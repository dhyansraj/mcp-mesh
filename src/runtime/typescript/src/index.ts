/**
 * @mcpmesh/sdk - MCP Mesh SDK for TypeScript
 *
 * Build distributed MCP agents with automatic service discovery and dependency injection.
 *
 * @example MCP Agent (fastmcp)
 * ```typescript
 * import { FastMCP, mesh } from "@mcpmesh/sdk";
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
import { serviceView } from "./service-view.js";
import { bindToExpress } from "./api-runtime.js";
import { llm } from "./llm.js";
import { llmProvider } from "./llm-provider.js";
import { sseStream } from "./sse-stream.js";
import { mount as a2aMount } from "./a2a/producer/index.js";
import {
  cancel as jobsCancel,
  postEvent as jobsPostEvent,
  status as jobsStatus,
  subscribeEvents as jobsSubscribeEvents,
  wait as jobsWait,
} from "./jobs.js";

/**
 * `mesh.a2a` namespace — A2A v1.0 producer surface (issue #933).
 *
 * Sibling to `mesh.route(...)` for "user-owned Express app, DDDI of mesh
 * tools" — but tailored to the A2A protocol's two-routes-per-skill shape
 * (dispatch + agent card). One call to `mesh.a2a.mount(app, config,
 * handler)` wires both routes plus the heartbeat surface emission.
 */
interface MeshA2ANamespace {
  /**
   * Mount an A2A v1.0 producer surface. Wires the JSON-RPC dispatch route
   * and the agent-card discovery route on the provided Express app.
   */
  mount: typeof a2aMount;
}

const a2a: MeshA2ANamespace = { mount: a2aMount };

/**
 * `mesh.jobs` namespace — MeshJob event-injection convenience helpers
 * (mirrors Python's `mesh.jobs` submodule shipped via PR #1041 for
 * issue #1032). The `postEvent` helper lets MCP tool bodies push an
 * event into a running job by id without holding a `JobProxy` reference
 * in scope (the SDK resolves the registry URL from
 * `MCP_MESH_REGISTRY_URL` and reuses a process-cached `JobProxy`).
 */
interface MeshJobsNamespace {
  cancel: typeof jobsCancel;
  postEvent: typeof jobsPostEvent;
  status: typeof jobsStatus;
  subscribeEvents: typeof jobsSubscribeEvents;
  wait: typeof jobsWait;
}

const jobs: MeshJobsNamespace = {
  cancel: jobsCancel,
  postEvent: jobsPostEvent,
  status: jobsStatus,
  subscribeEvents: jobsSubscribeEvents,
  wait: jobsWait,
};

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
  /** Create a consumer service view (RFC #1280) for a tool dependency slot */
  serviceView: typeof serviceView;
  /** Pipe an AsyncIterable<string> to an Express response as text/event-stream */
  sseStream: typeof sseStream;
  /** A2A v1.0 producer surface (issue #933). */
  a2a: MeshA2ANamespace;
  /** MeshJob event-injection helpers (mirrors Python `mesh.jobs`). */
  jobs: MeshJobsNamespace;
}

/**
 * Main mesh function with route and llm helpers attached.
 *
 * - `mesh(server, config)` - Create an MCP agent (wraps fastmcp)
 * - `mesh.route(deps, handler)` - Create Express route with DI
 * - `mesh.bind(app, options)` - Bind to Express, introspect routes
 * - `mesh.llm(config)` - Create LLM-powered tool with agentic loop
 * - `mesh.llmProvider(config)` - Create zero-code LLM provider
 * - `mesh.sseStream(res, asyncIterable)` - Forward async iterable as SSE
 */
const mesh: MeshNamespace = Object.assign(meshFn, {
  route,
  routeWithConfig,
  bind: bindToExpress,
  llm,
  llmProvider,
  serviceView,
  sseStream,
  a2a,
  jobs,
});

// Main API
export { mesh, MeshAgent };

// Worker-mode user contract: check globalThis[IN_WORKER_SYMBOL] to detect
// whether your module is being loaded inside a tool-isolation worker. Use
// this to guard module-top-level side effects (custom servers, OTel init).
export { IN_WORKER_SYMBOL } from "./agent.js";

// Internal: worker entry uses this to look up user-registered tools.
// Not part of the public API; do not depend on it from user code.
export { __getWorkerToolMap } from "./agent.js";

// Internal: worker entry needs these to restore ALS scopes around user
// tool calls so trace context + propagated headers work inside workers.
// Not part of the public API.
export { runWithTraceContext, runWithPropagatedHeaders } from "./proxy.js";

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

// Service views (RFC #1280) — consumer view factory + producer sugar surface.
export {
  serviceView,
  isServiceView,
  MeshServiceUnavailableError,
  SERVICE_VIEW_BRAND,
  CAPABILITY_NAME_PATTERN,
  type ServiceView,
  type ServiceViewSpec,
  type ServiceViewMethodSpec,
  type MeshServiceFacade,
  type MeshServiceFacadeMethod,
  type ServiceProducerMethod,
  type ServiceProducerMethodObject,
} from "./service-view.js";

// Proxy utilities (for advanced use)
export { createProxy, normalizeDependency, getCurrentPropagatedHeaders, callingJob, type CallingJob, extractContent, streamMcpTool, type MultiContentResult } from "./proxy.js";

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

