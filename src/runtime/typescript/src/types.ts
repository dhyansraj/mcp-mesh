/**
 * Type definitions for @mcpmesh/sdk
 */

import { z } from "zod";

/**
 * Metadata for media-typed tool parameters.
 */
export interface MediaParamMeta {
    mediaType: string;
}

/**
 * Create a Zod schema for a tool parameter that accepts media URIs.
 *
 * The generated JSON schema will include x-media-type for LLM tool discovery.
 * The framework detects the "[media:TYPE]" prefix in descriptions during
 * schema post-processing.
 *
 * @param mediaType - MIME type pattern (e.g., "image/*", "audio/wav", "*\/*")
 * @returns An optional string Zod schema with media type convention in description
 *
 * @example
 * ```typescript
 * import { mediaParam } from "@mcpmesh/sdk";
 *
 * agent.addTool({
 *   name: "analyze",
 *   parameters: z.object({
 *     question: z.string(),
 *     image: mediaParam("image/*"),
 *   }),
 *   execute: async ({ question, image }) => {
 *     if (image) return await llm("analyze", { media: [image] });
 *     return await llm("analyze");
 *   },
 * });
 * ```
 */
export function mediaParam(mediaType: string = "*/*"): z.ZodOptional<z.ZodString> {
    return z.string()
        .optional()
        .describe(`[media:${mediaType}] Media URI for this parameter`);
}

// Re-export types from core
export type {
  JsAgentHandle,
  JsMeshEvent,
  JsAgentSpec,
  JsToolSpec,
  JsDependencySpec,
  JsLlmAgentSpec,
  JsLlmToolInfo,
  JsLlmProviderInfo,
} from "@mcpmesh/core";

/**
 * Type marker for DDDI injection of a long-running-task handle (Phase 1
 * — MeshJob substrate).
 *
 * Used as a parameter-position type annotation on a tool registered with
 * `agent.addTool({ task: true, ... })` (producer) or `mesh.route(...)`
 * with a `task=true` dependency (consumer). The mesh runtime injects:
 *
 * - On the **producer side** (a tool decorated `{ task: true }` invoked
 *   via the inbound job-dispatch path or claim worker): a
 *   `JobController` exposing
 *   `await job.updateProgress(...)` /
 *   `await job.complete(result)` / `await job.fail(error)`.
 *
 * - On the **consumer side** (a function depending on a remote
 *   `task=true` capability): a submitter that returns a `JobProxy`
 *   exposing `await proxy.wait(timeoutSecs?)` / `await proxy.status()`
 *   / `await proxy.cancel(reason?)`.
 *
 * A MeshJob parameter is **orthogonal** to positional MeshTool slots
 * per `MESHJOB_DDDI_CONTRACT.md` — it does not consume a positional
 * dependency-injection index.
 *
 * If a function declaring a MeshJob param is invoked as a regular
 * synchronous tool call (no `X-Mesh-Job-Id` header, no claim path),
 * the runtime injects `null` for the slot. Producer code SHOULD treat
 * `null` as a fast path with no progress reporting.
 *
 * The type itself is structurally minimal because TypeScript erases
 * structural types at runtime; the DDDI resolver records signature
 * positions explicitly when the SDK builds the tool definition (see
 * `__tests__/resolver-meshjob.spec.ts`).
 *
 * @example Producer
 * ```typescript
 * agent.addTool({
 *   name: "plan_trip",
 *   capability: "plan_trip",
 *   task: true,
 *   parameters: z.object({ userId: z.string() }),
 *   dependencies: [{ capability: "weather" }],
 *   meshJobParamIndex: 2,  // signature position of `job` below
 *   execute: async (
 *     { userId },
 *     weather: McpMeshTool | null = null,
 *     job: MeshJob | null = null,
 *   ) => {
 *     await job?.updateProgress(0.1, "checking weather");
 *     const w = await weather?.({ city: "PDX" });
 *     await job?.updateProgress(0.9, "done");
 *     return { itinerary: w };
 *   },
 * });
 * ```
 */
export interface MeshJob {
  // Producer-side surface (when injected as JobController):
  jobId?: string;
  updateProgress?(progress: number, message?: string): Promise<void>;
  complete?(result: unknown): Promise<void>;
  fail?(error: string): Promise<void>;
  /**
   * Wait for the next event posted into this job's event log.
   *
   * Returns the event object on arrival, `null` on timeout. Cursor is
   * per-controller-instance (shared across `clone`s); a fresh
   * controller for the same `jobId` replays from seq=0.
   *
   * Mirrors Python's `MeshJob.recv_event` (event-channel extension that
   * shipped with v2.2 via PR #1041). Throws on `JobNotFound` /
   * transport-layer failures; `timeoutSecs` rejects NaN/Infinity/negative.
   */
  recvEvent?(types?: string[], timeoutSecs?: number): Promise<import("./jobs.js").JobEvent | null>;

