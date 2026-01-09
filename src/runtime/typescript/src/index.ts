/**
 * @mcpmesh/sdk - MCP Mesh SDK for TypeScript
 *
 * Build distributed MCP agents with automatic service discovery and dependency injection.
 *
 * @example
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
 */

// Main API
export { mesh, MeshAgent } from "./agent.js";

// Types
export type {
  AgentConfig,
  ResolvedAgentConfig,
  MeshToolDef,
  ToolMeta,
  JsAgentHandle,
  JsMeshEvent,
  JsAgentSpec,
  JsToolSpec,
} from "./types.js";

// Default export for convenience
export { mesh as default } from "./agent.js";