// Media utilities (multimodal content)
export {
  uploadMedia,
  downloadMedia,
  mediaResult,
  MediaResult,
  createMediaResult,
  saveUpload,
  saveUploadResult,
  getMediaStore,
  guessMimeType,
  formatForOpenai,
  resolveMediaInputs,
  LocalMediaStore,
  S3MediaStore,
  resolveResourceLinks,
  hasResourceLink,
  type MediaStore,
  type MediaUploadResult,
  type ResolvedContent,
} from "./media/index.js";

// Media parameter helper (schema annotation for media-typed params)
export { mediaParam } from "./types.js";
export { enrichSchemaWithMediaTypes } from "./media-param.js";

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
export { sseStream } from "./sse-stream.js";

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

// MeshJob substrate (Phase 1) — see MESHJOB_DDDI_CONTRACT.md.
// Re-export the MeshJob type marker, AsyncLocalStorage mirror, and the
// DDDI resolver so consumers can use either the SDK entry points or
// drop down to the underlying primitives in tests / advanced wiring.
export type { MeshJob } from "./types.js";
export {
  CURRENT_JOB,
  currentJob,
  remainingSeconds,
  withJobAsync,
  type JobContextSnapshot,
} from "./job-context.js";
export {
  resolveMeshJobSignature,
  ResolverError,
  type ResolvedSignature,
  type ResolvedMeshToolDep,
  type ResolverInput,
} from "./resolver-meshjob.js";
export {
  MeshJobSubmitter,
  type SubmitOptions,
} from "./mesh-job-submitter.js";
export {
  readJobHeaders,
  runWithJobContext,
  makeJobController,
} from "./inbound-job-dispatch.js";
export {
  ClaimDispatcher,
  stopDispatchers,
  type ClaimHandler,
} from "./claim-dispatcher.js";
export { registerJobHelperTools } from "./jobs-helper-tools.js";
export { registerCancelRoute } from "./jobs-cancel-route.js";
// MeshJob event-injection helpers + typed errors (mirrors Python
// `mesh.jobs` shipped via PR #1041 for issue #1032). The
// `mesh.jobs.postEvent` helper is the primary surface; the error
// classes are exported so consumers can `instanceof`-discriminate
// against the napi binding's generic Error.
export {
  cancel,
  postEvent,
  status,
  subscribeEvents,
  wait,
  JobNotFoundError,
  JobTerminalError,
  type JobEvent,
  type JobEventReceipt,
  type JobStatus,
  type SubscribeEventsOptions,
} from "./jobs.js";
// Re-export napi-rs job primitives for users who want to drop down
// to the underlying handles directly (e.g. constructing a JobProxy
// from a known job_id).
export { JobController, JobProxy } from "@mcpmesh/core";

// A2A consumer surface (issue #917) — sync send / non-blocking submit /
// SSE subscribe + bridge. The framework constructs A2AClient instances
// from `addTool({ a2aConfig: {...} })` and injects them into execute;
// users only reach for these classes directly in advanced scenarios.
export {
  A2AClient,
  A2AJob,
  A2AStream,
  A2ABearer,
  A2AError,
  A2ATimeoutError,
  A2AAuthError,
  A2AJobError,
  A2AJobFailedError,
  A2AJobCanceledError,
  type A2AClientConfig,
  type A2ABearerConfig,
  type A2AMessage,
  type A2AResponse,
  type A2ATaskEnvelope,
  type A2AEvent,
  type A2AEventKind,
} from "./a2a/index.js";

// A2A producer surface (issue #933 — Chunk 1A: sync skeleton). Users invoke
// `mesh.a2a.mount(app, config, handler)`; the producer types + registry
// classes are exported for advanced wiring / testability.
export {
  A2AProducerRegistry,
  A2ATaskStore,
  buildAgentCard,
  buildBearerAuthMiddleware,
  buildCompletedTask,
  buildDispatcherMiddleware,
  buildFailedTask,
  buildWorkingTask,
  stringifyResult,
  TERMINAL_EVICTION_MS,
  DEFAULT_INPUT_MODES as A2A_DEFAULT_INPUT_MODES,
  DEFAULT_OUTPUT_MODES as A2A_DEFAULT_OUTPUT_MODES,
  JSONRPC_AUTH_ERROR as A2A_JSONRPC_AUTH_ERROR,
  JSONRPC_PARSE_ERROR as A2A_JSONRPC_PARSE_ERROR,
  JSONRPC_INVALID_REQUEST as A2A_JSONRPC_INVALID_REQUEST,
  JSONRPC_METHOD_NOT_FOUND as A2A_JSONRPC_METHOD_NOT_FOUND,
  JSONRPC_INVALID_PARAMS as A2A_JSONRPC_INVALID_PARAMS,
  type A2AMountConfig,
  type A2ASurfaceMetadata,
  type A2ADependencies,
  type A2AHandler,
  type CardRenderContext as A2ACardRenderContext,
  type TaskRecord as A2ATaskRecord,
} from "./a2a/producer/index.js";

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
  LlmContentPart,
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
  // Media parameter types
  MediaParamMeta,
  // A2A consumer config (issue #917)
  MeshA2AConfig,
} from "./types.js";

// Default export for convenience
export default mesh;
