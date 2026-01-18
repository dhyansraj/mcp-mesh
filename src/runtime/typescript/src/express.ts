/**
 * MeshExpress: Express app integration with MCP Mesh.
 *
 * Provides automatic registration with mesh registry and dependency injection
 * for Express route handlers. Uses agent_type: "api" since API services only
 * consume capabilities, they don't provide them.
 *
 * **Note:** For simpler usage, just use `mesh.route()` without `meshExpress()`.
 * The API runtime auto-initializes when the first `mesh.route()` is called.
 *
 * @example Simple usage (recommended)
 * ```typescript
 * import express from "express";
 * import { mesh } from "@mcpmesh/sdk";
 *
 * const app = express();
 * app.use(express.json());
 *
 * // mesh.route() auto-initializes the mesh connection
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, { calculator }) => {
 *     res.json({ result: await calculator({ a: req.body.a, b: req.body.b }) });
 *   }
 * ));
 *
 * app.listen(3000);
 * ```
 *
 * @example Explicit control (advanced)
 * ```typescript
 * import express from "express";
 * import { meshExpress, mesh } from "@mcpmesh/sdk";
 *
 * const app = express();
 * const meshApp = meshExpress(app, { name: "my-api", port: 3000 });
 *
 * app.post("/compute", mesh.route(...));
 *
 * meshApp.start();
 * ```
 */

import type { Application, Request, Response } from "express";
import type { Server } from "http";
import {
  startAgent,
  type JsAgentSpec,
  type JsAgentHandle,
  type JsToolSpec,
  type JsDependencySpec,
} from "@mcpmesh/core";

import type { AgentConfig, ResolvedAgentConfig } from "./types.js";
import { resolveConfig, generateAgentIdSuffix } from "./config.js";
import { createProxy } from "./proxy.js";
import { RouteRegistry, type RouteMetadata } from "./route.js";
import { initTracing, type AgentMetadata } from "./tracing.js";

/**
 * Build tool specs from registered routes.
 * Shared helper for consistent tool spec generation.
 */
function buildToolSpecs(routes: RouteMetadata[]): JsToolSpec[] {
  return routes
    .filter((route) => route.dependencies.length > 0)
    .map((route) => ({
      functionName: route.routeId,
      capability: "", // Routes don't provide capabilities, they consume them
      version: "1.0.0",
      tags: [],
      description: "",
      dependencies: route.dependencies.map(
        (dep): JsDependencySpec => ({
          capability: dep.capability,
          tags: dep.tags,
          version: dep.version,
        })
      ),
      inputSchema: undefined,
    }));
}

/**
 * Configuration for MeshExpress.
 * Extends AgentConfig with Express-specific options.
 */
export interface MeshExpressConfig extends AgentConfig {
  /**
   * If true, automatically start when the module loads.
   * Defaults to false for Express (explicit start preferred).
   */
  autoStart?: boolean;
}

/**
 * MeshExpress wraps an Express app with MCP Mesh capabilities.
 *
 * Provides:
 * - Registration with mesh registry via Rust core
 * - Heartbeat management
 * - Dependency resolution for route handlers
 * - Distributed tracing
 */
export class MeshExpress {
  private app: Application;
  private config: ResolvedAgentConfig;
  private serviceId: string;
  private handle: JsAgentHandle | null = null;
  private server: Server | null = null;
  private started = false;
  private shutdownRequested = false;

  constructor(app: Application, config: MeshExpressConfig) {
    this.app = app;

    // Resolve config with env var precedence: ENV > config > defaults
    this.config = resolveConfig(config);

    // Generate unique service ID with suffix (e.g., "my-api-a1b2c3d4")
    this.serviceId = `${this.config.name}-${generateAgentIdSuffix()}`;

    // Add health check endpoint
    this.setupHealthEndpoints();

    // Auto-start if configured (but default is false for Express)
    if (config.autoStart) {
      process.nextTick(() => {
        this.start().catch((err) => {
          console.error("MeshExpress auto-start failed:", err);
          process.exit(1);
        });
      });
    }
  }

