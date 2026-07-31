/**
 * Express route handler with mesh dependency injection.
 *
 * Provides `mesh.route()` for injecting mesh dependencies into Express routes.
 * Similar to Python's `@mesh.route` decorator for FastAPI.
 *
 * When `mesh.route()` is first called, the API runtime automatically schedules
 * itself to start via `process.nextTick()`. This allows all routes to be
 * registered before connecting to the mesh.
 *
 * @example
 * ```typescript
 * import express from "express";
 * import { mesh } from "@mcpmesh/sdk";
 *
 * const app = express();
 * app.use(express.json());
 *
 * // mesh.route() triggers auto-init - no meshExpress() or start() needed!
 * // Dependencies bind BY POSITION: the Nth declared dependency is deps[N].
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, [calculator]) => {
 *     const result = await calculator({ a: req.body.a, b: req.body.b });
 *     res.json({ result });
 *   }
 * ));
 *
 * app.listen(3000);
 * ```
 */

import type { Request, Response, NextFunction, RequestHandler } from "express";
import type { DependencySpec, McpMeshTool, DependencyKwargs, TagSpec } from "./types.js";
import { normalizeDependency, runWithPropagatedHeaders, runWithTraceContext } from "./proxy.js";
import { resolvePositionalDeps, type PositionalDependencies } from "./positional-deps.js";
import { assertNoServiceViewDeps } from "./service-view.js";
import { getApiRuntime, introspectExpressRoutes } from "./api-runtime.js";
import { getSettleState, type PendingSettleDep } from "./settle.js";
import {
  PROPAGATE_HEADERS,
  matchesPropagateHeader,
  parseTraceContext,
  generateSpanId,
  generateTraceId,
  publishTraceSpan,
} from "./tracing.js";

/**
 * Global flag to track if Express auto-detection has been performed.
 * We only need to do this once on first request.
 */
let expressAutoDetected = false;

/**
 * Dependencies passed to route handlers — **positional** as of 3.4.0
 * (issue #1401). `deps[i]` is the proxy for the i-th declared dependency, or
 * `null` when it is not currently resolved. Slots are never compacted, so an
 * unavailable dependency nulls its own index and never shifts a later one.
 *
 * Before 3.4.0 this was a capability-keyed object. Destructure positionally:
 *
 * ```typescript
 * mesh.route([{ capability: "a" }, { capability: "b" }],
 *   async (req, res, [a, b]) => { ... })
 * ```
 *
 * A handler may narrow this to a tuple for per-slot typing, e.g.
 * `MeshRouteHandler<[McpMeshTool, McpMeshTool | null]>`.
 */
export type RouteDependencies = PositionalDependencies;

/**
 * Route handler function with dependency injection.
 *
 * @param req - Express request object
 * @param res - Express response object
 * @param deps - Resolved dependencies **by position** — `deps[i]` is the i-th
 *               declared dependency (see {@link RouteDependencies})
 */
export type MeshRouteHandler<D extends RouteDependencies = RouteDependencies> = (
  req: Request,
  res: Response,
  deps: D
) => void | Promise<void>;

/**
 * Extended route handler with next function for middleware chaining.
 *
 * This is also the type {@link route} accepts — deliberately NOT a union with
 * {@link MeshRouteHandler}. A 3-parameter handler is assignable here (fewer
 * parameters always are), whereas a *union* of the two signatures defeats
 * contextual typing for the `deps` array binding pattern: TypeScript cannot
 * pick a contextual signature out of the union, falls back to the pattern's
 * implied tuple (`[add]` → `[any]`), and then rejects the assignment because
 * an array "may have fewer elements". The keyed object form masked this — its
 * implied type `{ add: any }` happened to be satisfied by
 * `Record<string, McpMeshTool | null>` — so it only surfaced under #1401.
 */
export type MeshRouteHandlerWithNext<
  D extends RouteDependencies = RouteDependencies,
> = (
  req: Request,
  res: Response,
  deps: D,
  next: NextFunction
) => void | Promise<void>;

/**
 * Configuration for a mesh route.
 */
export interface MeshRouteConfig {
  /** Dependencies to inject */
  dependencies: DependencySpec[];
  /** Per-dependency configuration (indexed by position) */
  dependencyKwargs?: DependencyKwargs[];
}

/**
 * Internal route metadata stored in RouteRegistry.
 */
