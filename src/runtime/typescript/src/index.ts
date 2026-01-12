/**
 * @mcpmesh/sdk - MCP Mesh SDK for TypeScript
 *
 * Build distributed MCP agents with automatic service discovery and dependency injection.
 *
 * @example MCP Agent (fastmcp)
 * ```typescript
 * import { FastMCP } from "fastmcp";
 * import { mesh } from "@mcpmesh/sdk";
 * import { z } from "zod";
 *
 * const server = new FastMCP({ name: "Calculator", version: "1.0.0" });
 *
 * const agent = mesh(server, {
 *   name: "calculator",
 *   port: 9002,
 * });
 *
 * agent.addTool({
 *   name: "add",
 *   capability: "add",
 *   tags: ["tools", "math"],
 *   description: "Add two numbers together",
 *   parameters: z.object({ a: z.number(), b: z.number() }),
 *   execute: async ({ a, b }) => String(a + b),
 * });
 *
 * // No server.start() or main function needed!
 * ```
 *
 * @example Express API with mesh dependencies
 * ```typescript
 * import express from "express";
 * import { mesh, meshExpress } from "@mcpmesh/sdk";
 *
 * const app = express();
 * app.use(express.json());
 *
 * const meshApp = meshExpress(app, { name: "my-api", port: 3000 });
 *
 * app.post("/compute", mesh.route(
 *   [{ capability: "calculator" }],
 *   async (req, res, { calculator }) => {
 *     const result = await calculator({ a: req.body.a, b: req.body.b });
 *     res.json({ result });
 *   }
 * ));
 *
 * meshApp.start();
 * ```
 */

import { mesh as meshFn, MeshAgent } from "./agent.js";
import { route, routeWithConfig } from "./route.js";
import { bindToExpress } from "./api-runtime.js";

// Create mesh namespace with route attached
interface MeshNamespace {
  (server: import("fastmcp").FastMCP, config: import("./types.js").AgentConfig): MeshAgent;
  route: typeof route;
  routeWithConfig: typeof routeWithConfig;
  /** Optional: Bind to Express for proper route names in logs. Port auto-detected from PORT env. */
  bind: typeof bindToExpress;
}

/**
 * Main mesh function with route helpers attached.
 *
 * - `mesh(server, config)` - Create an MCP agent (wraps fastmcp)
 * - `mesh.route(deps, handler)` - Create Express route with DI
 * - `mesh.bind(app, options)` - Bind to Express, introspect routes
 */
const mesh: MeshNamespace = Object.assign(meshFn, {
  route,
  routeWithConfig,
  bind: bindToExpress,
});

// Main API
export { mesh, MeshAgent };

// Express integration
export { meshExpress, MeshExpress, type MeshExpressConfig } from "./express.js";

// API runtime (auto-init for Express routes)
export {
  getApiRuntime,
  ApiRuntime,
  bindToExpress,
  introspectExpressRoutes,
  type ApiRuntimeConfig,
} from "./api-runtime.js";

// Route utilities
export {
  route,
  routeWithConfig,
  RouteRegistry,
  type MeshRouteHandler,
  type MeshRouteHandlerWithNext,
  type RouteDependencies,
  type MeshRouteConfig,
  type RouteMetadata,
} from "./route.js";

// Proxy utilities (for advanced use)
export { createProxy, normalizeDependency } from "./proxy.js";

// Tracing utilities (for advanced use)
export {
  initTracing,
  isTracingAvailable,
  generateTraceId,
  generateSpanId,
  parseTraceContext,
  createTraceHeaders,
  publishTraceSpan,
  type TraceContext,
  type AgentMetadata,
  type SpanData,
} from "./tracing.js";

// Types
export type {
  AgentConfig,
  ResolvedAgentConfig,
  MeshToolDef,
  ToolMeta,
  DependencySpec,
  NormalizedDependency,
  ResolvedDependency,
  DependencyKwargs,
  McpMeshAgent,
  JsAgentHandle,
  JsMeshEvent,
  JsAgentSpec,
  JsToolSpec,
  JsDependencySpec,
} from "./types.js";

// Default export for convenience
export default mesh;
