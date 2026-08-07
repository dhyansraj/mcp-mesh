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
 *   async (req, res, [calculator]) => {
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
 * const meshApp = meshExpress(app, { name: "my-api", httpPort: 3000 });
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
import {
  resolveConfig,
  generateAgentIdSuffix,
  resolveStartupBindPort,
  MAX_CONSECUTIVE_NEXT_EVENT_FAILURES,
  NEXT_EVENT_BACKOFF_CAP_MS,
} from "./config.js";
import {
  buildStartupBody,
  runStartupCheck,
  startupStatusCodeFor,
} from "./startup-check.js";
import {
  startHealthCheckLoop,
  type HealthCheckLoop,
  type HealthVerdict,
} from "./health-check.js";
import { buildHealthBody, statusCodeFor } from "./health-routes.js";
import { createProxy } from "./proxy.js";
import { RouteRegistry, type RouteMetadata } from "./route.js";
import { initTracing, type AgentMetadata } from "./tracing.js";
import { getTlsConfigCached, getTlsOptions, prepareTls, cleanupTls } from "./tls-config.js";
import {
  clusterStrictEnabled,
  normalizeSchemaWithPolicy,
} from "./schema-normalize.js";
import { A2AProducerRegistry } from "./a2a/producer/registry.js";

/**
 * Build tool specs from registered routes.
 * Shared helper for consistent tool spec generation.
 */
function buildToolSpecs(routes: RouteMetadata[]): JsToolSpec[] {
  // Issue #547 Phase 4: cluster strict knob promotes WARN→BLOCK. Routes are
  // consumer-side so there's no per-tool override.
  const clusterStrict = clusterStrictEnabled();

  return routes
    .filter((route) => route.dependencies.length > 0)
    .map((route) => ({
      functionName: route.routeId,
      capability: "", // Routes don't provide capabilities, they consume them
      version: "1.0.0",
      tags: [],
      description: "",
      // Note: tags may contain nested arrays for OR alternatives (TagSpec[])
      // Serialize to JSON for Rust binding - preserves nested structure
      dependencies: route.dependencies.map(
        (dep): JsDependencySpec => {
          // Issue #547: per-dep expectedSchema → canonical + hash + matchMode.
          let expectedCanonical: string | undefined;
          let expectedHash: string | undefined;
          if (dep.expectedSchemaRaw) {
            const r = normalizeSchemaWithPolicy(
              dep.expectedSchemaRaw,
              `route ${route.routeId} dependency on '${dep.capability}'`,
              clusterStrict,
              true
            );
            expectedCanonical = r.canonicalJson ?? undefined;
            expectedHash = r.hash ?? undefined;
          }
          return {
            capability: dep.capability,
            tags: JSON.stringify(dep.tags ?? []),
            version: dep.version,
            expectedSchemaCanonical: expectedCanonical,
            expectedSchemaHash: expectedHash,
            matchMode: dep.matchMode,
            // Issue #1249: carry the required flag so the registry factors
            // this route edge into transitive availability. Only when true.
            required: dep.required ? true : undefined,
          };
        }
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
  /**
   * Memoized in-flight (or completed) teardown. `shutdown()` is
   * idempotent: the first caller creates this promise and every later
   * caller — user code, the signal handler, a second signal — awaits
   * the SAME teardown instead of racing a concurrent napi
   * `handle.shutdown()` / `server.close()`.
   */
  private shutdownPromise: Promise<void> | null = null;
  /**
   * This instance's own SIGINT/SIGTERM handler references, kept so
   * shutdown() can `process.off` them — otherwise sequential instances
   * in one process accumulate stale handlers whose memoized (already
   * resolved) shutdown() would `process.exit(0)` on the next signal.
   */
  private signalHandlers: {
    sigint: () => void;
    sigterm: () => void;
  } | null = null;
  /**
   * The `healthCheck` refresh loop (RFC #1502 step 3), or null when the
   * gateway declares no check. Same machinery as `MeshAgent` — see
   * {@link startHealthRefresh}.
   */
  private healthLoop: HealthCheckLoop | null = null;

  constructor(app: Application, config: MeshExpressConfig) {
    this.app = app;

    // Resolve config with env var precedence: ENV > config > defaults
    this.config = resolveConfig(config);

    // Generate unique service ID with suffix (e.g., "my-api-a1b2c3d4")
    this.serviceId = `${this.config.name}-${generateAgentIdSuffix()}`;

    // `healthCheck` is HONOURED here since RFC #1502 step 3; the loop
    // itself starts in `start()`, after the heartbeat. #1476 warned that it
    // was ignored on a gateway, on the grounds that withdrawing a fan-out
    // point takes the application down. Step 2 removed that harm: pausing
    // the heartbeat stops registry traffic ONLY — the Express server keeps
    // listening, resolved dependencies are retained (#1131), and `/ready`
    // reports the mesh runtime rather than the verdict, so the pod stays in
    // its Service endpoints and keeps taking ingress. A gateway that
    // reports unavailable stops being DISCOVERED; it does not go dark.

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
    // Diagnostic view of the `healthCheck` verdict (RFC #1502 step 3). It
    // used to be a fixed `healthy` because a gateway never ran the check;
    // now that a failing one withdraws the gateway, an endpoint that still
    // said "healthy" would be the only place an operator could look and the
    // one place that lied. Same body and same 200/503 rule as the MCP
    // agent's `/health` (`health-routes.ts`) — nothing probes it, so its
    // status code is free to carry the verdict.
    this.app.get("/health", (_req: Request, res: Response) => {
      const verdict = this.getHealthVerdict();
      res.status(statusCodeFor(verdict)).json({
        ...buildHealthBody(this.config.name, verdict),
        serviceId: this.serviceId,
      });
    });

    // Ready check endpoint
    this.app.get("/ready", (_req: Request, res: Response) => {
      const isReady = this.handle !== null;
      res.status(isReady ? 200 : 503).json({
        ready: isReady,
        serviceId: this.serviceId,
      });
    });

    // Liveness endpoint (issue #1467) — always 200 while the process is
    // up. Deliberately consults NOTHING: liveness must not share a URL
    // with readiness, or a dependency outage that should only make the
    // service unready restarts the pod instead. Mirrors Python's
    // `build_livez_response`.
    this.app.get("/livez", (_req: Request, res: Response) => {
      res.status(200).json({
        alive: true,
        agent: this.config.name,
        serviceId: this.serviceId,
        timestamp: new Date().toISOString(),
      });
    });

    // Startup endpoint (RFC #1502) — reports the user's `startupCheck`.
    //
    // Both hooks are honoured on a gateway (RFC #1502). What this one does
    // there is the milder of the two: it never withdraws a running fan-out
    // point, it only stops a misconfigured one from coming up, and a gateway
    // with a broken config should never come up.
    //
    // Registered as GET only, like the three above: Express routes HEAD to a
    // GET handler when no HEAD route exists, so HEAD answers with the same
    // status. The check runs per hit — startupProbe stops polling on first
    // success, so there is nothing to cache.
    this.app.get("/startupz", (_req: Request, res: Response) => {
      // `void` rather than an async handler: Express 4 does not handle a
      // rejected promise from a route handler, and runStartupCheck is
      // documented never to reject, so nothing is lost and the signature
      // stays the same under both Express majors.
      void runStartupCheck(this.config.startupCheck, this.config.name).then(
        (verdict) => {
          res
            .status(startupStatusCodeFor(verdict))
            .json(
              buildStartupBody(this.config.name, verdict, {
                serviceId: this.serviceId,
              }),
            );
        },
      );
    });
  }

  /**
   * Start the Express server and register with mesh.
   */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;

    // Resolve the bind port BEFORE the server and heartbeat start (issue
    // #1194: a conflict falls back to an OS-assigned port with a
    // prominent warning — see resolveStartupBindPort). The heartbeat
    // reads `this.config.httpPort`, so registration carries the ACTUAL
    // port instead of a phantom endpoint.
    {
      const resolvedPort = await resolveStartupBindPort(
        this.config.httpPort,
        "service"
      );
      if (resolvedPort !== this.config.httpPort) {
        this.config = { ...this.config, httpPort: resolvedPort };
      }
    }

    console.log(`Starting MeshExpress service: ${this.serviceId}`);

    // Prepare TLS credentials (fetches from Vault if configured)
    prepareTls(this.serviceId);

    // 0. Initialize distributed tracing
    const tlsConfig = getTlsConfigCached();
    const scheme = tlsConfig.enabled ? "https" : "http";
    const agentMetadata: AgentMetadata = {
      agentId: this.serviceId,
      agentName: this.config.name,
      agentNamespace: this.config.namespace,
      agentHostname: this.config.httpHost,
      agentIp: this.config.httpHost,
      agentPort: this.config.httpPort,
      agentEndpoint: `${scheme}://${this.config.httpHost}:${this.config.httpPort}`,
    };
    await initTracing(agentMetadata);

    // 1. Start HTTP server
    await this.startServer();

    // 2. Start heartbeat to registry via Rust core
    await this.startHeartbeat();

    // 2.5 RFC #1502 step 3: start the health-check refresh. AFTER the
    // heartbeat, deliberately — the gateway registers and becomes visible
    // first, and only the refreshes that follow can withdraw it. Returns
    // immediately; the seed run is scheduled, never awaited.
    this.startHealthRefresh();

    // 3. Install signal handlers for graceful shutdown
    this.installSignalHandlers();
  }

  /**
   * RFC #1502 step 3: run the user's `healthCheck` on a timer and report
   * each verdict to the Rust core, which stops heartbeating while the
   * gateway is `unhealthy` so the registry withdraws it from discovery.
   *
   * This is `MeshAgent.startHealthRefresh` with the same shared loop
   * (`startHealthCheckLoop`), not a second implementation: the seed run is
   * scheduled rather than awaited and does not publish, a throwing check
   * degrades instead of withdrawing, and both the check and the publish are
   * deadline-bounded. Everything that made the provider loop safe applies
   * unchanged here.
   *
   * What a withdrawn gateway keeps: the Express server, its resolved
   * dependencies (#1131), and a 200 on `/ready` — so it stays in its
   * Service endpoints and keeps taking ingress. It stops being discovered,
   * it does not go dark.
   */
  private startHealthRefresh(): void {
    const healthCheck = this.config.healthCheck;
    if (!healthCheck || this.healthLoop) return;

    const ttlSeconds = this.config.healthCheckTtl;
    console.log(
      `Health check runs every ${ttlSeconds}s for service ${this.serviceId}; ` +
        `an unhealthy verdict stops the heartbeat and withdraws this gateway ` +
        `from the registry (the Express server keeps serving)`,
    );

    this.healthLoop = startHealthCheckLoop({
      agentName: this.serviceId,
      healthCheck,
      ttlSeconds,
      publish: async (status) => {
        // The handle is nulled by shutdown(); a verdict landing after
        // teardown has nowhere to go and is not an error, so it stays
        // silent — every clean shutdown would otherwise warn.
        const handle = this.handle;
        if (!handle || this.shutdownRequested) return false;
        const queued = await handle.updateHealth(status);
        if (!queued) {
          // The runtime is up but did not take the verdict. Left silent,
          // an `unhealthy` gateway would keep heartbeating with nothing in
          // the logs to say why it was never withdrawn.
          console.warn(
            `[mesh-health] health status '${status}' for service ` +
              `'${this.serviceId}' was not queued to the mesh runtime — this ` +
              `verdict has not taken effect; the next refresh retries`,
          );
        }
        return queued;
      },
    });
  }

  /**
   * The latest health verdict, or null before the first run completes (or
   * when no `healthCheck` is configured). Read per request by `/health`;
   * null answers 200 there, so a gateway with no check is unaffected.
   */
  getHealthVerdict(): HealthVerdict | null {
    return this.healthLoop?.latest() ?? null;
  }

  /**
   * Start the Express HTTP server.
   *
   * Issue #1163 MED-3: uses `await import("node:https")` — `require()`
   * is not defined in an ESM package ("type": "module"), so the TLS
   * path previously threw a ReferenceError at startup. Mirrors the
   * MCP-agent path in agent.ts.
   */
  private async startServer(): Promise<void> {
    const bindHost = process.env.HOST ?? "0.0.0.0";

    // Use HTTPS when TLS is enabled
    const tlsOpts = getTlsOptions();
    const https = tlsOpts ? await import("node:https") : null;

    return new Promise((resolve, reject) => {
      try {
        if (tlsOpts && https) {
          const serverOpts = {
            ...tlsOpts,
            requestCert: true,
            rejectUnauthorized: true,
          };
          this.server = https.createServer(serverOpts, this.app).listen(
            this.config.httpPort, bindHost, () => {
              console.log(`Service listening on port ${this.config.httpPort} (HTTPS)`);
              resolve();
            }
          );
        } else {
          this.server = this.app.listen(this.config.httpPort, bindHost, () => {
            console.log(`Service listening on port ${this.config.httpPort}`);
            resolve();
          });
        }

        this.server!.on("error", (err) => {
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

    // Issue #933 / #938: flip agent_type to "a2a" when any
    // mesh.a2a.mount(...) surface is registered (spec §2.3 / §8). A2A
    // surfaces and mesh.route() routes coexist on the same agent;
    // agent_type=a2a does NOT mean "no other routes" (matches Python's
    // heartbeat_preparation.py:371-389). Centralized in
    // A2AProducerRegistry.buildAgentSpecContribution so the startup-time
    // value matches the post-mount push path (#938 fix).
    const { agentType, surfacesJson, a2aProducer } =
      A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");

    const spec: JsAgentSpec = {
      // Base name (shared across replicas), unique ID via agentId.
      name: this.config.name,
      agentId: this.serviceId,
      version: this.config.version,
      description: this.config.description,
      registryUrl: this.config.registryUrl,
      httpPort: this.config.httpPort,
      httpHost: this.config.httpHost,
      namespace: this.config.namespace,
      agentType,
      tools,
      heartbeatInterval: this.config.heartbeatInterval,
      surfaces: surfacesJson,
      // Issue #972: producer flag is supplied by the registry contribution
      // helper (true iff at least one mesh.a2a.mount(...) surface). Express
      // path uses `mesh.route(...)` for capability resolution — there's no
      // a2aConfig-style consumer marker in this code path, so the consumer
      // flag stays false in v1. Field names are NAPI-camelCase (a2_ -> a2A).
      a2AProducer: a2aProducer,
      a2AConsumer: false,
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
      // Handle is nulled by shutdown(); exit cleanly instead of
      // spinning on a dead reference.
      if (!this.handle) {
        console.log("Event loop: handle closed, exiting");
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
          console.log("Event loop: shutdown requested, exiting");
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
            `Event loop: terminating after ${consecutiveNextEventFailures} ` +
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
          `Event loop: nextEvent() failed (consecutive=${consecutiveNextEventFailures}), ` +
            `retrying in ${backoffMs}ms:`,
          err
        );
        await new Promise((resolve) => setTimeout(resolve, backoffMs));
        continue;
      }

      try {
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
            // #1131: Log only — RETAIN resolved dependencies on a registry
            // (control-plane) blip. Already-resolved dependency endpoints are
            // data-plane: direct agent→agent connections that stay valid while
            // the registry is unreachable. Clearing them here would permanently
            // sever those connections, since the Rust core never resets topology
            // and its diff gate re-emits only CHANGED deps on reconnect (so the
            // unchanged, still-valid ones would never come back). Matches the
            // cross-runtime reference behavior (MeshAgent, Python, Java).
            console.warn(`Disconnected from registry: ${event.reason}`);
            break;

          case "shutdown":
            console.log("Service shutting down");
            return;

          default:
            break;
        }
      } catch (err) {
        // Per-event isolation: a bad event (or a bug in one handler)
        // must not kill dependency-event processing for the process
        // lifetime. Log and keep consuming events.
        console.error(
          `Event loop: error handling event '${event.eventType}':`,
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

      console.log(
        `\nReceived ${signal}, shutting down service ${this.serviceId}...`
      );

      // Bounded overall shutdown (issue #1163 MED-2 consistency): a
      // hang anywhere in the cleanup sequence (e.g. server.close()
      // waiting on open connections) cannot wedge the process past its
      // SIGTERM grace.
      //
      // Deliberately ref'd (no unref): both completion paths below
      // clearTimeout and process.exit synchronously, so the timer never
      // delays a successful exit — but it must keep a wedged shutdown's
      // otherwise-empty event loop alive long enough to emit the loud
      // exit(1) diagnostic instead of silently exiting 0.
      const forceExitTimer = setTimeout(() => {
        console.error(
          `Shutdown did not complete within ${SIGNAL_SHUTDOWN_TIMEOUT_MS}ms; forcing exit`
        );
        process.exit(1);
      }, SIGNAL_SHUTDOWN_TIMEOUT_MS);

      this.shutdown().then(() => {
        clearTimeout(forceExitTimer);
        console.log(`Service ${this.serviceId} shut down cleanly`);
        process.exit(0);
      }).catch((err) => {
        clearTimeout(forceExitTimer);
        console.error("Error during shutdown:", err);
        process.exit(1);
      });
    };

    // Keep named references so shutdown() can remove exactly these
    // listeners (anonymous arrows can't be process.off'd).
    const sigint = () => shutdownHandler("SIGINT");
    const sigterm = () => shutdownHandler("SIGTERM");
    this.signalHandlers = { sigint, sigterm };
    process.on("SIGINT", sigint);
    process.on("SIGTERM", sigterm);
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
      // Stop the health refresh first (same order as `MeshAgent.shutdown`).
      // Its verdicts are only meaningful while the gateway is serving, and a
      // tick landing mid-teardown would push a status at a handle that is
      // about to close.
      if (this.healthLoop) {
        this.healthLoop.stop();
        this.healthLoop = null;
      }
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
      cleanupTls();
      // Remove this instance's own signal listeners LAST: during the
      // teardown above a signal must still reach the handler (it arms
      // the force-exit timer). Leaving them installed would let a later
      // instance's signal hit this already-resolved shutdown() and
      // process.exit(0) prematurely.
      if (this.signalHandlers) {
        process.off("SIGINT", this.signalHandlers.sigint);
        process.off("SIGTERM", this.signalHandlers.sigterm);
        this.signalHandlers = null;
      }
    })();
    return this.shutdownPromise;
  }
}

/**
 * Create a MeshExpress instance wrapping an Express app.
 *
 * @example
 * ```typescript
 * const app = express();
 * const meshApp = meshExpress(app, { name: "my-api", httpPort: 3000 });
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
