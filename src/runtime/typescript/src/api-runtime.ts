/**
 * API Runtime - Singleton for auto-starting Express/API services with mesh.
 *
 * This module provides auto-initialization for API services (Express, etc.)
 * that use mesh.route() for dependency injection. When the first mesh.route()
 * is called, the runtime schedules itself to start via process.nextTick(),
 * allowing all routes to be registered before connecting to the mesh.
 *
 * Key differences from MCP agents:
 * - Uses agent_type: "api" (not "mcp_agent")
 * - Port doesn't matter (API services are not called via mesh)
 * - Only consumes capabilities, never provides them
 *
 * @example
 * ```typescript
 * import express from "express";
 * import { mesh } from "@mcpmesh/sdk";
 *
 * const app = express();
 *
 * // mesh.route() triggers auto-init via nextTick
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, { calculator }) => {
 *     res.json({ result: await calculator({ a: 1, b: 2 }) });
 *   }
 * ));
 *
 * app.listen(3000); // Mesh already started
 * ```
 */

import {
  startAgent,
  resolveConfig,
  resolveConfigInt,
  autoDetectIp,
  type JsAgentSpec,
  type JsAgentHandle,
  type JsToolSpec,
  type JsDependencySpec,
} from "@mcpmesh/core";

import { RouteRegistry, type RouteMetadata } from "./route.js";
import { createProxy } from "./proxy.js";
import { initTracing, type AgentMetadata } from "./tracing.js";

/**
 * Build tool specs from registered routes.
 * Shared helper to avoid duplication between start() and updateExpressInfo().
 */