  // Consumer-side surface (when injected as JobProxy / submitter):
  submit?(payload?: Record<string, unknown>, options?: {
    maxDuration?: number;
    maxRetries?: number;
    totalDeadline?: number;
    ownerInstanceId?: string;
  }): Promise<MeshJob>;
  wait?(timeoutSecs?: number): Promise<unknown>;
  status?(): Promise<Record<string, unknown>>;
  cancel?(reason?: string): Promise<void>;
  /**
   * Post an event into this job's event log. The running handler
   * (inside the `task: true` job) will see it on its next `recvEvent`
   * call — or wake immediately if it's currently long-polling.
   *
   * Mirrors Python's `MeshJob.send_event`. Throws `JobNotFoundError` /
   * `JobTerminalError` for the corresponding registry error codes.
   */
  sendEvent?(eventType: string, payload?: unknown): Promise<import("./jobs.js").JobEventReceipt>;
}

/**
 * Dependency specification for mesh tool DI.
 *
 * Can be specified as a simple string (capability name) or
 * a full object with tags and version filters.
 *
 * @example
 * ```typescript
 * // Simple: just capability name
 * dependencies: ["date-service"]
 *
 * // With filters
 * dependencies: [
 *   { capability: "data-service", tags: ["+fast"] },
 *   { capability: "formatter", version: ">=2.0.0" }
 * ]
 * ```
 */
/**
 * Tag specification - can be a simple string or array of strings for OR alternatives.
 * e.g., ["required", ["python", "typescript"]] = required AND (python OR typescript)
 */
export type TagSpec = string | string[];

export type DependencySpec =
  | string
  | {
      /** Capability name to depend on */
      capability: string;
      /** Tags for filtering. Supports OR alternatives via nested arrays.
       * e.g., ["+fast", "-deprecated"] or ["api", ["v1", "v2"]] for api AND (v1 OR v2)
       */
      tags?: TagSpec[];
      /** Version constraint (e.g., ">=2.0.0") */
      version?: string;
      /** Issue #547: optional Zod schema describing the expected provider response.
       * When set, the registry uses the canonical hash to filter producers
       * whose output schema matches under {@link matchMode}. Backward compat:
       * if omitted, no schema check is performed.
       */
      expectedSchema?: z.ZodType<unknown>;
      /** Issue #547: how to compare producer output schema against
       * {@link expectedSchema}. Defaults to "subset" when expectedSchema is set.
       */
      matchMode?: "subset" | "strict";
    };

/**
 * Normalized dependency specification (after processing).
 */
export interface NormalizedDependency {
  capability: string;
  tags: TagSpec[];
  version?: string;
  /** Issue #547: raw JSON Schema (post-zodToJsonSchema) for the expected
   * dependency response. Normalization is deferred to the heartbeat pipeline
   * to keep decorator-time work cheap and consistent with Python parity.
   */
  expectedSchemaRaw?: object;
  /** Issue #547: schema match mode ("subset" or "strict"). */
  matchMode?: "subset" | "strict";
}

/**
 * Resolved dependency info from registry.
 */
export interface ResolvedDependency {
  /** Capability name */
  capability: string;
  /** Agent ID providing this capability */
  agentId: string;
  /** Endpoint URL (e.g., "http://10.0.0.5:8000") */
  endpoint: string;
  /** Function name to call */
  functionName: string;
}

/**
 * Configuration for a MeshAgent.
 *
 * Environment variables take precedence over config values:
 * - MCP_MESH_AGENT_NAME: Override agent name
 * - MCP_MESH_HTTP_HOST: Override host (auto-detected if not set)
 * - MCP_MESH_HTTP_PORT: Override port
 * - MCP_MESH_NAMESPACE: Override namespace
 * - MCP_MESH_REGISTRY_URL: Override registry URL
 * - MCP_MESH_HEALTH_INTERVAL: Override heartbeat interval
 */
export interface AgentConfig {
  /** Unique agent name/identifier. Env: MCP_MESH_AGENT_NAME */
  name: string;
  /** Agent version (semver). Defaults to "1.0.0" */
  version?: string;
  /** Human-readable description */
  description?: string;
  /** HTTP port for this agent. Env: MCP_MESH_HTTP_PORT */
  httpPort: number;
  /** HTTP host announced to registry. Env: MCP_MESH_HTTP_HOST (auto-detected if not set) */
  httpHost?: string;
  /** Namespace for isolation. Env: MCP_MESH_NAMESPACE. Defaults to "default" */
  namespace?: string;
  /** Heartbeat interval in seconds. Env: MCP_MESH_HEALTH_INTERVAL. Defaults to 5 */
  heartbeatInterval?: number;
}

/**
 * Resolved configuration with all defaults applied.
 * Note: Does not include deprecated aliases (port, host).
 */
export interface ResolvedAgentConfig {
  name: string;
  version: string;
  description: string;
  httpPort: number;
  httpHost: string;
  namespace: string;
  registryUrl: string;
  heartbeatInterval: number;
}