  /**
   * Setup health check endpoints for the registry.
   */
  private setupHealthEndpoints(): void {
    // Health check endpoint for registry
    this.app.get("/health", (_req: Request, res: Response) => {
      res.json({ status: "healthy", serviceId: this.serviceId });
    });

    // Ready check endpoint
    this.app.get("/ready", (_req: Request, res: Response) => {
      const isReady = this.handle !== null;
      res.status(isReady ? 200 : 503).json({
        ready: isReady,
        serviceId: this.serviceId,
      });
    });
  }

  /**
   * Start the Express server and register with mesh.
   */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;

    console.log(`Starting MeshExpress service: ${this.serviceId}`);

    // 0. Initialize distributed tracing
    const agentMetadata: AgentMetadata = {
      agentId: this.serviceId,
      agentName: this.config.name,
      agentNamespace: this.config.namespace,
      agentHostname: this.config.host,
      agentIp: this.config.host,
      agentPort: this.config.port,
      agentEndpoint: `http://${this.config.host}:${this.config.port}`,
    };
    await initTracing(agentMetadata);

    // 1. Start HTTP server
    await this.startServer();

    // 2. Start heartbeat to registry via Rust core
    await this.startHeartbeat();

    // 3. Install signal handlers for graceful shutdown
    this.installSignalHandlers();
  }

  /**
   * Start the Express HTTP server.
   */
  private startServer(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.server = this.app.listen(this.config.port, "0.0.0.0", () => {
          console.log(`Service listening on port ${this.config.port}`);
          resolve();
        });

        this.server.on("error", (err) => {
          reject(err);
        });
      } catch (err) {
        reject(err);
      }
    });
  }

  /**
   * Start the Rust core heartbeat loop.
   */
  private async startHeartbeat(): Promise<void> {
    const registry = RouteRegistry.getInstance();
    const routes = registry.getRoutes();
    const tools = buildToolSpecs(routes);

    const spec: JsAgentSpec = {
      name: this.serviceId,
      version: this.config.version,
      description: this.config.description,
      registryUrl: this.config.registryUrl,
      httpPort: this.config.port,
      httpHost: this.config.host,
      namespace: this.config.namespace,
      agentType: "api", // API services only consume capabilities, not provide them
      tools,
      heartbeatInterval: this.config.heartbeatInterval,
    };

    // Start the agent via Rust core
    this.handle = startAgent(spec);

    // Count total dependencies
    const totalDeps = routes.reduce((sum, r) => sum + r.dependencies.length, 0);
    console.log(
      `Registered ${routes.length} routes with registry (${totalDeps} dependencies)`
    );

    // Start event loop (runs in background)
    this.runEventLoop();
  }

  /**
   * Run the event loop to handle mesh events.
   */
  private async runEventLoop(): Promise<void> {
    if (!this.handle) return;

    const registry = RouteRegistry.getInstance();

    while (true) {
      try {
        const event = await this.handle.nextEvent();

        switch (event.eventType) {
          case "agent_registered":
            console.log(`Service registered with ID: ${event.agentId}`);
            break;

          case "registration_failed":
            console.error(`Registration failed: ${event.error}`);
            break;

          case "dependency_available":
            this.handleDependencyAvailable(
              registry,
              event.capability!,
              event.endpoint!,
              event.functionName!,
              event.agentId!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "dependency_unavailable":
            this.handleDependencyUnavailable(
              registry,
              event.capability!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "dependency_changed":
            this.handleDependencyAvailable(
              registry,
              event.capability!,
              event.endpoint!,
              event.functionName!,
              event.agentId!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "registry_connected":
            console.log("Connected to registry");
            break;

          case "registry_disconnected":
            console.warn(`Disconnected from registry: ${event.reason}`);
            registry.clearAllDependencies();
            break;

          case "shutdown":
            console.log("Service shutting down");
            return;

          default:
            break;
        }
      } catch (err) {
        console.error("Event loop error:", err);
        break;
      }
    }
  }

  /**
   * Handle dependency_available event.
   */
  private handleDependencyAvailable(
    registry: RouteRegistry,
    capability: string,
    endpoint: string,
    functionName: string,
    agentId: string,
    requestingFunction?: string,
    depIndex?: number
  ): void {
    // If we have position info, use it directly
    if (requestingFunction !== undefined && depIndex !== undefined) {
      const route = registry.getRoute(requestingFunction);
      const kwargs = route?.dependencyKwargs?.[depIndex];

      const proxy = createProxy(endpoint, capability, functionName, kwargs);
      registry.setDependency(requestingFunction, depIndex, proxy);

      console.log(
        `Dependency available: ${capability} at ${endpoint} (route: ${requestingFunction}, index: ${depIndex}, agent: ${agentId})`
      );
      return;
    }

    // Fallback: match by capability across all routes
    let matchCount = 0;
    for (const route of registry.getRoutes()) {
      route.dependencies.forEach((dep, idx) => {
        if (dep.capability === capability) {
          const kwargs = route.dependencyKwargs?.[idx];
          const proxy = createProxy(endpoint, capability, functionName, kwargs);
          registry.setDependency(route.routeId, idx, proxy);
          matchCount++;
        }
      });
    }

    console.log(
      `Dependency available: ${capability} at ${endpoint} (agent: ${agentId}, ${matchCount} route bindings)`
    );
  }

  /**
   * Handle dependency_unavailable event.
   */
  private handleDependencyUnavailable(
    registry: RouteRegistry,
    capability: string,
    requestingFunction?: string,
    depIndex?: number
  ): void {
    // If we have position info, use it directly
    if (requestingFunction !== undefined && depIndex !== undefined) {
      registry.removeDependency(requestingFunction, depIndex);
      console.log(
        `Dependency unavailable: ${capability} (route: ${requestingFunction}, index: ${depIndex})`
      );
      return;
    }

    // Fallback: match by capability across all routes
    let removeCount = 0;
    for (const route of registry.getRoutes()) {
      route.dependencies.forEach((dep, idx) => {
        if (dep.capability === capability) {
          registry.removeDependency(route.routeId, idx);
          removeCount++;
        }
      });
    }

    console.log(
      `Dependency unavailable: ${capability} (${removeCount} route bindings removed)`
    );
  }

  /**
   * Install signal handlers for graceful shutdown.
   *
   * Calls handle.shutdown() directly to trigger Rust core unregistration.
   * This causes nextEvent() to return with a "shutdown" event, breaking
   * the event loop cleanly.
   */
  private installSignalHandlers(): void {
    const shutdownHandler = (signal: string) => {
      if (this.shutdownRequested) return;
      this.shutdownRequested = true;

      console.log(
        `\nReceived ${signal}, shutting down service ${this.serviceId}...`
      );

      // Call shutdown directly - this triggers Rust core to unregister
      // and send a shutdown event that breaks the event loop
      if (this.handle) {
        this.handle.shutdown().then(() => {
          console.log(`Service ${this.serviceId} unregistered from registry`);
          process.exit(0);
        }).catch((err) => {
          console.error("Error during shutdown:", err);
          process.exit(1);
        });
      } else {
        process.exit(0);
      }
    };

    process.on("SIGINT", () => shutdownHandler("SIGINT"));
    process.on("SIGTERM", () => shutdownHandler("SIGTERM"));
  }

  /**
   * Get the service ID.
   */
  getServiceId(): string {
    return this.serviceId;
  }

  /**
   * Get the resolved configuration.
   */
  getConfig(): ResolvedAgentConfig {
    return this.config;
  }

  /**
   * Get the underlying Express app.
   */
  getApp(): Application {
    return this.app;
  }

  /**
   * Get the HTTP server instance.
   */
  getServer(): Server | null {
    return this.server;
  }

  /**
   * Get the agent handle for advanced operations.
   */
  getHandle(): JsAgentHandle | null {
    return this.handle;
  }

  /**
   * Shutdown the service gracefully.
   */
  async shutdown(): Promise<void> {
    if (this.handle) {
      await this.handle.shutdown();
      this.handle = null;
    }

    if (this.server) {
      await new Promise<void>((resolve) => {
        this.server!.close(() => resolve());
      });
      this.server = null;
    }
  }
}

/**
 * Create a MeshExpress instance wrapping an Express app.
 *
 * @example
 * ```typescript
 * const app = express();
 * const meshApp = meshExpress(app, { name: "my-api", port: 3000 });
 *
 * // Define routes with mesh.route()...
 *
 * meshApp.start();
 * ```
 */
export function meshExpress(
  app: Application,
  config: MeshExpressConfig
): MeshExpress {
  return new MeshExpress(app, config);
}
