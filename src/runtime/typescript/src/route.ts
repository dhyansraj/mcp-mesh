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
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, { calculator }) => {
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
import { getApiRuntime, introspectExpressRoutes } from "./api-runtime.js";
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
 * Dependencies object passed to route handlers.
 * Keys are capability names, values are proxy instances (or null if unavailable).
 */
export type RouteDependencies = Record<string, McpMeshTool | null>;

/**
 * Route handler function with dependency injection.
 *
 * @param req - Express request object
 * @param res - Express response object
 * @param deps - Resolved dependencies as an object (keys are capability names)
 */
export type MeshRouteHandler = (
  req: Request,
  res: Response,
  deps: RouteDependencies
) => void | Promise<void>;

/**
 * Extended route handler with next function for middleware chaining.
 */
export type MeshRouteHandlerWithNext = (
  req: Request,
  res: Response,
  deps: RouteDependencies,
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
   * Get all resolved dependencies for a route as an object.
   * Keys are capability names for easy destructuring in handlers.
   * Handles remapped route IDs (e.g., route_0_UNKNOWN:UNKNOWN -> GET:/time).
   */
  getDependenciesForRoute(routeId: string): RouteDependencies {
    // Use getRoute to handle remapped IDs
    const route = this.getRoute(routeId);
    if (!route) return {};

    // Use the resolved route ID for dependency lookup
    const resolvedId = route.routeId;
    const deps: RouteDependencies = {};
    route.dependencies.forEach((dep, idx) => {
      deps[dep.capability] = this.getDependency(resolvedId, idx);
    });

    return deps;
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
 * @param handler - Route handler receiving (req, res, deps)
 * @returns Express middleware
 *
 * @example
 * ```typescript
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, { calculator }) => {
 *     if (!calculator) {
 *       return res.status(503).json({ error: "Calculator service unavailable" });
 *     }
 *     const result = await calculator({ a: req.body.a, b: req.body.b });
 *     res.json({ result });
 *   }
 * ));
 * ```
 */
export function route(
  dependencies: DependencySpec[],
  handler: MeshRouteHandler | MeshRouteHandlerWithNext,
  options?: { dependencyKwargs?: DependencyKwargs[] }
): RequestHandler {
  const registry = RouteRegistry.getInstance();

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

      // Get resolved dependencies as object (use ref to get current ID after introspection)
      const deps = registry.getDependenciesForRoute(routeRef.id);

      // Also try to resolve by capability name if route-specific resolution isn't available yet
      // This handles the case where dependencies were resolved before the route was registered
      for (const dep of normalizedDeps) {
        if (deps[dep.capability] === undefined) {
          deps[dep.capability] = null;
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
          injectedDependencies: Object.values(deps).filter((d) => d !== null).length,
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
 * }, async (req, res, { calculator }) => {
 *   // ...
 * }));
 * ```
 */
export function routeWithConfig(
  config: MeshRouteConfig,
  handler: MeshRouteHandler | MeshRouteHandlerWithNext
): RequestHandler {
  return route(config.dependencies, handler, {
    dependencyKwargs: config.dependencyKwargs,
  });
}