/**
 * Proxy configuration for a dependency.
 */
export interface DependencyKwargs {
  /** Request timeout in seconds. Defaults to 30 */
  timeout?: number;
  /** Total number of attempts (1 = one attempt with zero retries). Defaults to 1 */
  maxAttempts?: number;
  /** Enable streaming responses (uses streamTimeout instead of timeout). Defaults to false */
  streaming?: boolean;
  /** Require session affinity. Defaults to false */
  sessionRequired?: boolean;
  /** Timeout for streaming/LLM responses in seconds. Defaults to 300 */
  streamTimeout?: number;
  /** Extra headers to send with every request to this dependency */
  customHeaders?: Record<string, string>;
  /** Initial retry delay in seconds. Defaults to 0.1 */
  retryDelay?: number;
  /** Retry backoff multiplier. Defaults to 2.0 */
  retryBackoff?: number;
  /** Max response body size in bytes. Defaults to 10MB (10485760) */
  maxResponseSize?: number;
}

/**
 * Per-tool A2A bridge configuration (issue #917).
 *
 * When set on a `MeshToolDef`, the framework constructs a per-config
 * `A2AClient` and injects it into the user's `execute` function as the
 * LAST positional argument (after the standard dependency proxies and
 * — for `task: true` tools — after the `JobController`). Multiple
 * tools sharing the same `(url, skillId, auth, timeoutMs)` tuple share
 * one cached client so the underlying undici connection pool is
 * amortised.
 *
 * The presence of `a2aConfig` ALSO opts the tool into auto-tag
 * injection: at heartbeat-build time the framework appends the
 * surrounding agent name to the tool's tags array so downstream
 * resolvers can pin a specific bridge via the tag selector. Mirrors
 * Python's `@mesh.a2a_consumer` and Java's `@A2AConsumer`.
 */
export interface MeshA2AConfig {
  /** Required: A2A endpoint URL. Trailing slashes are stripped. */
  url: string;
  /** Optional: skill ID to invoke. Defaults to the tool's `capability`. */
  skillId?: string;
  /** Optional: bearer credential (instance or `{ tokenEnv }` / `{ token }` config). */
  auth?:
    | { token?: string; tokenEnv?: string }
    | { authorizationHeader: () => string };
  /** Optional: per-call deadline (ms). Default 30_000. */
  timeoutMs?: number;
  /** Optional: initial backoff between `tasks/get` polls (ms). Default 500. */
  pollIntervalMs?: number;
  /** Optional: cap on the backoff between polls (ms). Default 2_000. */
  pollIntervalMaxMs?: number;
}

/**
 * Tool definition for MeshAgent.
 */