export interface RouteMetadata {
  /** Route identifier (METHOD:path) */
  routeId: string;
  /** HTTP method */
  method: string;
  /** Route path pattern */
  path: string;
  /** Normalized dependencies (tags may include OR alternatives) */
  dependencies: Array<{
    capability: string;
    tags: TagSpec[];
    version?: string;
    /** Issue #547: raw expected output schema (post-zodToJsonSchema). */
    expectedSchemaRaw?: object;
    /** Issue #547: schema match mode. */
    matchMode?: "subset" | "strict";
    /** Issue #1249: opt-in required edge (default false). A required route dep
     * whose proxy is unavailable at call time trips the perimeter 503. */
    required?: boolean;
  }>;
  /** Per-dependency kwargs */
  dependencyKwargs?: DependencyKwargs[];
}

/**
 * Global registry for mesh routes.
 * Tracks all routes created with mesh.route() for dependency resolution.
 */
export class RouteRegistry {
  private static instance: RouteRegistry | null = null;
  private routes: Map<string, RouteMetadata> = new Map();
  private resolvedDeps: Map<string, McpMeshTool> = new Map();
  private routeIdMapping: Map<string, string> = new Map(); // old ID → new ID
  private routeCounter = 0;

  private constructor() {}

  static getInstance(): RouteRegistry {
    if (!RouteRegistry.instance) {
      RouteRegistry.instance = new RouteRegistry();
    }
    return RouteRegistry.instance;
  }

  /**
   * Reset the registry (mainly for testing).
   */
  static reset(): void {
    RouteRegistry.instance = null;
  }

  /**
   * Register a route with its dependencies.
   * Returns a unique route ID for dependency resolution.
   */
  registerRoute(
    method: string,
    path: string,
    dependencies: DependencySpec[],
    dependencyKwargs?: DependencyKwargs[]
  ): string {
    // Generate unique route ID
    const routeId = `route_${this.routeCounter++}_${method}:${path}`;

    const normalizedDeps = dependencies.map(normalizeDependency);

    this.routes.set(routeId, {
      routeId,
      method,
      path,
      dependencies: normalizedDeps,
      dependencyKwargs,
    });

    // Settling-window grace (#1193): declare this route's deps with the
    // process-wide settle state so the agent-level "all declared deps
    // resolved" latch can flip eagerly. Keys are renamed alongside the
    // route ID in updateRouteInfo().
    const settleState = getSettleState();
    normalizedDeps.forEach((_dep, depIndex) => {
      settleState.registerDeclared(`${routeId}:dep_${depIndex}`);
    });

    return routeId;
  }

  /**
   * Get all registered routes.
   */
  getRoutes(): RouteMetadata[] {
    return Array.from(this.routes.values());
  }

  /**
   * Get a route by ID.
   * Handles lookup with old route IDs that have been remapped after introspection.
   */
  getRoute(routeId: string): RouteMetadata | undefined {
    // Check if this is an old ID that's been remapped
    const actualId = this.routeIdMapping.get(routeId) || routeId;
    return this.routes.get(actualId);
  }

  /**
   * Resolve a route ID to its current ID (after any remapping).
   */
  resolveRouteId(routeId: string): string {
    return this.routeIdMapping.get(routeId) || routeId;
  }

  /**
   * Update resolved dependency for a route.
   * Handles old route IDs that have been remapped after introspection.
   */
  setDependency(routeId: string, depIndex: number, proxy: McpMeshTool): void {
    // Resolve to current route ID in case this is an old ID from Rust core
    const actualId = this.routeIdMapping.get(routeId) || routeId;
    const depKey = `${actualId}:dep_${depIndex}`;
    this.resolvedDeps.set(depKey, proxy);
    // Settling-window grace (#1193): wake any settling request waiting on
    // this dependency AFTER the proxy is stored so the woken request
    // re-reads a real proxy. This is the single funnel for route deps —
    // both the express runtime and the API runtime land here.
    getSettleState().markResolved(depKey);
  }

  /**
   * Remove resolved dependency for a route.
   * Handles old route IDs that have been remapped after introspection.
   */
  removeDependency(routeId: string, depIndex: number): void {
    // Resolve to current route ID in case this is an old ID from Rust core
    const actualId = this.routeIdMapping.get(routeId) || routeId;
    const depKey = `${actualId}:dep_${depIndex}`;
    this.resolvedDeps.delete(depKey);
  }

  /**
   * Get resolved dependency for a route.
   * Handles old route IDs that have been remapped after introspection.
   */
  getDependency(routeId: string, depIndex: number): McpMeshTool | null {
    // Resolve to current route ID in case this is an old ID from Rust core
    const actualId = this.routeIdMapping.get(routeId) || routeId;
    const depKey = `${actualId}:dep_${depIndex}`;
    return this.resolvedDeps.get(depKey) ?? null;
  }

