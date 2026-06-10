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

import {
  MAX_CONSECUTIVE_NEXT_EVENT_FAILURES,
  NEXT_EVENT_BACKOFF_CAP_MS,
} from "./config.js";
import { RouteRegistry, type RouteMetadata } from "./route.js";
import { createProxy } from "./proxy.js";
import { initTracing, type AgentMetadata } from "./tracing.js";
import { getTlsConfigCached, prepareTls, cleanupTls } from "./tls-config.js";
import { A2AProducerRegistry } from "./a2a/producer/registry.js";

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
      // Note: tags may contain nested arrays for OR alternatives (TagSpec[])
      // Serialize to JSON for Rust binding - preserves nested structure
      dependencies: route.dependencies.map(
        (dep): JsDependencySpec => ({
          capability: dep.capability,
          tags: JSON.stringify(dep.tags ?? []),
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
  /** Heartbeat interval in seconds. Env: MCP_MESH_HEALTH_INTERVAL. Default: 5 */
  heartbeatInterval?: number;
  /** HTTP port the Express app is listening on (for registry display) */
  httpPort?: number;
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
  /**
   * Memoized in-flight (or completed) teardown. `shutdown()` is
   * idempotent: the first caller creates this promise and every later
   * caller — user code, the signal handler, a second signal — awaits
   * the SAME teardown instead of racing a concurrent napi
   * `handle.shutdown()`.
   */
  private shutdownPromise: Promise<void> | null = null;
  /**
   * PR #938 W2: race-flag for `pushSurfacesUpdate()` calls that arrive
   * AFTER `start()` has been scheduled but BEFORE `this.handle` is set.
   * `start()` does async work (TLS prep, tracing init) between
   * `scheduleStart()` and `this.handle = startAgent(spec)`; a `mesh.a2a.mount(...)`
   * fired during that gap would otherwise be silently dropped — the
   * push early-returns on `!this.handle` AND the startup-time spec was
   * built before the mount landed. We flush once after the handle is set.
   */
  private pendingSurfacesPush = false;

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
      // Generate service ID: "<base>-<random-suffix>".
      // Unnamed API services default to "api" — set MCP_MESH_AGENT_NAME to disambiguate.
      const namePart = resolveConfig("agent_name", this.config.name) || "api";
      const suffix = Math.random().toString(36).substring(2, 10);
      this.serviceId = `${namePart}-${suffix}`;

      console.log(`Starting API runtime: ${this.serviceId}`);

      // Registry URL only from env var MCP_MESH_REGISTRY_URL
      const registryUrl = resolveConfig("registry_url", null);
      const namespace = resolveConfig("namespace", this.config.namespace);
      const heartbeatInterval =
        resolveConfigInt(
          "health_interval",
          this.config.heartbeatInterval ?? null
        ) ?? 5;

      // Get port from MCP_MESH_HTTP_PORT env var, config, or default to 0
      const port = resolveConfigInt("http_port", this.config.httpPort ?? null) ?? 0;

      // Prepare TLS credentials (fetches from Vault if configured)
      prepareTls(this.serviceId);

      // Initialize distributed tracing
      const tlsConfig = getTlsConfigCached();
      const scheme = tlsConfig.enabled ? "https" : "http";
      const agentMetadata: AgentMetadata = {
        agentId: this.serviceId,
        agentName: namePart,
        agentNamespace: namespace,
        agentHostname: autoDetectIp(),
        agentIp: autoDetectIp(),
        agentPort: port,
        agentEndpoint: port > 0 ? `${scheme}://${autoDetectIp()}:${port}` : "",
      };
      await initTracing(agentMetadata);

      // Build tool specs from registered routes
      const registry = RouteRegistry.getInstance();
      const routes = registry.getRoutes();
      const tools = buildToolSpecs(routes);

      // Issue #933 / #938: flip agent_type to "a2a" when any
      // mesh.a2a.mount(...) surface is registered (spec §2.3 / §8). A2A
      // surfaces and mesh.route() / mesh.tool capabilities coexist on the
      // same agent; agent_type=a2a does NOT mean "no other routes/tools"
      // (matches Python's heartbeat_preparation.py:371-389). Centralized in
      // A2AProducerRegistry.buildAgentSpecContribution so the startup-time
      // value matches the post-mount push path (#938 fix).
      const { agentType, surfacesJson, a2aProducer } =
        A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");

      // Create AgentSpec
      const spec: JsAgentSpec = {
        // Base name (shared across replicas), unique ID via agentId.
        name: namePart,
        agentId: this.serviceId,
        version: "1.0.0",
        description: "",
        registryUrl,
        httpPort: port,
        httpHost: autoDetectIp(),
        namespace,
        agentType,
        tools,
        heartbeatInterval,
        surfaces: surfacesJson,
        // Issue #972: API runtime uses `mesh.route(...)` only; no consumer
        // marker on this code path, so consumer flag stays false in v1.
        // Field names are NAPI-camelCase (a2_ -> a2A).
        a2AProducer: a2aProducer,
        a2AConsumer: false,
      };

      // Start the agent via Rust core
      this.handle = startAgent(spec);

      // PR #938 W2: flush any deferred `pushSurfacesUpdate()` call that
      // arrived during the async window between `scheduleStart()` and
      // `this.handle` being set. The startup-time spec above already
      // captured the registry state at the moment we built `tools` /
      // `surfacesJson`, so a mount fired AFTER that snapshot would be
      // silently dropped without this flush. Smart-diffed inside the
      // Rust runtime, so the redundant push (when nothing actually
      // changed) is a no-op.
      if (this.pendingSurfacesPush) {
        this.pendingSurfacesPush = false;
        this.pushSurfacesUpdate();
      }

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
   *
   * Resilience (issue #1163 MED-1): the loop must outlive individual
   * failures. A throw from an event handler (e.g. a malformed event
   * hitting a non-null assertion) is logged and the loop continues; a
   * `nextEvent()` rejection (e.g. a transient napi failure) backs off
   * exponentially (capped) and retries. Only the "shutdown" event — or
   * the handle being torn down — exits the loop.
   */
  private async runEventLoop(): Promise<void> {
    if (!this.handle) return;

    const registry = RouteRegistry.getInstance();
    let consecutiveNextEventFailures = 0;

    while (true) {
      // Check if handle was nulled during shutdown
      if (!this.handle) {
        console.log("API runtime event loop: handle nulled, exiting");
        return;
      }

      let event: Awaited<ReturnType<JsAgentHandle["nextEvent"]>>;
      try {
        event = await this.handle.nextEvent();
        consecutiveNextEventFailures = 0;
      } catch (err) {
        // Explicit shutdown() racing a failing nextEvent(): exit
        // promptly instead of burning more backoff cycles.
        if (!this.handle || this.shutdownRequested) {
          console.log("API runtime event loop: shutdown requested, exiting");
          return;
        }
        consecutiveNextEventFailures++;
        // Ceiling (~60s of continuous failure — see the constant's doc
        // in config.ts): a permanently broken handle must not retry
        // forever, keeping the process alive via the backoff timer.
        if (
          consecutiveNextEventFailures >= MAX_CONSECUTIVE_NEXT_EVENT_FAILURES
        ) {
          console.error(
            `API runtime event loop: terminating after ${consecutiveNextEventFailures} ` +
              `consecutive nextEvent() failures; dependency topology is ` +
              `frozen for the remainder of the process:`,
            err
          );
          return;
        }
        const backoffMs = Math.min(
          100 * 2 ** (consecutiveNextEventFailures - 1),
          NEXT_EVENT_BACKOFF_CAP_MS
        );
        console.error(
          `API runtime event loop: nextEvent() failed ` +
            `(consecutive=${consecutiveNextEventFailures}), retrying in ${backoffMs}ms:`,
          err
        );
        await new Promise((resolve) => setTimeout(resolve, backoffMs));
        continue;
      }

      try {
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
            // #1131: Log only — RETAIN resolved dependencies on a registry
            // (control-plane) blip. Already-resolved dependency endpoints are
            // data-plane: direct agent→agent connections that stay valid while
            // the registry is unreachable. Clearing them here would permanently
            // sever those connections, since the Rust core never resets topology
            // and its diff gate re-emits only CHANGED deps on reconnect (so the
            // unchanged, still-valid ones would never come back). Matches the
            // cross-runtime reference behavior (MeshAgent, Python, Java).
            console.warn(`API runtime disconnected: ${event.reason}`);
            break;

          case "shutdown":
            console.log("API runtime shutting down");
            return;

          default:
            break;
        }
      } catch (err) {
        // Per-event isolation: a bad event (or a bug in one handler)
        // must not kill dependency-event processing for the process
        // lifetime. Log and keep consuming events.
        console.error(
          `API runtime event loop: error handling event '${event.eventType}':`,
          err
        );
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
   * Runs the full `shutdown()` sequence (issue #1163 MED-2) — registry
   * unregister via `handle.shutdown()` (which also resolves the event
   * loop's `nextEvent()` with a "shutdown" event) plus TLS cleanup —
   * bounded by a force-exit timer so a hang cannot wedge the process
   * past its SIGTERM grace.
   */
  private installSignalHandlers(): void {
    const SIGNAL_SHUTDOWN_TIMEOUT_MS = 10_000;
    // Dedupe repeated signals locally. This must NOT key off
    // `shutdownRequested` (set by shutdown() itself): a signal arriving
    // while a user-initiated shutdown() is in flight must still arm the
    // force-exit timer and exit the process when that same (memoized)
    // shutdown completes.
    let signalHandled = false;
    const shutdownHandler = (signal: string) => {
      if (signalHandled) return;
      signalHandled = true;

      console.log(`\nReceived ${signal}, shutting down ${this.serviceId}...`);

      // Deliberately ref'd (no unref): both completion paths below
      // clearTimeout and process.exit synchronously, so the timer never
      // delays a successful exit — but it must keep a wedged shutdown's
      // otherwise-empty event loop alive long enough to emit the loud
      // exit(1) diagnostic instead of silently exiting 0.
      const forceExitTimer = setTimeout(() => {
        console.error(
          `API runtime shutdown did not complete within ${SIGNAL_SHUTDOWN_TIMEOUT_MS}ms; forcing exit`
        );
        process.exit(1);
      }, SIGNAL_SHUTDOWN_TIMEOUT_MS);

      this.shutdown().then(() => {
        clearTimeout(forceExitTimer);
        console.log(`API runtime ${this.serviceId} shut down cleanly`);
        process.exit(0);
      }).catch((err) => {
        clearTimeout(forceExitTimer);
        console.error("Error during API runtime shutdown:", err);
        process.exit(1);
      });
    };

    process.on("SIGINT", () => shutdownHandler("SIGINT"));
    process.on("SIGTERM", () => shutdownHandler("SIGTERM"));
  }

  /**
   * Shutdown the API runtime gracefully.
   *
   * Idempotent and re-entrant: the first call runs the teardown; every
   * later call (user code, the signal handler, a double signal) returns
   * the SAME promise. The memo is never cleared: shutdown is terminal,
   * and re-running a half-torn-down cleanup after a failure would be
   * worse than surfacing the original rejection to every caller.
   */
  shutdown(): Promise<void> {
    if (this.shutdownPromise) return this.shutdownPromise;
    this.shutdownRequested = true;
    this.shutdownPromise = (async () => {
      if (this.handle) {
        await this.handle.shutdown();
        this.handle = null;
      }
      cleanupTls();
    })();
    return this.shutdownPromise;
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
  /**
   * Push the current A2A surfaces + agent_type into the Rust core (issue #938).
   *
   * Called from `mesh.a2a.mount(...)` after each surface registration so
   * deferred mounts (mounts registered after `startAgent()` / first
   * heartbeat) are reflected in the next heartbeat envelope rather than
   * silently dropped. Mirrors Python's per-heartbeat
   * `_build_a2a_surfaces` semantics (`heartbeat_preparation.py:371-389`).
   *
   * No-op when the runtime hasn't started yet — the value will be picked
   * up via `buildAgentSpecContribution()` at startup time. Smart-diffed
   * inside the Rust runtime, so re-mounting an identical payload doesn't
   * generate a redundant heartbeat.
   */
  pushSurfacesUpdate(): void {
    if (this.handle === null) {
      // Runtime hasn't been started yet, OR start() is mid-flight (async
      // gap between `scheduleStart()` and `this.handle = startAgent(spec)`).
      //
      // PR #938 W2 — the gap case: a mount fired during start()'s async
      // work (TLS prep / tracing init) would be silently dropped without
      // this flag. The startup-time spec was already built; without a
      // replay, the mount lands in the registry but never reaches the
      // Rust core. Set a flag so `start()` flushes us right after
      // `this.handle` is set.
      //
      // The pure pre-`scheduleStart()` case (flag stays unread, nothing
      // started) is still a no-op — `start()` will pick up the current
      // registry state via `buildAgentSpecContribution()` when it runs.
      if (this.starting) {
        this.pendingSurfacesPush = true;
      }
      return;
    }
    const { agentType, surfacesJson } =
      A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");
    this.handle
      .updateSurfaces(agentType, surfacesJson ?? null)
      .catch((err) => {
        console.warn("Failed to push A2A surfaces update:", err);
      });
  }

  updateExpressInfo(port: number, routeCount: number): void {
    if (!this.handle) {
      console.warn("Cannot update Express info: handle not available");
      return;
    }

    // Update port if detected
    if (port > 0) {
      this.config.httpPort = port;
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

  // Access Express internal router (Express 4 uses ._router, Express 5 uses .router)
  // Note: Express 4 throws deprecation error if you access .router, so try _router first
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const expressApp = app as any;
  const router = expressApp._router || expressApp.router;

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