export interface MeshToolDef<T extends z.ZodType = z.ZodType> {
  /** Tool name (used in MCP protocol) */
  name: string;
  /** Capability name for mesh discovery. Defaults to tool name */
  capability?: string;
  /** Human-readable description */
  description?: string;
  /** Tags for filtering (e.g., ["tools", "math"]) */
  tags?: string[];
  /** Version of this capability. Defaults to "1.0.0" */
  version?: string;
  /** Zod schema for input parameters */
  parameters: T;
  /**
   * Issue #547: Zod schema for the tool's return value.
   *
   * Optional, opt-in. When provided, the SDK extracts and normalizes the
   * output schema and ships it to the registry alongside the input schema
   * so consumers can match producers by canonical schema hash.
   *
   * Zod cannot infer the return type from the handler signature (unlike
   * Python's reflection on Pydantic return annotations), so users must
   * provide this explicitly.
   */
  outputSchema?: z.ZodType<unknown>;
  /**
   * Issue #547 Phase 4: per-tool override for the schema verdict policy.
   *
   * When `true` (default), a BLOCK verdict from the schema normalizer
   * refuses agent startup. Set to `false` as a producer-side escape hatch
   * to demote BLOCK to WARN for this specific tool. Wins even when the
   * cluster-wide `MCP_MESH_SCHEMA_STRICT=true` env var is set (which
   * otherwise promotes WARN to BLOCK across all tools).
   */
  outputSchemaStrict?: boolean;
  /**
   * Phase 1 MeshJob substrate: mark this tool as long-running.
   *
   * When `true`, producers advertise `task=true` in their tool
   * metadata so consumers know to invoke this capability via job
   * semantics (`mesh.MeshJob.submit(...) → wait/poll`) rather than as
   * a regular synchronous `tools/call`. The actual job-context binding
   * happens at inbound call time via the dispatch wrapper.
   *
   * Constraints (validated at `addTool` time):
   *
   *   - `execute` MUST be an `async` function (long-running tools need
   *     a Promise-based control flow to drive `MeshJob.updateProgress()`,
   *     cancellation, and outbound polling). Sync `execute` raises a
   *     clear error at registration.
   *
   * Default: `false` (regular synchronous tool). See
   * `MESHJOB_DESIGN.org` "Producer-side flow".
   */
  task?: boolean;
  /**
   * Phase 1 MeshJob substrate (producer-side): signature position of
   * the `MeshJob` parameter on the user's `execute` function.
   *
   * When set on a `task: true` tool, the runtime injects a
   * `JobController` at this position when the tool is invoked under
   * a job context (claim path or inbound call carrying
   * `X-Mesh-Job-Id`). When the tool is invoked synchronously without
   * a job context, the runtime injects `null` per
   * `MESHJOB_DDDI_CONTRACT.md`.
   *
   * Position 0 is reserved for `args`; deps start at 1. The
   * `MeshJob` slot is orthogonal to MeshTool positional indexing —
   * MeshTool deps skip the `meshJobParamIndex` position and shift
   * accordingly. See `resolver-meshjob.ts` for the contract test
   * seam.
   *
   * Producer example with one MeshTool dep and a MeshJob slot:
   * ```ts
   * agent.addTool({
   *   task: true,
   *   dependencies: ["weather"],
   *   meshJobParamIndex: 2,  // job at sig pos 2
   *   execute: async (
   *     { city },
   *     weather: McpMeshTool | null = null,  // dep at sig pos 1
   *     job: MeshJob | null = null,           // controller at sig pos 2
   *   ) => { ... },
   * });
   * ```
   */
  meshJobParamIndex?: number;
  /**
   * Phase 1 MeshJob substrate (consumer-side): index into
   * `dependencies` whose proxy should be injected as a
   * `MeshJobSubmitter` (returns a `JobProxy`) instead of a regular
   * `McpMeshTool` proxy.
   *
   * Use this when the consumer wants to call a remote `task: true`
   * capability via job semantics (submit + poll/wait) rather than as
   * a regular synchronous `tools/call`. The user function receives a
   * `MeshJob`-typed handle at the dep's positional slot.
   *
   * Consumer example:
   * ```ts
   * agent.addTool({
   *   name: "commission_report",
   *   dependencies: ["generate_report"],
   *   meshJobDepIndex: 0,  // generate_report is task=true
   *   execute: async ({ userId }, generateReport: MeshJob | null = null) => {
   *     const proxy = await generateReport!.submit(
   *       { user_id: userId, sections: ["intro"] },
   *       { maxDuration: 60 },
   *     );
   *     return await proxy.wait(60);
   *   },
   * });
   * ```
   */
  meshJobDepIndex?: number;
  /**
   * Issue #894: per-tool retry-eligible exception whitelist.
   *
   * When a `task: true` handler raises an Error whose constructor matches
   * one of the entries (`err instanceof cls`), the dispatch wrapper calls
   * `controller.releaseLease(reason)` instead of `controller.fail(reason)`.
   * The registry then resets `owner_instance_id` so a peer replica can
   * re-claim within ~5s — useful for transient failures (network blips,
   * upstream unavailable) where the next attempt on a different replica
   * is likely to succeed.
   *
   * Constraints (validated at `addTool` time):
   *
   *   - requires `task: true` (no-op for synchronous tools — non-job
   *     handlers don't have a controller, so retry has no meaning);
   *   - entries must be Error constructor classes (functions); anything
   *     else throws at registration.
   *
   * Default: `undefined` (no retry-eligible exceptions; all raises mark
   * the row failed). Empty array is equivalent.
   *
   * @example
   * ```ts
   * agent.addTool({
   *   task: true,
   *   retryOn: [TransientUpstreamError, AbortError],
   *   execute: async (args, job: MeshJob | null = null) => {
   *     // If this throws TransientUpstreamError, the registry will
   *     // hand the job to a peer replica within ~5s.
   *     return await callFlakeyApi(args);
   *   },
   * });
   * ```
   */
  retryOn?: Array<new (...args: unknown[]) => Error>;
  /**
   * Dependencies required by this tool.
   * Injected positionally as McpMeshTool params after args.
   *
   * @example
   * ```typescript
   * dependencies: ["time-service", "calculator"],
   * execute: async (
   *   { query },
   *   timeTool: McpMeshTool | null = null,  // dependencies[0]
   *   calcTool: McpMeshTool | null = null   // dependencies[1]
   * ) => { ... }
   * ```
   */
  dependencies?: DependencySpec[];
  /**
   * Per-dependency configuration indexed by position.
   * Array index corresponds to dependencies array position.
   * Supports duplicate capabilities with different settings.
   */
  dependencyKwargs?: DependencyKwargs[];
  /**
   * Issue #917: A2A bridge configuration. When set, the framework
   * constructs a cached `A2AClient` and injects it at the trailing
   * positional slot of `execute` (after deps + JobController). Also
   * opts the tool into consumer-name auto-tag injection.
   */
  a2aConfig?: MeshA2AConfig;
  /**
   * Tool implementation.
   *
   * Returns any serializable value - the SDK auto-converts to string:
   * - string: returned as-is
   * - number/boolean: converted via JSON.stringify
   * - object/array: converted via JSON.stringify
   * - null/undefined: converted to empty string
   *
   * @param args - Parsed arguments matching the Zod schema
   * @param deps - Dependency proxies injected positionally (McpMeshTool | null)
   *
   * @example
   * ```typescript
   * // Return number - auto-serialized
   * execute: async ({ a, b }) => a + b
   *
   * // Return object - auto-serialized to JSON
   * execute: async ({ a, b }) => ({ result: a + b, source: "local" })
   *
   * // With dependencies
   * execute: async (
   *   { query },
   *   timeTool: McpMeshTool | null = null,
   *   calcTool: McpMeshTool | null = null
   * ) => {
   *   if (timeTool) {
   *     const time = await timeTool();
   *   }
   *   return { result: time };
   * }
   * ```
   */
  execute: (
    args: z.infer<T>,
    ...deps: (McpMeshTool | MeshJob | null)[]
  ) => Promise<unknown> | unknown;
}