  /**
   * Get all resolved dependencies for a route as a **positional array**
   * (issue #1401) — index i holds the i-th declared dependency's proxy, or
   * `null` when it is unresolved.
   *
   * Handles remapped route IDs (e.g., route_0_UNKNOWN:UNKNOWN -> GET:/time).
   *
   * Built with an index-preserving `map()` over the DECLARED dependencies —
   * never by pushing resolved entries. A push-based build would omit
   * unresolved slots and shift every later dependency into the wrong
   * position; harmless for the old capability-keyed object, fatal for an
   * array. Returns a plain array; the migration guard is applied at the
   * user-code boundary (see `wrapPositionalDeps`).
   */
  getDependenciesForRoute(routeId: string): RouteDependencies {
    // Use getRoute to handle remapped IDs
    const route = this.getRoute(routeId);
    if (!route) return [];

    // Use the resolved route ID for dependency lookup
    const resolvedId = route.routeId;
    return route.dependencies.map((_dep, idx) =>
      this.getDependency(resolvedId, idx)
    );
  }

  /**
   * Clear all resolved dependencies (e.g., on registry disconnect).
   */
  clearAllDependencies(): void {
    this.resolvedDeps.clear();
  }

  /**
   * Update route metadata with proper method and path.
   * Called after Express route introspection.
   */
  updateRouteInfo(routeId: string, method: string, path: string): void {
    const route = this.routes.get(routeId);
    if (route) {
      // Create new route ID with proper method:path
      const newRouteId = `${method}:${path}`;

      // Store mapping for old→new ID (for dependency events from Rust core)
      this.routeIdMapping.set(routeId, newRouteId);

      // Update the route metadata
      route.method = method;
      route.path = path;
      route.routeId = newRouteId;

      // Re-register with new ID
      this.routes.delete(routeId);
      this.routes.set(newRouteId, route);

      // Migrate any resolved dependencies to new key
      for (let i = 0; i < route.dependencies.length; i++) {
        const oldKey = `${routeId}:dep_${i}`;
        const newKey = `${newRouteId}:dep_${i}`;
        const dep = this.resolvedDeps.get(oldKey);
        if (dep) {
          this.resolvedDeps.set(newKey, dep);
          this.resolvedDeps.delete(oldKey);
        }
        // Settling-window grace (#1193): keep the settle state's declared/
        // resolved/waiter keys aligned with the remapped route ID.
        getSettleState().renameDeclared(oldKey, newKey);
      }
    }
  }

}

/**
 * Perform auto-detection of Express app, port, and routes on first request.
 * This eliminates the need for mesh.bind() - everything is detected automatically.
 *
 * @param req - Express request object (provides access to app and socket)
 */
function performExpressAutoDetection(req: Request): void {
  try {
    // Extract port from the socket
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const socket = (req as any).socket || (req as any).connection;
    const port = socket?.localPort || 0;

    // Get Express app from request
    const app = req.app;

    if (app) {
      // Introspect routes to get proper METHOD:path names
      const routeCount = introspectExpressRoutes(app);

      // Update runtime with detected info
      getApiRuntime().updateExpressInfo(port, routeCount);
    }
  } catch (err) {
    // Don't fail the request if auto-detection fails
    console.warn("Express auto-detection failed:", err);
  }
}

/**
 * Reset auto-detection flag (for testing).
 */
export function resetAutoDetection(): void {
  expressAutoDetected = false;
}

/**
 * Create an Express middleware that injects mesh dependencies.
 *
 * @param dependencies - Array of dependency specifications
 * @param handler - Route handler receiving (req, res, deps) where `deps` is
 *                  **positional**: `deps[i]` is the i-th declared dependency
 * @returns Express middleware
 *
 * @example
 * ```typescript
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, [calculator]) => {
 *     if (!calculator) {
 *       res.status(503).json({ error: "Calculator service unavailable" });
 *       return;
 *     }
 *     const result = await calculator({ a: req.body.a, b: req.body.b });
 *     res.json({ result });
 *   }
 * ));
 * ```
 */
