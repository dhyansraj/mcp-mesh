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
 *   httpPort: 9002,
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
 * const meshApp = meshExpress(app, { name: "my-api", httpPort: 3000 });
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
import { llm } from "./llm.js";
import { llmProvider } from "./llm-provider.js";

// Create mesh namespace with route and llm attached
interface MeshNamespace {
  (server: import("fastmcp").FastMCP, config: import("./types.js").AgentConfig): MeshAgent;
  route: typeof route;
  routeWithConfig: typeof routeWithConfig;
  /** Optional: Bind to Express for proper route names in logs. Port auto-detected from PORT env. */
  bind: typeof bindToExpress;
  /** Create an LLM-powered tool with agentic capabilities */
  llm: typeof llm;
  /** Create a zero-code LLM provider tool */
  llmProvider: typeof llmProvider;
}

/**
 * Main mesh function with route and llm helpers attached.
 *
 * - `mesh(server, config)` - Create an MCP agent (wraps fastmcp)
 * - `mesh.route(deps, handler)` - Create Express route with DI
 * - `mesh.bind(app, options)` - Bind to Express, introspect routes
 * - `mesh.llm(config)` - Create LLM-powered tool with agentic loop
 * - `mesh.llmProvider(config)` - Create zero-code LLM provider
 */
const mesh: MeshNamespace = Object.assign(meshFn, {
  route,
  routeWithConfig,
  bind: bindToExpress,
  llm,
  llmProvider,
});

// Main API
export { mesh, MeshAgent };

// Re-export FastMCP for convenience (so users don't need to install it separately)
export { FastMCP } from "fastmcp";

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

// LLM utilities
export {
  llm,
  LlmToolRegistry,
  buildLlmAgentSpecs,
  handleLlmToolsUpdated,
  handleLlmProviderAvailable,
  handleLlmProviderUnavailable,
  getLlmToolMetadata,
  isLlmTool,
  type LlmToolConfig,
  type ResolvedProvider,
  type FastMcpToolDef,
} from "./llm.js";

// LLM Agent
export {
  MeshLlmAgent,
  VercelDirectProvider,
  LiteLLMProvider, // Deprecated: use VercelDirectProvider instead
  MeshDelegatedProvider,
  createLlmToolProxy,
  type MeshLlmAgentConfig,
  type AgentRunContext,
  type LlmProvider,
} from "./llm-agent.js";

// LLM Provider (Phase 4)
export {
  llmProvider,
  loadProvider,
  extractVendorFromModel,
  extractModelName,
  isLlmProviderTool,
  getLlmProviderMeta,
} from "./llm-provider.js";

// Provider Handlers (Phase 4)
export {
  ProviderHandlerRegistry,
  GenericHandler,
  ClaudeHandler,
  OpenAIHandler,
  type ProviderHandler,
  type ProviderHandlerConstructor,
  type VendorCapabilities,
  type ToolSchema,
  type OutputSchema,
  type PreparedRequest,
  type OutputMode,
} from "./provider-handlers/index.js";

// Error classes
export {
  MaxIterationsError,
  ToolExecutionError,
  LLMAPIError,
  ResponseParseError as LlmResponseParseError,
  ProviderUnavailableError,
} from "./errors.js";

// SSE utilities
export { parseSSEResponse, isSSEResponse, parseSSEStream } from "./sse.js";

// Debug utilities
export { debug, createDebug, isAnyDebugEnabled } from "./debug.js";

// Template utilities
export {
  renderTemplate,
  clearTemplateCache,
  registerHelper,
  registerPartial,
  isFileTemplate,
  extractFilePath,
  setTemplateBasePath,
  getTemplateBasePath,
  findAndSetBasePath,
} from "./template.js";

// Response parser
export {
  ResponseParser,
  createResponseParser,
  extractJson,
  zodSchemaToPromptDescription,
  formatZodError,
} from "./response-parser.js";

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
  McpMeshTool,
  McpMeshAgent, // Deprecated, use McpMeshTool
  JsAgentHandle,
  JsMeshEvent,
  JsAgentSpec,
  JsToolSpec,
  JsDependencySpec,
  JsLlmAgentSpec,
  JsLlmToolInfo,
  JsLlmProviderInfo,
  // LLM types
  LlmProviderSpec,
  LlmFilterSpec,
  LlmFilterMode,
  LlmMeta,
  LlmToolCall,
  LlmMessage,
  LlmToolCallRequest,
  LlmToolDefinition,
  LlmCompletionParams,
  LlmCompletionResponse,
  MeshLlmConfig,
  LlmAgent,
  LlmCallOptions,
  LlmToolProxy,
  // New types for feature parity
  LlmMessageInput,
  LlmContextMode,
  LlmOutputMode,
  // LLM Provider types (Phase 4)
  MeshLlmRequest,
  MeshLlmUsage,
  MeshLlmResponse,
  LlmProviderConfig,
} from "./types.js";

// Default export for convenience
export default mesh;