/**
 * Proxy for calling remote MCP tools.
 *
 * Dependencies are injected as McpMeshTool instances.
 * Always check for null (dependency may be unavailable).
 *
 * @example
 * ```typescript
 * execute: async (
 *   { query },
 *   dateTool: McpMeshTool | null = null
 * ) => {
 *   if (!dateTool) return "Date service unavailable";
 *   const date = await dateTool({ format: "ISO" });
 *   return `Today is ${date}`;
 * }
 * ```
 */
export interface McpMeshTool {
  /**
   * Call the bound tool with arguments.
   * Returns parsed result (object/array) or raw string if not JSON.
   * Matches Python's behavior - no need to JSON.parse().
   */
  (args?: Record<string, unknown>, options?: { headers?: Record<string, string> }): Promise<unknown>;

  /**
   * Call a specific tool by name.
   * Returns parsed result (object/array) or raw string if not JSON.
   */
  callTool(toolName: string, args?: Record<string, unknown>, options?: { headers?: Record<string, string> }): Promise<unknown>;

  /**
   * Stream text chunks from a remote ``Stream[str]`` tool.
   *
   * Returns an async iterable that yields each chunk the producer emits via
   * MCP ``notifications/progress``. The final result message ends the stream
   * (its content is NOT yielded — iterate to get the whole stream).
   *
   * NOTE: If the producer doesn't actually emit progress notifications, the
   * underlying SSE response will only contain the final ``result`` and this
   * iterable will yield nothing.
   *
   * @example
   * ```typescript
   * for await (const chunk of planner.stream({ destination: "Tokyo" })) {
   *   process.stdout.write(chunk);
   * }
   * ```
   */
  stream(args?: Record<string, unknown>, options?: { headers?: Record<string, string> }): AsyncIterable<string>;

  /**
   * Get the endpoint URL for this dependency.
   */
  readonly endpoint: string;

  /**
   * Get the capability name.
   */
  readonly capability: string;

  /**
   * Get the function name to call.
   */
  readonly functionName: string;

  /**
   * Check if the proxy is connected/available.
   */
  readonly isAvailable: boolean;
}

/**
 * @deprecated Use McpMeshTool instead. McpMeshAgent will be removed in a future version.
 */
export type McpMeshAgent = McpMeshTool;

/**
 * Internal metadata for a registered tool.
 */
export interface ToolMeta {
  capability: string;
  version: string;
  tags: string[];
  description: string;
  inputSchema?: string;
  /** Issue #547: raw JSON Schema (post-zodToJsonSchema) for return type. */
  outputSchemaRaw?: object;
  /** Issue #547 Phase 4: per-tool override for the schema verdict policy
   * (default true). When false, a BLOCK verdict for this tool is demoted
   * to WARN instead of refusing startup. */
  outputSchemaStrict?: boolean;
  /** Normalized dependencies for this tool */
  dependencies: NormalizedDependency[];
  /** Per-dependency configuration indexed by position (matches dependencies array) */
  dependencyKwargs?: DependencyKwargs[];
  /** Phase 1 MeshJob substrate: producer flag advertising this tool as
   * long-running so consumers invoke via job semantics. See
   * MeshToolDef.task for full semantics. */
  task?: boolean;
  /** Phase 1 MeshJob substrate: producer-side signature position of
   * the MeshJob param. Used by the inbound dispatch wrapper to inject
   * a JobController when running as a job. */
  meshJobParamIndex?: number;
  /** Phase 1 MeshJob substrate: consumer-side index into dependencies
   * whose slot should hold a MeshJobSubmitter (instead of a regular
   * McpMeshTool proxy). */
  meshJobDepIndex?: number;
  /** Issue #917: A2A bridge marker — when true, the heartbeat-build
   * pass appends the surrounding agent name to the tool's tags before
   * the registry sees them. */
  a2aConsumer?: boolean;
  /** Issue #917: agent name captured at addTool time so the heartbeat
   * pass injects the correct value (in case the agent is renamed via
   * env between addTool and heartbeat). */
  a2aAgentName?: string;
}