export function route<D extends RouteDependencies = RouteDependencies>(
  dependencies: DependencySpec[],
  handler: MeshRouteHandlerWithNext<D>,
  options?: { dependencyKwargs?: DependencyKwargs[] }
): RequestHandler {
  const registry = RouteRegistry.getInstance();

  // RFC #1280: service views are a tool-parameter surface only. A view in
  // mesh.route deps is out of scope — reject rather than shipping a malformed
  // `capability: undefined` edge.
  assertNoServiceViewDeps(dependencies, "mesh.route");

  // We don't know the method/path yet since this is called before app.get/post/etc
  // So we'll register with placeholder and update when the middleware is called
  // Use a ref object so introspection can update it and the middleware sees the change
  const routeRef = {
    id: registry.registerRoute(
      "UNKNOWN", // Will be determined at runtime from req.method
      "UNKNOWN", // Will be determined at runtime from req.path
      dependencies,
      options?.dependencyKwargs
    ),
  };

  // Trigger auto-init of API runtime on first route() call
  // Uses process.nextTick() to wait until all routes are registered
  if (dependencies.length > 0) {
    getApiRuntime().scheduleStart();
  }

  // Store normalized deps for the handler
  const normalizedDeps = dependencies.map(normalizeDependency);

  // Issue #1249: does this route declare any required dep? Precomputed once so
  // the perimeter check below is a no-op for the common (all-optional) route.
  // Every declared dep always has its own index in the positional `deps`
  // array, so — unlike Python's positional injection, where a dep can be
  // declared without a matching parameter — there is no "required perimeter
  // INACTIVE (no injectable slot)" case to warn about.
  // TS `mesh.route` has no declared streaming/SSE variant either, and the 503
  // is emitted before the handler runs (nothing written to `res` yet), so
  // there is no stream to break and no creation-time bypass warning to emit.
  const hasRequiredDep = normalizedDeps.some((dep) => dep.required === true);

  // Capability names in declaration order — the migration guard prints these
  // when an un-migrated handler reads `deps.<capability>` (issue #1401).
  const declaredCapabilities = normalizedDeps.map((dep) => dep.capability);

  // Return Express middleware
  const middleware: RequestHandler = async (
    req: Request,
    res: Response,
    next: NextFunction
  ): Promise<void> => {
    try {
      // Auto-detect Express app, port, and routes on first request
      // This eliminates the need for mesh.bind()
      if (!expressAutoDetected) {
        expressAutoDetected = true;
        performExpressAutoDetection(req);
      }

      // Settling-window grace (#1193): while the agent is still settling,
      // wait — bounded by the remaining settle budget — for any declared
      // dep this request would inject that is still unresolved. No-op
      // (single latch check) once settled; deps are read AFTER the wait so
      // they reflect the resolution state.
      const settleState = getSettleState();
      if (normalizedDeps.length > 0 && !settleState.isSettled()) {
        const currentId = registry.resolveRouteId(routeRef.id);
        const pendingSettle: PendingSettleDep[] = [];
        normalizedDeps.forEach((dep, depIndex) => {
          if (registry.getDependency(currentId, depIndex) === null) {
            pendingSettle.push({
              depKey: `${currentId}:dep_${depIndex}`,
              capability: dep.capability,
            });
          }
        });
        if (pendingSettle.length > 0) {
          await settleState.awaitPending(pendingSettle);
        }
      }

      // Resolve, pad and guard the positional dependency array (issue #1401).
      // Shared with the A2A producer dispatcher so the two injection sites
      // cannot drift. `depValues` is the unguarded view the required-dependency
      // perimeter below reads by index; `deps` is what user code receives —
      // an un-migrated `deps.<capability>` access throws a prescriptive error
      // instead of evaluating to `undefined`. Uses the ref to get the current
      // route ID after introspection.
      const { values: depValues, deps } = resolvePositionalDeps(
        registry,
        routeRef.id,
        declaredCapabilities,
        "mesh.route"
      );

      // Issue #1249 perimeter: a route dep declared `required: true` whose
      // proxy is unavailable AT CALL TIME (after the settle wait above) makes
      // the capability unavailable — return 503 before user code, naming the
      // capability, so monitoring alarms on 5xx and clients see a retryable
      // "unavailable" rather than a hand-written null check.
      //
      // Evaluate required-ness PER INDEX against the same positional array the
      // handler receives (issue #1401). Injection used to be capability-keyed,
      // which collapsed a capability declared twice into ONE `deps[cap]` slot —
      // so the check had to dedupe per capability to avoid 503-ing on a dead
      // sibling while the slot the handler read was live. Under positional
      // injection each declaration owns its own index: two slots declaring the
      // same capability are two distinct slots, either of which can be null in
      // the handler. Deduping now would let a required slot the handler will
      // read as `null` slip past the perimeter.
      if (hasRequiredDep) {
        for (let i = 0; i < normalizedDeps.length; i++) {
          const dep = normalizedDeps[i];
          if (dep.required !== true) continue;
          // `== null` catches both the resolved-null and never-set cases.
          if (depValues[i] == null) {
            console.warn(
              `🚫 Route '${req.method} ${req.path}': required dependency ` +
                `[${i}] '${dep.capability}' unavailable — returning 503`
            );
            res.status(503).json({
              error: "dependency_unavailable",
              capability: dep.capability,
            });
            return;
          }
        }
      }

      // Extract propagated headers from incoming HTTP request
      const propagatedHeaders: Record<string, string> = {};
      if (PROPAGATE_HEADERS.length > 0) {
        for (const [headerName, value] of Object.entries(req.headers)) {
          if (typeof value === "string" && matchesPropagateHeader(headerName)) {
            propagatedHeaders[headerName.toLowerCase()] = value;
          }
        }
      }

      // Parse trace context from incoming request headers
      const reqHeaders: Record<string, string | undefined> = {};
      if (req.headers) {
        for (const [key, value] of Object.entries(req.headers)) {
          if (typeof value === "string") {
            reqHeaders[key.toLowerCase()] = value;
          }
        }
      }
      const incomingTrace = parseTraceContext(reqHeaders);

      // Set up trace context: use incoming or generate new
      const traceId = incomingTrace?.traceId ?? generateTraceId();
      const spanId = generateSpanId();
      const parentSpanId = incomingTrace?.parentSpanId ?? null;

      // Route name for span (matches Python convention: "METHOD /path")
      const routeName = `${req.method} ${req.path}`;
      const startTime = Date.now() / 1000;
      let success = true;
      let error: string | null = null;

      try {
        // Call handler with trace context + propagated headers
        // runWithTraceContext populates AsyncLocalStorage so downstream proxy calls
        // get _trace_id/_parent_span injected automatically
        const traceContext = { traceId, parentSpanId: spanId };
        const runHandler = async () => {
          if (handler.length === 4) {
            await (handler as MeshRouteHandlerWithNext)(req, res, deps, next);
          } else {
            await (handler as MeshRouteHandler)(req, res, deps);
          }
        };

        const runWithHeaders = async () => {
          if (Object.keys(propagatedHeaders).length > 0) {
            await runWithPropagatedHeaders(propagatedHeaders, runHandler);
          } else {
            await runHandler();
          }
        };

        await runWithTraceContext(traceContext, runWithHeaders);
      } catch (err) {
        success = false;
        error = err instanceof Error ? err.message : String(err);
        throw err;
      } finally {
        // Publish route handler span (fire and forget)
        // publishTraceSpan gates on tracingEnabled internally
        const endTime = Date.now() / 1000;
        const durationMs = (endTime - startTime) * 1000;

        publishTraceSpan({
          traceId,
          spanId,
          parentSpan: parentSpanId,
          functionName: routeName,
          startTime,
          endTime,
          durationMs,
          success,
          error,
          resultType: "route_handler",
          argsCount: 0,
          kwargsCount: 0,
          dependencies: [],
          injectedDependencies: depValues.filter((d) => d !== null).length,
          meshPositions: [],
        }).catch(() => {
          // Silently ignore publish errors
        });
      }
    } catch (error) {
      next(error);
    }
  };

  // Attach metadata for introspection
  // Use routeRef so introspection can update the ID and middleware sees the change
  (middleware as RequestHandler & { _meshRouteId: string })._meshRouteId = routeRef.id;
  (middleware as RequestHandler & { _meshRouteRef: typeof routeRef })._meshRouteRef = routeRef;
  (middleware as RequestHandler & { _meshDependencies: typeof normalizedDeps })._meshDependencies = normalizedDeps;

  return middleware;
}

/**
 * Alternative API: route with config object.
 *
 * @example
 * ```typescript
 * app.post("/compute", mesh.routeWithConfig({
 *   dependencies: [{ capability: "calculator" }],
 *   dependencyKwargs: [{ timeout: 60 }],
 * }, async (req, res, [calculator]) => {
 *   // ...
 * }));
 * ```
 */
export function routeWithConfig<D extends RouteDependencies = RouteDependencies>(
  config: MeshRouteConfig,
  handler: MeshRouteHandlerWithNext<D>
): RequestHandler {
  return route<D>(config.dependencies, handler, {
    dependencyKwargs: config.dependencyKwargs,
  });
}