function buildToolSpecs(routes: RouteMetadata[]): JsToolSpec[] {
  return routes
    .filter((route) => route.dependencies.length > 0)
    .map((route) => ({
      functionName: route.routeId,
      capability: "", // API routes don't provide capabilities
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
 * Configuration for API runtime (optional, uses env vars if not set).
 */
export interface ApiRuntimeConfig {
  /** API service name prefix. Env: MCP_MESH_AGENT_NAME. Default: "api" */
  name?: string;
  /** Namespace for isolation. Env: MCP_MESH_NAMESPACE. Default: "default" */
  namespace?: string;
  /** Registry URL. Env: MCP_MESH_REGISTRY_URL. Default: "http://localhost:8000" */
  registryUrl?: string;
  /** Heartbeat interval in seconds. Env: MCP_MESH_HEALTH_INTERVAL. Default: 5 */
  heartbeatInterval?: number;
  /** Port the Express app is listening on (for registry display) */
  port?: number;
}

/**
 * Singleton API runtime that manages mesh connection for Express/API services.
 *
 * - Auto-starts when first mesh.route() is called
 * - Uses agent_type: "api" for registration
 * - Handles dependency resolution events
 */
class ApiRuntime {
  private static instance: ApiRuntime | null = null;

  private config: ApiRuntimeConfig = {};
  private serviceId: string = "";
  private handle: JsAgentHandle | null = null;
  private started = false;
  private starting = false;
  private scheduledStart = false;
  private shutdownRequested = false;

  private constructor() {}

  static getInstance(): ApiRuntime {
    if (!ApiRuntime.instance) {
      ApiRuntime.instance = new ApiRuntime();
    }
    return ApiRuntime.instance;
  }

  /**
   * Reset the runtime (mainly for testing).
   */
  static reset(): void {
    if (ApiRuntime.instance?.handle) {
      ApiRuntime.instance.handle.shutdown().catch(() => {});
    }
    ApiRuntime.instance = null;
  }

  /**
   * Configure the runtime (optional, can be called before routes are defined).
   * Environment variables take precedence over config values.
   */
  configure(config: ApiRuntimeConfig): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * Schedule the runtime to start on next tick.
   * Called automatically when first mesh.route() is invoked.
   */
  scheduleStart(): void {
    if (this.started || this.starting || this.scheduledStart) {
      return;
    }

    this.scheduledStart = true;

    // Use process.nextTick to start after all routes are registered
    process.nextTick(() => {
      this.start().catch((err) => {
        console.error("ApiRuntime auto-start failed:", err);
        // Don't exit - the app may still work with degraded functionality
      });
    });
  }

  /**
   * Start the API runtime - connects to mesh and handles dependency events.
   */
  async start(): Promise<void> {
    if (this.started) return;
    if (this.starting) {
      // Wait for existing start to complete
      while (this.starting) {
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      return;
    }

    this.starting = true;

    try {
      // Generate service ID: "api-<random-suffix>"
      const namePart = resolveConfig("agent_name", this.config.name) || "api";
      const suffix = Math.random().toString(36).substring(2, 10);
      this.serviceId = `${namePart}-${suffix}`;

      console.log(`Starting API runtime: ${this.serviceId}`);

      // Resolve configuration with env var precedence
      const registryUrl = resolveConfig(
        "registry_url",
        this.config.registryUrl
      );
      const namespace = resolveConfig("namespace", this.config.namespace);
      const heartbeatInterval =
        resolveConfigInt(
          "health_interval",
          this.config.heartbeatInterval ?? null
        ) ?? 5;

      // Get port from config, env var, or default to 0
      // Common pattern: apps use PORT env var
      const port = this.config.port ??
        (process.env.PORT ? parseInt(process.env.PORT, 10) : 0);

      // Initialize distributed tracing
      const agentMetadata: AgentMetadata = {
        agentId: this.serviceId,
        agentName: namePart,
        agentNamespace: namespace,
        agentHostname: autoDetectIp(),
        agentIp: autoDetectIp(),
        agentPort: port,
        agentEndpoint: port > 0 ? `http://${autoDetectIp()}:${port}` : "",
      };
      await initTracing(agentMetadata);

      // Build tool specs from registered routes
      const registry = RouteRegistry.getInstance();
      const routes = registry.getRoutes();
      const tools = buildToolSpecs(routes);

      // Create AgentSpec with agent_type: "api"
      const spec: JsAgentSpec = {
        name: this.serviceId,
        version: "1.0.0",
        description: "",
        registryUrl,
        httpPort: port,
        httpHost: autoDetectIp(),
        namespace,
        agentType: "api", // API services only consume capabilities
        tools,
        heartbeatInterval,
      };

      // Start the agent via Rust core
      this.handle = startAgent(spec);

      // Count total dependencies
      const totalDeps = routes.reduce((sum, r) => sum + r.dependencies.length, 0);
      console.log(
        `API runtime registered: ${routes.length} routes with ${totalDeps} dependencies`
      );

      // Start event loop in background
      this.runEventLoop();

      // Install signal handlers for graceful shutdown
      this.installSignalHandlers();

      this.started = true;
    } finally {
      this.starting = false;
    }
  }

  /**
   * Run the event loop to handle mesh events.
   */
  private async runEventLoop(): Promise<void> {
    if (!this.handle) return;

    const registry = RouteRegistry.getInstance();

    while (true) {
      try {
        // Check if handle was nulled during shutdown
        if (!this.handle) {
          console.log("API runtime event loop: handle nulled, exiting");
          return;
        }

        const event = await this.handle.nextEvent();

        switch (event.eventType) {
          case "agent_registered":
            console.log(`API service registered: ${event.agentId}`);
            break;

          case "registration_failed":
            console.error(`API registration failed: ${event.error}`);
            break;

          case "dependency_available":
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

          case "dependency_unavailable":
            this.handleDependencyUnavailable(
              registry,
              event.capability!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "registry_connected":
            console.log("API runtime connected to registry");
            break;

          case "registry_disconnected":
            console.warn(`API runtime disconnected: ${event.reason}`);
            registry.clearAllDependencies();
            break;

          case "shutdown":
            console.log("API runtime shutting down");
            return;

          default:
            break;
        }
      } catch (err) {
        console.error("API runtime event loop error:", err);
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
        `Dependency available: ${capability} at ${endpoint} (route: ${requestingFunction}, agent: ${agentId})`
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
      `Dependency available: ${capability} at ${endpoint} (${matchCount} routes)`
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
      console.log(`Dependency unavailable: ${capability} (route: ${requestingFunction})`);
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

    console.log(`Dependency unavailable: ${capability} (${removeCount} routes)`);
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

      console.log(`\nReceived ${signal}, shutting down ${this.serviceId}...`);

      // Call shutdown directly - this triggers Rust core to unregister
      // and send a shutdown event that breaks the event loop
      if (this.handle) {
        this.handle.shutdown().then(() => {
          console.log(`API runtime ${this.serviceId} unregistered from registry`);
          process.exit(0);
        }).catch((err) => {
          console.error("Error during API runtime shutdown:", err);
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
   * Shutdown the API runtime gracefully.
   */
  async shutdown(): Promise<void> {
    if (this.handle) {
      await this.handle.shutdown();
      this.handle = null;
    }
  }

  /**
   * Get the service ID.
   */
  getServiceId(): string {
    return this.serviceId;
  }

  /**
   * Check if the runtime is started.
   */
  isStarted(): boolean {
    return this.started;
  }

  /**
   * Update Express info detected on first request.
   * Called by route middleware when auto-detection runs.
   *
   * After introspection, this method updates the Rust core with:
   * 1. Updated tools with proper route names (e.g., "GET:/time" instead of "route_0_UNKNOWN:UNKNOWN")
   * 2. Detected HTTP port
   *
   * The Rust core uses smart diffing - only sends a heartbeat if tools actually changed.
   *
   * @param port - Port detected from req.socket.localPort
   * @param routeCount - Number of routes discovered via introspection
   */
  updateExpressInfo(port: number, routeCount: number): void {
    if (!this.handle) {
      console.warn("Cannot update Express info: handle not available");
      return;
    }

    // Update port if detected
    if (port > 0) {
      this.config.port = port;
      // Send port update to Rust core (triggers heartbeat if changed)
      this.handle.updatePort(port).catch((err) => {
        console.warn("Failed to update port:", err);
      });
    }

    // Build updated tool specs with proper route names
    const registry = RouteRegistry.getInstance();
    const routes = registry.getRoutes();
    const tools = buildToolSpecs(routes);

    // Send updated tools to Rust core
    // The Rust core uses smart diffing - only sends heartbeat if tools changed
    this.handle.updateTools(tools).then((sent) => {
      if (sent) {
        console.log(
          `Express auto-detected: port ${port}, ${routeCount} mesh routes updated`
        );
      }
    }).catch((err) => {
      console.warn("Failed to update tools:", err);
    });
  }
}

// Export singleton instance getter
export function getApiRuntime(): ApiRuntime {
  return ApiRuntime.getInstance();
}

/**
 * Introspect Express app to discover route method/path for mesh routes.
 *
 * Express 4 stores routes in app._router.stack
 * Express 5 stores routes in app.router.stack
 *
 * Each layer has:
 * - route.path: the path pattern
 * - route.methods: object with method flags { get: true, post: true, ... }
 * - route.stack[0].handle: the handler function
 *
 * We match handlers by looking for our _meshRouteId marker.
 */
export function introspectExpressRoutes(app: unknown): number {
  const registry = RouteRegistry.getInstance();
  let updatedCount = 0;

  // Access Express internal router (Express 5 uses .router, Express 4 uses ._router)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const expressApp = app as any;
  const router = expressApp.router || expressApp._router;

  if (!router || !router.stack) {
    console.warn("Express router not found - routes may not be registered yet");
    return 0;
  }

  // Iterate through router stack
  for (const layer of router.stack) {
    if (!layer.route) continue; // Skip middleware layers

    const route = layer.route;
    const path = route.path;
    const methods = Object.keys(route.methods)
      .filter((m) => route.methods[m])
      .map((m) => m.toUpperCase());

    // Check each handler in the route stack
    for (const routeLayer of route.stack) {
      const handler = routeLayer.handle;

      // Check if this handler was created by mesh.route()
      if (handler && handler._meshRouteId) {
        const oldRouteId = handler._meshRouteId;
        const method = methods[0] || "GET"; // Use first method

        // Update the registry with proper method/path
        registry.updateRouteInfo(oldRouteId, method, path);

        // Update the handler's route ID reference (both direct and via ref object)
        const newRouteId = `${method}:${path}`;
        handler._meshRouteId = newRouteId;
        if (handler._meshRouteRef) {
          handler._meshRouteRef.id = newRouteId;
        }

        updatedCount++;
      }
    }
  }

  return updatedCount;
}

/**
 * Bind mesh to an Express app, introspecting routes for proper naming.
 *
 * This is OPTIONAL - everything works without it, but route names in logs
 * will be "route_0_UNKNOWN:UNKNOWN" instead of "GET:/time".
 *
 * Port is auto-detected from PORT env var.
 *
 * @param app - Express application instance
 * @returns Number of routes discovered
 *
 * @example
 * ```typescript
 * const app = express();
 *
 * app.get("/time", mesh.route([...], handler));
 * app.get("/status", mesh.route([...], handler));
 *
 * // Optional: get proper route names in logs
 * mesh.bind(app);
 *
 * app.listen(process.env.PORT || 4000);
 * ```
 */
export function bindToExpress(app: unknown): number {
  // Introspect routes for proper naming
  const count = introspectExpressRoutes(app);

  if (count > 0) {
    console.log(`Mesh bound to Express: ${count} routes discovered`);
  }

  return count;
}

// Export for testing
export { ApiRuntime };