// ============================================================================
// LLM Types
// ============================================================================

/**
 * LLM provider specification.
 * Mesh delegation only — describes the capability/tag filter used to
 * discover an ``@mesh.llm_provider`` in the mesh.
 *
 * @example
 * ```typescript
 * // Mesh delegation (discover LLM provider via mesh)
 * provider: { capability: "llm", tags: ["+claude"] }
 * ```
 */
export type LlmProviderSpec = {
  /** Capability name to discover in mesh */
  capability: string;
  /** Tags for filtering (e.g., ["+claude", "-deprecated"]) */
  tags?: string[];
};

/**
 * LLM filter specification for tool access.
 */
export type LlmFilterSpec =
  | { capability: string }
  | { tags: string[] };

/**
 * Filter mode for LLM tool resolution.
 */
export type LlmFilterMode = "all" | "best_match" | "*";

/**
 * Metadata attached to LLM responses.
 */
export interface LlmMeta {
  /** Total input tokens used */
  inputTokens: number;
  /** Total output tokens used */
  outputTokens: number;
  /** Total tokens (input + output) */
  totalTokens: number;
  /** Response latency in milliseconds */
  latencyMs: number;
  /** Number of agentic loop iterations */
  iterations: number;
  /** Tool calls made during the agentic loop */
  toolCalls: LlmToolCall[];
  /** Model used for generation */
  model: string;
  /** Provider used (e.g., ``mesh:<endpoint>`` or ``mesh:<capability>``) */
  provider: string;
}

/**
 * Tool call record for LLM tracing.
 */
export interface LlmToolCall {
  /** Tool function name */
  name: string;
  /** Arguments passed to the tool */
  args: Record<string, unknown>;
  /** Result from the tool */
  result: unknown;
  /** Whether the call succeeded */
  success: boolean;
  /** Error message if failed */
  error?: string;
  /** Latency in milliseconds */
  latencyMs: number;
}

/**
 * Content part for multipart messages (text + images).
 * Uses OpenAI-compatible format which Vercel AI SDK converts per-vendor.
 */
export type LlmContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string; detail?: string } };

/**
 * LiteLLM-style message format.
 */
export interface LlmMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | LlmContentPart[] | null;
  /** Tool calls requested by the assistant */
  tool_calls?: LlmToolCallRequest[];
  /** Tool call ID (for tool responses) */
  tool_call_id?: string;
  /** Function name (for tool responses) */
  name?: string;
}

/**
 * Tool call request from LLM.
 */
export interface LlmToolCallRequest {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string; // JSON string
  };
}

/**
 * Tool definition for LLM function calling.
 */
export interface LlmToolDefinition {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, unknown>; // JSON Schema
  };
}

/**
 * LLM completion request parameters (LiteLLM-compatible).
 */
export interface LlmCompletionParams {
  /** Model identifier (e.g., "anthropic/claude-sonnet-4-5") */
  model: string;
  /** Messages array */
  messages: LlmMessage[];
  /** Available tools */
  tools?: LlmToolDefinition[];
  /** Tool choice strategy */
  tool_choice?: "auto" | "none" | "required" | { type: "function"; function: { name: string } };
  /** Maximum tokens to generate */
  max_tokens?: number;
  /** Sampling temperature */
  temperature?: number;
  /** Top-p sampling */
  top_p?: number;
  /** Stop sequences */
  stop?: string[];
  /** Stream responses */
  stream?: boolean;
}

/**
 * LLM completion response (LiteLLM-compatible).
 */
export interface LlmCompletionResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: LlmMessage;
    finish_reason: "stop" | "tool_calls" | "length" | "content_filter";
  }>;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/**
 * Configuration for mesh.llm() tool definition.
 */
export interface MeshLlmConfig<TParams extends z.ZodType, TReturns extends z.ZodType | undefined = undefined> {
  /** Tool name (used in MCP protocol) */
  name: string;
  /** Capability name for mesh discovery. Defaults to tool name */
  capability?: string;
  /** Human-readable description */
  description?: string;
  /** Tags for filtering (e.g., ["tools", "llm"]) */
  tags?: string[];
  /** Version of this capability. Defaults to "1.0.0" */
  version?: string;

  // LLM Configuration
  /** LLM provider — mesh-delegation spec (capability + tag filter) */
  provider: LlmProviderSpec;
  /** Model override (e.g., "anthropic/claude-sonnet-4-5") */
  model?: string;
  /** Maximum agentic loop iterations. Defaults to 10 */
  maxIterations?: number;
  /** Enable parallel tool execution. When true, multiple tool calls execute concurrently. Defaults to false */
  parallelToolCalls?: boolean;

  // System prompt
  /** System prompt template (inline or "file://path/to/template.hbs") */
  systemPrompt?: string;
  /** Parameter name to use for template context */
  contextParam?: string;

