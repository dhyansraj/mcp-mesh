/**
 * Type definitions for @mcpmesh/sdk
 */

import type { z } from "zod";

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
export type DependencySpec =
  | string
  | {
      /** Capability name to depend on */
      capability: string;
      /** Tags for filtering (e.g., ["+fast", "-deprecated"]) */
      tags?: string[];
      /** Version constraint (e.g., ">=2.0.0") */
      version?: string;
    };

/**
 * Normalized dependency specification (after processing).
 */
export interface NormalizedDependency {
  capability: string;
  tags: string[];
  version?: string;
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
  port: number;
  /** HTTP host announced to registry. Env: MCP_MESH_HTTP_HOST (auto-detected if not set) */
  host?: string;
  /** Namespace for isolation. Env: MCP_MESH_NAMESPACE. Defaults to "default" */
  namespace?: string;
  /** Registry URL. Env: MCP_MESH_REGISTRY_URL. Defaults to "http://localhost:8000" */
  registryUrl?: string;
  /** Heartbeat interval in seconds. Env: MCP_MESH_HEALTH_INTERVAL. Defaults to 5 */
  heartbeatInterval?: number;
}

/**
 * Resolved configuration with all defaults applied.
 */
export type ResolvedAgentConfig = Required<AgentConfig>;

/**
 * Proxy configuration for a dependency.
 */
export interface DependencyKwargs {
  /** Request timeout in seconds. Defaults to 30 */
  timeout?: number;
  /** Total number of attempts (1 = one attempt with zero retries). Defaults to 1 */
  maxAttempts?: number;
  /** Enable streaming responses. Defaults to false */
  streaming?: boolean;
  /** Require session affinity. Defaults to false */
  sessionRequired?: boolean;
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
   * Dependencies required by this tool.
   * Injected positionally as McpMeshAgent params after args.
   *
   * @example
   * ```typescript
   * dependencies: ["time-service", "calculator"],
   * execute: async (
   *   { query },
   *   timeSvc: McpMeshAgent | null = null,  // dependencies[0]
   *   calc: McpMeshAgent | null = null      // dependencies[1]
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
   * Tool implementation.
   *
   * @param args - Parsed arguments matching the Zod schema
   * @param deps - Dependency proxies injected positionally (McpMeshAgent | null)
   *
   * @example
   * ```typescript
   * execute: async (
   *   { query },
   *   timeSvc: McpMeshAgent | null = null,
   *   calc: McpMeshAgent | null = null
   * ) => {
   *   if (timeSvc) {
   *     const time = await timeSvc();
   *   }
   *   return "result";
   * }
   * ```
   */
  execute: (
    args: z.infer<T>,
    ...deps: (McpMeshAgent | null)[]
  ) => Promise<string> | string;
}

/**
 * Proxy for calling remote MCP agents.
 *
 * Dependencies are injected as McpMeshAgent instances.
 * Always check for null (dependency may be unavailable).
 *
 * @example
 * ```typescript
 * execute: async (
 *   { query },
 *   dateSvc: McpMeshAgent | null = null
 * ) => {
 *   if (!dateSvc) return "Date service unavailable";
 *   const date = await dateSvc({ format: "ISO" });
 *   return `Today is ${date}`;
 * }
 * ```
 */
export interface McpMeshAgent {
  /**
   * Call the bound tool with arguments.
   * Returns parsed result (object/array) or raw string if not JSON.
   * Matches Python's behavior - no need to JSON.parse().
   */
  (args?: Record<string, unknown>): Promise<unknown>;

  /**
   * Call a specific tool by name.
   * Returns parsed result (object/array) or raw string if not JSON.
   */
  callTool(toolName: string, args?: Record<string, unknown>): Promise<unknown>;

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
 * Internal metadata for a registered tool.
 */
export interface ToolMeta {
  capability: string;
  version: string;
  tags: string[];
  description: string;
  inputSchema?: string;
  /** Normalized dependencies for this tool */
  dependencies: NormalizedDependency[];
  /** Per-dependency configuration indexed by position (matches dependencies array) */
  dependencyKwargs?: DependencyKwargs[];
}

// ============================================================================
// LLM Types
// ============================================================================

/**
 * LLM provider specification.
 * Can be a direct LiteLLM provider string or mesh delegation config.
 *
 * @example
 * ```typescript
 * // Direct LiteLLM provider
 * provider: "claude"
 * provider: "openai"
 *
 * // Mesh delegation (discover LLM provider via mesh)
 * provider: { capability: "llm", tags: ["+claude"] }
 * ```
 */
export type LlmProviderSpec =
  | string // Direct LiteLLM provider (e.g., "claude", "openai")
  | {
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
  /** Provider used (litellm provider name or mesh agent ID) */
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
 * LiteLLM-style message format.
 */
export interface LlmMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
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
  /** Model identifier (e.g., "anthropic/claude-sonnet-4-20250514") */
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
  /** LLM provider - direct string (LiteLLM) or mesh delegation object */
  provider: LlmProviderSpec;
  /** Model override (e.g., "anthropic/claude-sonnet-4-20250514") */
  model?: string;
  /** Maximum agentic loop iterations. Defaults to 10 */
  maxIterations?: number;

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

  // LiteLLM parameters
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