  // Tool filtering
  /** Filter specification for which mesh tools the LLM can access */
  filter?: LlmFilterSpec[];
  /** Filter mode: "all" (union), "best_match" (single best), "*" (all tools) */
  filterMode?: LlmFilterMode;

  // Generation parameters (forwarded to the mesh-delegated provider)
  /** Maximum tokens to generate */
  maxOutputTokens?: number;
  /** Sampling temperature */
  temperature?: number;
  /** Top-p sampling */
  topP?: number;
  /** Stop sequences */
  stop?: string[];

  // Schema
  /** Zod schema for input parameters */
  parameters: TParams;
  /** Zod schema for structured output (optional - returns string if not specified) */
  returns?: TReturns;
  /**
   * Output mode for response parsing:
   * - "strict": Enforce exact schema compliance (use provider's native structured output if available)
   * - "hint": Include schema in prompt but accept any response (default)
   * - "text": Return raw text without parsing
   */
  outputMode?: LlmOutputMode;

  /**
   * Execute handler - receives injected LLM agent.
   * The llm parameter is a callable that runs the agentic loop.
   */
  execute: (
    args: z.infer<TParams>,
    context: {
      /** Call the LLM with the user message */
      llm: LlmAgent<TReturns extends z.ZodType ? z.infer<TReturns> : string>;
    }
  ) => Promise<TReturns extends z.ZodType ? z.infer<TReturns> : string>;
}

/**
 * Message input for multi-turn conversations.
 * Can be a simple string (converted to user message) or an array of messages.
 */
export type LlmMessageInput =
  | string
  | Array<{ role: "user" | "assistant"; content: string }>;

/**
 * Injected LLM agent for mesh.llm() handlers.
 */
export interface LlmAgent<T = string> {
  /**
   * Send a message to the LLM and run the agentic loop.
   *
   * @param message - User message string or array of messages for multi-turn
   * @param options - Optional runtime overrides
   * @returns The LLM response (validated if schema provided)
   *
   * @example
   * ```typescript
   * // Single message
   * const result = await llm("What is 5+3?");
   *
   * // Multi-turn conversation
   * const result = await llm([
   *   { role: "user", content: "What is 5+3?" },
   *   { role: "assistant", content: "8" },
   *   { role: "user", content: "Now multiply that by 2" },
   * ]);
   * ```
   */
  (message: LlmMessageInput, options?: LlmCallOptions): Promise<T>;

  /**
   * Get response metadata from the last call.
   */
  readonly meta: LlmMeta | null;

  /**
   * Get available tools for this LLM agent.
   */
  readonly tools: LlmToolProxy[];

  /**
   * Override the system prompt at runtime.
   *
   * @param prompt - New system prompt (inline or "file://path.hbs")
   */
  setSystemPrompt(prompt: string): void;

  /**
   * Stream the assistant's text response chunk-by-chunk from a streaming
   * mesh-delegated provider (Python's ``@mesh.llm_provider`` exposes a
   * ``process_chat_stream`` MCP tool tagged ``ai.mcpmesh.stream``).
   *
   * **Tag opt-in (REQUIRED):** TypeScript users must explicitly add
   * ``"ai.mcpmesh.stream"`` to their provider tags to discriminate the
   * streaming variant from the buffered one. Python's ``@mesh.llm`` does
   * this automatically based on the function's ``Stream[str]`` return type;
   * TS does not perform that return-type analysis at decorator time, so the
   * opt-in must be explicit:
   *
   * ```ts
   * server.addTool(mesh.llm({
   *   name: "chat_stream",
   *   provider: { capability: "llm", tags: ["+claude", "ai.mcpmesh.stream"] },
   *   parameters: z.object({ message: z.string() }),
   *   execute: async ({ message }, { llm }) => {
   *     for await (const chunk of llm.stream(message)) {
   *       process.stdout.write(chunk);
   *     }
   *     return "ok";
   *   },
   * }));
   * ```
   *
   * @param message - User message (string or multi-turn array)
   * @param options - Same runtime overrides as the callable form
   * @returns AsyncIterable of text chunks (final accumulated result is NOT yielded)
   */
  stream(message: LlmMessageInput, options?: LlmCallOptions): AsyncIterable<string>;
}

/**
 * Context merge mode for runtime context override.
 */
export type LlmContextMode = "merge" | "replace";

/**
 * Output mode for response parsing.
 */
export type LlmOutputMode = "strict" | "hint" | "text";

/**
 * Runtime options for LLM calls.
 */
export interface LlmCallOptions {
  /** Additional context for template rendering */
  context?: Record<string, unknown>;
  /** Context merge mode: "merge" (default) adds to base context, "replace" overrides entirely */
  contextMode?: LlmContextMode;
  /** Override max tokens */
  maxOutputTokens?: number;
  /** Override temperature */
  temperature?: number;
  /** Override max iterations */
  maxIterations?: number;
  /**
   * Media items to include alongside the user prompt.
   *
   * Each item is either a URI string (resolved via MediaStore.fetch()) or
   * an inline `{ data: Buffer; mimeType: string }` object.
   *
   * When provided, the user message is converted to multipart content
   * with text + image_url blocks (OpenAI-compatible format).
   */
  media?: Array<string | { data: Buffer; mimeType: string }>;
  /**
   * Escape-hatch for vendor-specific kwargs that aren't covered by the
   * typed option surface (e.g., Gemini `thinking_config`, Anthropic
   * `output_config`, OpenAI `reasoning_effort`). Merged into the wire
   * `model_params` dict BEFORE typed fields, so typed options
   * (`maxOutputTokens`, `temperature`, etc.) win on collision and the
   * typed surface stays authoritative. For arbitrary kwargs the typed
   * surface doesn't expose, this field is the only way to set them.
   *
   * Example: ``modelParams: { thinking_config: { thinking_budget: 0 } }``
   */
  modelParams?: Record<string, unknown>;
}

/**
 * Proxy for calling mesh tools from LLM agent.
 */
export interface LlmToolProxy {
  /** Tool function name */
  name: string;
  /** Capability name */
  capability: string;
  /** Description */
  description?: string;
  /** Input schema (JSON Schema format) */
  inputSchema?: Record<string, unknown>;
  /** Endpoint URL */
  endpoint: string;
  /** Agent ID providing this tool */
  agentId: string;

  /**
   * Call the tool.
   */
  (args: Record<string, unknown>): Promise<unknown>;
}

// ============================================================================
// LLM Provider Types (Phase 4)
// ============================================================================

/**
 * Standard LLM request format for mesh-delegated LLM calls.
 *
 * This interface is used when delegating LLM calls to mesh-registered LLM provider
 * agents via mesh.llmProvider(). It standardizes the request format across the mesh.
 *
 * @example
 * ```typescript
 * // Provider side (automatic with mesh.llmProvider):
 * server.addTool(mesh.llmProvider({
 *   model: "anthropic/claude-sonnet-4-5",
 *   capability: "llm",
 * }));
 *
 * // Consumer side:
 * const response = await llmProvider({
 *   request: {
 *     messages: [
 *       { role: "system", content: "You are helpful." },
 *       { role: "user", content: "Hello!" },
 *     ],
 *   },
 * });
 * ```
 */
export interface MeshLlmRequest {
  /** List of message dicts with "role" and "content" keys (and optionally "tool_calls") */
  messages: LlmMessage[];
  /** Optional list of tool definitions (MCP format) */
  tools?: LlmToolDefinition[];
  /** Optional parameters to pass to the model (temperature, max_tokens, model, etc.) */
  model_params?: Record<string, unknown>;
  /** Optional arbitrary context data for debugging/tracing */
  context?: Record<string, unknown>;
  /** Optional request ID for tracking */
  request_id?: string;
  /** Optional agent name that initiated the request */
  caller_agent?: string;
}

/**
 * Usage metadata included in LLM provider responses.
 * Tracks token usage for cost monitoring.
 */
export interface MeshLlmUsage {
  /** Number of input/prompt tokens used */
  prompt_tokens: number;
  /** Number of output/completion tokens used */
  completion_tokens: number;
  /** Model used for generation */
  model: string;
}

/**
 * Response from an LLM provider.
 * Contains the assistant message with optional tool calls and usage metadata.
 */
export interface MeshLlmResponse {
  /** Role is always "assistant" for provider responses */
  role: "assistant";
  /** Text content from the LLM */
  content: string;
  /** Tool calls requested by the LLM (for agentic loop) */
  tool_calls?: LlmToolCallRequest[];
  /** Token usage metadata for cost tracking */
  _mesh_usage?: MeshLlmUsage;
}

/**
 * Configuration for mesh.llmProvider() tool definition.
 *
 * @example
 * ```typescript
 * server.addTool(mesh.llmProvider({
 *   model: "anthropic/claude-sonnet-4-5",
 *   capability: "llm",
 *   tags: ["llm", "claude", "anthropic", "provider"],
 *   maxOutputTokens: 4096,
 *   temperature: 0.7,
 * }));
 * ```
 */
export interface LlmProviderConfig {
  /** LLM model identifier (e.g., "anthropic/claude-sonnet-4-5", "openai/gpt-4o") */
  model: string;
  /** Capability name for mesh registration. Defaults to "llm" */
  capability?: string;
  /** Tags for mesh registration (e.g., ["llm", "claude", "anthropic"]) */
  tags?: string[];
  /** Version string for mesh registration. Defaults to "1.0.0" */
  version?: string;
  /** Maximum tokens to generate. Passed to Vercel AI SDK */
  maxOutputTokens?: number;
  /** Sampling temperature. Passed to Vercel AI SDK */
  temperature?: number;
  /** Top-p sampling. Passed to Vercel AI SDK */
  topP?: number;
  /** Tool name for MCP registration. Defaults to "process_chat" */
  name?: string;
  /** Description for the tool */
  description?: string;
}
