/**
 * MeshLlmAgent - Agentic loop implementation for LLM-powered tools.
 *
 * This class handles:
 * - System prompt rendering (with Handlebars templates)
 * - Agentic loop with tool execution
 * - LLM provider calls (direct Vercel AI SDK or mesh delegation)
 * - Response parsing with Zod validation
 * - Metadata tracking (tokens, latency, tool calls)
 *
 * Configuration Hierarchy (ENV > Config):
 * - MESH_LLM_PROVIDER: Override provider for direct mode (e.g., "claude", "openai", "gemini")
 * - MESH_LLM_MODEL: Override model (e.g., "gpt-4o", "gemini-2.0-flash")
 * - MESH_LLM_MAX_ITERATIONS: Override max agentic loop iterations
 * - MESH_LLM_FILTER_MODE: Override tool filter mode ("all", "include", "exclude")
 *
 * @example
 * ```typescript
 * const agent = new MeshLlmAgent({
 *   provider: "claude",
 *   model: "anthropic/claude-sonnet-4-5",
 *   systemPrompt: "file://prompts/assistant.hbs",
 *   maxIterations: 10,
 *   returnSchema: ResponseSchema,
 * });
 *
 * const result = await agent.run("Help me calculate 2+2", {
 *   templateContext: { user: "John" },
 *   tools: resolvedToolProxies,
 * });
 * ```
 */

import type { ZodType } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import type {
  LlmProviderSpec,
  LlmMeta,
  LlmToolCall,
  LlmContentPart,
  LlmMessage,
  LlmToolDefinition,
  LlmToolCallRequest,
  LlmCompletionResponse,
  LlmToolProxy,
  LlmCallOptions,
  LlmMessageInput,
  LlmOutputMode,
  LlmContextMode,
} from "./types.js";
import { renderTemplate } from "./template.js";
import { ResponseParser } from "./response-parser.js";
import {
  MaxIterationsError,
  LLMAPIError,
  ToolExecutionError,
} from "./errors.js";
import { parseSSEResponse } from "./sse.js";
import {
  loadProvider,
  extractVendorFromModel,
  extractModelName,
} from "./llm-provider.js";
import { ProviderHandlerRegistry } from "./provider-handlers/index.js";
import { resolveMediaInputs } from "./media/index.js";
import { getCurrentTraceContext, getCurrentPropagatedHeaders } from "./proxy.js";
import {
  generateSpanId,
  publishTraceSpan,
  createTraceHeaders,
} from "./tracing.js";
import { fetchWithTimeout, isTimeoutError } from "./timeout-utils.js";
import { getDispatcher } from "./http-pool.js";

/**
 * Configuration for MeshLlmAgent.
 */
export interface MeshLlmAgentConfig {
  /** Function ID (used for event matching) */
  functionId: string;
  /** LLM provider spec */
  provider: LlmProviderSpec;
  /** Model override */
  model?: string;
  /** System prompt template */
  systemPrompt?: string;
  /** Parameter name for template context */
  contextParam?: string;
  /** Max agentic loop iterations */
  maxIterations: number;
  /** Max tokens */
  maxOutputTokens?: number;
  /** Temperature */
  temperature?: number;
  /** Top-p */
  topP?: number;
  /** Stop sequences */
  stop?: string[];
  /** Return schema for validation */
  returnSchema?: ZodType;
  /** Output mode: strict, hint, or text */
  outputMode?: LlmOutputMode;
  /** Enable parallel tool execution */
  parallelToolCalls?: boolean;
}

/**
 * Runtime context for agent execution.
 */
export interface AgentRunContext {
  /** Template context (from contextParam or runtime override) */
  templateContext?: Record<string, unknown>;
  /** Resolved tool proxies from mesh */
  tools: LlmToolProxy[];
  /** Resolved mesh provider (if using mesh delegation) */
  meshProvider?: {
    endpoint: string;
    functionName: string;
    model?: string;
  };
  /** Runtime overrides */
  options?: LlmCallOptions;
}

/**
 * Provider interface for making LLM completion calls.
 */
export interface LlmProvider {
  complete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
      // Issue #459: Output schema for provider to apply vendor-specific handling
      outputSchema?: { schema: Record<string, unknown>; name: string };
    }
  ): Promise<LlmCompletionResponse>;
}

/**
 * Default LiteLLM provider using HTTP proxy.
 * Assumes LiteLLM proxy is running at LITELLM_URL or localhost:4000.
 */
export class LiteLLMProvider implements LlmProvider {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || process.env.LITELLM_URL || "http://localhost:4000";
  }

  async complete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
    }
  ): Promise<LlmCompletionResponse> {
    const body: Record<string, unknown> = {
      model,
      messages,
    };

    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    if (options?.maxOutputTokens) body.max_tokens = options.maxOutputTokens;
    if (options?.temperature !== undefined) body.temperature = options.temperature;
    if (options?.topP !== undefined) body.top_p = options.topP;
    if (options?.stop) body.stop = options.stop;

    // Set up timeout (default 300s to match Python SDK's stream_timeout)
    const timeoutMs = parseInt(process.env.LITELLM_TIMEOUT_MS || "300000", 10);

    let response: Response;
    try {
      response = await fetchWithTimeout(`${this.baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        timeout: timeoutMs,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        dispatcher: getDispatcher(`${this.baseUrl}/v1/chat/completions`) as any,
      });
    } catch (error) {
      if (isTimeoutError(error)) {
        throw new LLMAPIError(408, `Request timed out after ${timeoutMs}ms`, "litellm");
      }
      throw new LLMAPIError(0, `Fetch failed: ${error instanceof Error ? error.message : String(error)}`, "litellm");
    }

    if (!response.ok) {
      const error = await response.text();
      throw new LLMAPIError(response.status, error, "litellm");
    }

    return (await response.json()) as LlmCompletionResponse;
  }
}

/**
 * Default model mappings for provider shorthand names.
 */
const DEFAULT_MODELS: Record<string, string> = {
  claude: "anthropic/claude-sonnet-4-5",
  openai: "openai/gpt-4o",
  anthropic: "anthropic/claude-sonnet-4-5",
  gemini: "google/gemini-3-flash-preview",
  google: "google/gemini-3-flash-preview",
  gpt4: "openai/gpt-4o",
  gpt35: "openai/gpt-3.5-turbo",
};

/**
 * Direct Vercel AI SDK provider.
 * Uses Vercel AI SDK (@ai-sdk/anthropic, @ai-sdk/openai, etc.) directly
 * without needing a proxy server.
 */
export class VercelDirectProvider implements LlmProvider {
  private providerSpec: string;
  private cachedProvider: ((modelId: string) => unknown) | null = null;
  private providerLoadAttempted = false;
  private toolProxies: Map<string, LlmToolProxy> = new Map();

  constructor(providerSpec: string) {
    this.providerSpec = providerSpec;
  }

  /**
   * Set tool proxies for execute callbacks in the Vercel AI SDK agentic loop.
   * When set, tools are created with execute callbacks and maxSteps is enabled,
   * letting the SDK handle the tool execution loop internally.
   */
  setToolProxies(tools: LlmToolProxy[]): void {
    this.toolProxies.clear();
    for (const tool of tools) {
      this.toolProxies.set(tool.name, tool);
    }
  }

  /**
   * Resolve the full model string from provider spec.
   * E.g., "claude" -> "anthropic/claude-sonnet-4-5"
   */
  private resolveModel(model?: string): string {
    // If explicit model provided, use it
    if (model && model !== "default") {
      // If model already has vendor prefix, use as-is
      if (model.includes("/")) {
        return model;
      }
      // Otherwise, try to add vendor prefix from provider spec
      const vendor = extractVendorFromModel(
        DEFAULT_MODELS[this.providerSpec.toLowerCase()] ?? this.providerSpec
      );
      if (vendor) {
        return `${vendor}/${model}`;
      }
      return model;
    }

    // Map shorthand provider to full model
    const defaultModel = DEFAULT_MODELS[this.providerSpec.toLowerCase()];
    if (defaultModel) {
      return defaultModel;
    }

    // Assume provider spec is already a model identifier
    return this.providerSpec;
  }

  async complete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
      outputSchema?: { schema: Record<string, unknown>; name: string };
    }
  ): Promise<LlmCompletionResponse> {
    const fullModel = this.resolveModel(model);
    const vendor = extractVendorFromModel(fullModel);
    const modelName = extractModelName(fullModel);

    if (!vendor) {
      throw new LLMAPIError(
        400,
        `Cannot determine vendor from model: ${fullModel}. Use format "vendor/model" (e.g., "anthropic/claude-sonnet-4-5")`,
        "vercel"
      );
    }

    // Load provider if not cached
    if (!this.providerLoadAttempted) {
      this.providerLoadAttempted = true;
      this.cachedProvider = await loadProvider(vendor);
    }

    if (!this.cachedProvider) {
      throw new LLMAPIError(
        500,
        `Vercel AI SDK provider for '${vendor}' not available. Install: npm install @ai-sdk/${vendor}`,
        "vercel"
      );
    }

    // Create the model instance
    const aiModel = this.cachedProvider(modelName);

    // Get vendor-specific handler for optimizations
    const handler = ProviderHandlerRegistry.getHandler(vendor);

    // Import generateText from ai package
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const aiModule = (await import("ai")) as any;
    const generateText = aiModule.generateText;
    const jsonSchema = aiModule.jsonSchema;
    const aiTool = aiModule.tool;

    // Convert tools to Vercel AI SDK format
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let vercelTools: Record<string, any> | undefined;
    if (tools && tools.length > 0) {
      vercelTools = {};
      for (const tool of tools) {
        const rawSchema = tool.function.parameters ?? {
          type: "object",
          properties: {},
        };
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { $schema, ...schemaWithoutMeta } = rawSchema as Record<
          string,
          unknown
        >;
        const cleanSchema = {
          type: "object",
          ...schemaWithoutMeta,
        };
        const proxy = this.toolProxies.get(tool.function.name);
        vercelTools[tool.function.name] = aiTool({
          description: tool.function.description ?? "",
          inputSchema: jsonSchema(cleanSchema),
          ...(proxy ? {
            execute: async (args: Record<string, unknown>) => {
              const result = await proxy(args);
              return typeof result === "string" ? result : JSON.stringify(result);
            },
          } : {}),
        });
      }
    }

    // Apply vendor-specific request preparation
    const preparedRequest = handler.prepareRequest(
      messages,
      null, // tools handled separately
      options?.outputSchema ?? null,
      {
        temperature: options?.temperature,
        maxOutputTokens: options?.maxOutputTokens,
        topP: options?.topP,
      }
    );

    // Build request options
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const requestOptions: Record<string, any> = {
      model: aiModel,
      messages: preparedRequest.messages,
    };

    if (vercelTools && Object.keys(vercelTools).length > 0) {
      requestOptions.tools = vercelTools;
      // When tool proxies are set, the SDK handles the agentic loop via execute callbacks.
      // maxSteps allows the SDK to call tools and feed results back to the LLM automatically.
      if (this.toolProxies.size > 0) {
        requestOptions.maxSteps = 10;
      }
    }

    if (options?.maxOutputTokens) {
      requestOptions.maxTokens = options.maxOutputTokens;
    }
    if (options?.temperature !== undefined) {
      requestOptions.temperature = options.temperature;
    }
    if (options?.topP !== undefined) {
      requestOptions.topP = options.topP;
    }

    try {
      const result = await generateText(requestOptions);

      // Convert Vercel AI SDK response to LlmCompletionResponse format.
      // When maxSteps is active, the SDK executed tools internally — don't
      // expose intermediate tool_calls to the consumer's outer loop.
      const sdkHandledLoop = requestOptions.maxSteps != null;
      const response: LlmCompletionResponse = {
        id: `vercel-${Date.now()}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: fullModel,
        choices: [
          {
            index: 0,
            message: {
              role: "assistant",
              content: result.text || null,
              tool_calls: sdkHandledLoop ? undefined : result.toolCalls?.map(
                (tc: { toolCallId: string; toolName: string; args: unknown }) => ({
                  id: tc.toolCallId,
                  type: "function" as const,
                  function: {
                    name: tc.toolName,
                    arguments: JSON.stringify(tc.args ?? {}),
                  },
                })
              ),
            },
            finish_reason: result.finishReason ?? "stop",
          },
        ],
        usage: {
          prompt_tokens: result.usage?.promptTokens ?? 0,
          completion_tokens: result.usage?.completionTokens ?? 0,
          total_tokens:
            (result.usage?.promptTokens ?? 0) +
            (result.usage?.completionTokens ?? 0),
        },
      };

      return response;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : String(error);
      throw new LLMAPIError(500, `Vercel AI SDK error: ${message}`, "vercel");
    }
  }
}

/**
 * Mesh provider that delegates to an LLM provider discovered via mesh.
 */
export class MeshDelegatedProvider implements LlmProvider {
  private endpoint: string;
  private functionName: string;
  private parallelToolCalls: boolean;

  constructor(endpoint: string, functionName: string, parallelToolCalls: boolean = false) {
    this.endpoint = endpoint;
    this.functionName = functionName;
    this.parallelToolCalls = parallelToolCalls;
  }

  async complete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
      // Issue #459: Output schema for provider to apply vendor-specific handling
      outputSchema?: { schema: Record<string, unknown>; name: string };
    }
  ): Promise<LlmCompletionResponse> {
    // Build MeshLlmRequest structure (matches Python claude_provider schema)
    const modelParams: Record<string, unknown> = {};
    // Only pass model if it's a real model name (not "default")
    if (model && model !== "default") {
      modelParams.model = model;
    }
    if (options?.maxOutputTokens) modelParams.max_tokens = options.maxOutputTokens;
    if (options?.temperature !== undefined) modelParams.temperature = options.temperature;
    if (options?.topP !== undefined) modelParams.top_p = options.topP;
    if (options?.stop) modelParams.stop = options.stop;
    // Issue #459: Include output_schema for provider to apply vendor-specific handling
    // (e.g., OpenAI/Gemini need response_format, Claude uses strict mode)
    if (options?.outputSchema) {
      modelParams.output_schema = options.outputSchema.schema;
      modelParams.output_type_name = options.outputSchema.name;
    }
    // Issue #713: Include parallel_tool_calls for provider-side parallel execution.
    // Provider handlers strip this from LLM API params (e.g., Claude doesn't accept it),
    // but the provider's agentic loop needs it to decide parallel vs sequential execution.
    if (this.parallelToolCalls) {
      modelParams.parallel_tool_calls = true;
    }

    const request: Record<string, unknown> = {
      messages,
    };
    // Only include model_params if there are params
    if (Object.keys(modelParams).length > 0) {
      request.model_params = modelParams;
    }

    if (tools && tools.length > 0) {
      request.tools = tools;
    }

    // Wrap in "request" parameter as expected by Python claude_provider
    const args: Record<string, unknown> = { request };

    // Set up timeout (default 300s to match Python SDK's stream_timeout)
    const timeoutMs = parseInt(process.env.MESH_PROVIDER_TIMEOUT_MS || "300000", 10);

    // Tracing: propagate context to downstream provider
    const traceCtx = getCurrentTraceContext();
    const traceSpanId = traceCtx ? generateSpanId() : null;
    const traceStartTime = Date.now() / 1000;

    // Inject trace context into args for fastmcp fallback
    if (traceCtx && traceSpanId) {
      args._trace_id = traceCtx.traceId;
      args._parent_span = traceSpanId;
    }
    // Inject propagated headers
    const delegatedPropHeaders = getCurrentPropagatedHeaders();
    if (Object.keys(delegatedPropHeaders).length > 0) {
      args._mesh_headers = { ...delegatedPropHeaders };
    }

    let traceSuccess = true;
    let traceError: string | null = null;

    try {
      // Call the mesh provider via MCP
      let response: Response;
      try {
        response = await fetchWithTimeout(`${this.endpoint}/mcp`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            ...(traceCtx && traceSpanId ? createTraceHeaders(traceCtx.traceId, traceSpanId) : {}),
            ...getCurrentPropagatedHeaders(),
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: Date.now(),
            method: "tools/call",
            params: {
              name: this.functionName,
              arguments: args,
            },
          }),
          timeout: timeoutMs,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          dispatcher: getDispatcher(`${this.endpoint}/mcp`) as any,
        });
      } catch (error) {
        if (isTimeoutError(error)) {
          throw new LLMAPIError(408, `Request timed out after ${timeoutMs}ms`, `mesh:${this.endpoint}`);
        }
        throw new LLMAPIError(0, `Fetch failed: ${error instanceof Error ? error.message : String(error)}`, `mesh:${this.endpoint}`);
      }

      if (!response.ok) {
        const error = await response.text();
        throw new LLMAPIError(response.status, error, `mesh:${this.endpoint}`);
      }

      // Handle SSE response from FastMCP stateless HTTP stream
      const responseText = await response.text();

      const result = parseSSEResponse<{
        error?: { message: string };
        result?: { content?: Array<{ type: string; text: string }> };
      }>(responseText);

      if (result.error) {
        throw new Error(`Mesh provider RPC error: ${result.error.message}`);
      }

      // Parse the MCP result content
      const content = result.result?.content?.[0];
      if (!content || content.type !== "text") {
        throw new Error("Invalid response from mesh provider");
      }

      // Check for MCP tool execution error (isError flag in result)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((result.result as any)?.isError) {
        throw new Error(`Mesh provider tool error: ${content.text}`);
      }

      // Parse the LLM provider response
      // Format: { role, content, tool_calls?, _mesh_usage? }
      const meshResponse = JSON.parse(content.text) as {
        role: string;
        content: string;
        tool_calls?: Array<{
          id: string;
          type: "function";
          function: { name: string; arguments: string };
        }>;
        _mesh_usage?: { prompt_tokens: number; completion_tokens: number };
      };

      // Validate role - LLM responses should always be "assistant"
      let validatedRole: "assistant" = "assistant";
      if (meshResponse.role !== "assistant") {
        console.warn(
          `[mesh.llm] Unexpected role "${meshResponse.role}" from mesh provider, defaulting to "assistant"`
        );
      }

      // Convert to OpenAI format expected by MeshLlmAgent
      const openAiResponse: LlmCompletionResponse = {
        id: `mesh-${Date.now()}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: "mesh-delegated",
        choices: [
          {
            index: 0,
            message: {
              role: validatedRole,
              content: meshResponse.content,
              tool_calls: meshResponse.tool_calls,
            },
            finish_reason: meshResponse.tool_calls ? "tool_calls" : "stop",
          },
        ],
        usage: meshResponse._mesh_usage
          ? {
              prompt_tokens: meshResponse._mesh_usage.prompt_tokens,
              completion_tokens: meshResponse._mesh_usage.completion_tokens,
              total_tokens:
                meshResponse._mesh_usage.prompt_tokens +
                meshResponse._mesh_usage.completion_tokens,
            }
          : undefined,
      };

      return openAiResponse;
    } catch (err) {
      traceSuccess = false;
      traceError = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      if (traceCtx && traceSpanId) {
        const traceEndTime = Date.now() / 1000;
        const traceDurationMs = (traceEndTime - traceStartTime) * 1000;
        publishTraceSpan({
          traceId: traceCtx.traceId,
          spanId: traceSpanId,
          parentSpan: traceCtx.parentSpanId,
          functionName: "proxy_call_wrapper",
          startTime: traceStartTime,
          endTime: traceEndTime,
          durationMs: traceDurationMs,
          success: traceSuccess,
          error: traceError,
          resultType: traceSuccess ? "object" : "error",
          argsCount: 0,
          kwargsCount: 0,
          dependencies: [this.endpoint],
          injectedDependencies: 0,
          meshPositions: [],
        }).catch(() => {});
      }
    }
  }
}

/**
 * MeshLlmAgent - The core agentic loop implementation.
 */
export class MeshLlmAgent<T = string> {
  private config: MeshLlmAgentConfig;
  private responseParser: ResponseParser<T>;
  private _meta: LlmMeta | null = null;
  private _systemPromptOverride: string | null = null;
  private _parallelLogEmitted = false;

  constructor(config: MeshLlmAgentConfig) {
    this.config = config;
    this.responseParser = new ResponseParser(config.returnSchema as ZodType<T> | undefined);
  }

  /**
   * Get metadata from the last run.
   */
  get meta(): LlmMeta | null {
    return this._meta;
  }

  /**
   * Override the system prompt at runtime.
   */
  setSystemPrompt(prompt: string): void {
    this._systemPromptOverride = prompt;
  }

  /**
   * Get the effective system prompt (override or config).
   */
  private getSystemPrompt(): string | undefined {
    return this._systemPromptOverride ?? this.config.systemPrompt;
  }

  /**
   * Run the agentic loop.
   *
   * @param messageInput - User message string or multi-turn message array
   * @param context - Runtime context with tools and options
   * @returns Parsed response (validated if schema provided)
   */
  async run(messageInput: LlmMessageInput, context: AgentRunContext): Promise<T> {
    if (this.config.parallelToolCalls && !this._parallelLogEmitted) {
      console.log("[mesh.llm] parallel tool calls enabled — tools will execute concurrently via Promise.all()");
      this._parallelLogEmitted = true;
    }
    const startTime = Date.now();
    const toolCalls: LlmToolCall[] = [];
    let totalInputTokens = 0;
    let totalOutputTokens = 0;

    // Resolve provider
    const provider = this.resolveProvider(context);

    // Build initial messages
    const messages: LlmMessage[] = [];

    // Build tool definitions first (needed for schema injection)
    // When using mesh delegation, enrich tools with endpoint URLs
    // so the provider can execute tools directly via MCP proxies
    const isMeshDelegated = !!context.meshProvider;
    const toolDefs = this.buildToolDefinitions(context.tools, isMeshDelegated);

    // Add system prompt if configured
    const systemPromptTemplate = this.getSystemPrompt();
    if (systemPromptTemplate) {
      let systemContent = await renderTemplate(
        systemPromptTemplate,
        context.templateContext ?? {}
      );

      // Inject tool schemas into system prompt (Python parity feature)
      if (toolDefs.length > 0) {
        const toolSchemaSection = this.buildToolSchemaSection(toolDefs);
        systemContent += toolSchemaSection;
      }

      // Inject output schema hint if using "hint" or "strict" mode with a schema.
      // Skip for mesh delegation — the provider's handler applies vendor-specific
      // formatting via output_schema in model_params. Consumer doesn't know
      // the provider's vendor, so it must not add vendor-agnostic schema instructions.
      const outputMode = this.config.outputMode ?? "hint";
      if (!context.meshProvider && outputMode !== "text" && this.config.returnSchema) {
        const outputSchemaSection = this.buildOutputSchemaSection();
        systemContent += outputSchemaSection;
      }

      messages.push({ role: "system", content: systemContent });
    }

    // Resolve media inputs if provided (URIs and/or inline buffers -> image_url parts)
    const mediaItems = context.options?.media;
    let mediaParts: Array<{ type: string; [key: string]: unknown }> | null = null;
    if (mediaItems && mediaItems.length > 0) {
      mediaParts = await resolveMediaInputs(mediaItems);
    }

    // Handle multi-turn conversation input
    if (typeof messageInput === "string") {
      if (mediaParts && mediaParts.length > 0) {
        // Multipart user message: text + image(s)
        messages.push({
          role: "user",
          content: [
            { type: "text", text: messageInput },
            ...mediaParts,
          ] as LlmContentPart[],
        });
      } else {
        // Simple string - add as user message
        messages.push({ role: "user", content: messageInput });
      }
    } else {
      // Array of messages - add all; attach media to the last user message
      for (let i = 0; i < messageInput.length; i++) {
        const msg = messageInput[i];
        const isLastUser =
          mediaParts &&
          mediaParts.length > 0 &&
          msg.role === "user" &&
          i === messageInput.length - 1;

        if (isLastUser) {
          messages.push({
            role: "user",
            content: [
              { type: "text", text: msg.content },
              ...mediaParts!,
            ] as LlmContentPart[],
          });
        } else {
          messages.push({ role: msg.role, content: msg.content });
        }
      }
    }

    // Get effective options (runtime options > MESH_LLM_* env > config)
    const maxIterations =
      context.options?.maxIterations ??
      (process.env.MESH_LLM_MAX_ITERATIONS
        ? parseInt(process.env.MESH_LLM_MAX_ITERATIONS, 10)
        : this.config.maxIterations);
    const maxTokens = context.options?.maxOutputTokens ?? this.config.maxOutputTokens;
    const temperature = context.options?.temperature ?? this.config.temperature;

    // Determine model (mesh provider > MESH_LLM_MODEL env > config > default)
    const model =
      context.meshProvider?.model ??
      process.env.MESH_LLM_MODEL ??
      this.config.model ??
      this.getDefaultModel();

    // Build output schema for provider (Issue #459) - computed once before loop
    let outputSchema: { schema: Record<string, unknown>; name: string } | undefined;
    if (this.config.returnSchema) {
      try {
        const jsonSchema = zodToJsonSchema(this.config.returnSchema) as Record<string, unknown>;
        // Extract schema name from title or use generic name
        const schemaName = (jsonSchema.title as string) ?? "Response";
        outputSchema = { schema: jsonSchema, name: schemaName };
      } catch {
        // If schema conversion fails, skip
      }
    }

    // Set tool proxies on direct-mode providers so the Vercel AI SDK
    // can execute tools internally via maxSteps (agentic loop in the SDK).
    if (provider instanceof VercelDirectProvider && context.tools.length > 0) {
      provider.setToolProxies(context.tools);
    }

    // Agentic loop
    let iteration = 0;
    let finalContent: string = "";

    while (iteration < maxIterations) {
      iteration++;

      // Call LLM
      const response = await provider.complete(
        model,
        messages,
        toolDefs.length > 0 ? toolDefs : undefined,
        { maxOutputTokens: maxTokens, temperature, topP: this.config.topP, stop: this.config.stop, outputSchema }
      );

      // Track tokens
      if (response.usage) {
        totalInputTokens += response.usage.prompt_tokens;
        totalOutputTokens += response.usage.completion_tokens;
      }

      const choice = response.choices[0];
      if (!choice) {
        throw new Error("No response from LLM");
      }

      const assistantMessage = choice.message;

      // Add assistant message to history
      messages.push(assistantMessage);

      // Check for tool calls
      if (assistantMessage.tool_calls && assistantMessage.tool_calls.length > 0) {
        console.log(`[mesh.llm] LLM requested ${assistantMessage.tool_calls.length} tool calls`);

        if (this.config.parallelToolCalls && assistantMessage.tool_calls.length > 1) {
          // Parallel execution via Promise.all()
          console.log(`[mesh.llm] Executing ${assistantMessage.tool_calls.length} tool calls in parallel`);
          const toolResultPromises = assistantMessage.tool_calls.map(async (toolCall) => {
            try {
              const toolResult = await this.executeToolCall(toolCall, context.tools, toolCalls);
              return {
                role: "tool" as const,
                content: typeof toolResult === "string" ? toolResult : JSON.stringify(toolResult),
                tool_call_id: toolCall.id,
                name: toolCall.function.name,
              };
            } catch (err) {
              console.error(`[mesh.llm] Parallel tool call failed for ${toolCall.function.name}: ${err}`);
              return {
                role: "tool" as const,
                content: JSON.stringify({ error: err instanceof Error ? err.message : String(err) }),
                tool_call_id: toolCall.id,
                name: toolCall.function.name,
              };
            }
          });

          const toolResults = await Promise.all(toolResultPromises);
          for (const result of toolResults) {
            messages.push(result);
          }
        } else {
          // Sequential execution (default)
          for (const toolCall of assistantMessage.tool_calls) {
            const toolResult = await this.executeToolCall(toolCall, context.tools, toolCalls);

            // Add tool result to messages
            messages.push({
              role: "tool",
              content: typeof toolResult === "string" ? toolResult : JSON.stringify(toolResult),
              tool_call_id: toolCall.id,
              name: toolCall.function.name,
            });
          }
        }

        // Continue loop to get next response
        continue;
      }

      // No tool calls - this is the final response
      // Assistant content is always a string (multipart arrays are only for user messages)
      finalContent = typeof assistantMessage.content === "string"
        ? assistantMessage.content
        : "";
      break;
    }

    // Check if we exhausted iterations without completing
    if (iteration >= maxIterations && finalContent === "") {
      const lastMessage = messages[messages.length - 1];
      throw new MaxIterationsError(iteration, lastMessage, messages);
    }

    // Store metadata
    const endTime = Date.now();
    this._meta = {
      inputTokens: totalInputTokens,
      outputTokens: totalOutputTokens,
      totalTokens: totalInputTokens + totalOutputTokens,
      latencyMs: endTime - startTime,
      iterations: iteration,
      toolCalls,
      model,
      provider: this.getProviderName(context),
    };

    // Parse and validate response
    return this.responseParser.parse(finalContent);
  }

  /**
   * Create a callable LlmAgent interface.
   */
  createCallable(context: AgentRunContext): {
    (message: LlmMessageInput, options?: LlmCallOptions): Promise<T>;
    readonly meta: LlmMeta | null;
    readonly tools: LlmToolProxy[];
    setSystemPrompt(prompt: string): void;
  } {
    const agent = this;

    const callable = async (message: LlmMessageInput, options?: LlmCallOptions): Promise<T> => {
      // Handle context mode
      const contextMode: LlmContextMode = options?.contextMode ?? "merge";
      let mergedTemplateContext: Record<string, unknown>;

      if (contextMode === "replace" && options?.context) {
        // Replace mode - use only the runtime context
        mergedTemplateContext = options.context;
      } else if (options?.context) {
        // Merge mode (default) - combine base and runtime context
        mergedTemplateContext = { ...context.templateContext, ...options.context };
      } else {
        // No runtime context - use base context
        mergedTemplateContext = context.templateContext ?? {};
      }

      // Merge options
      const mergedContext: AgentRunContext = {
        ...context,
        options: options ? { ...context.options, ...options } : context.options,
        templateContext: mergedTemplateContext,
      };

      return agent.run(message, mergedContext);
    };

    // Attach meta property
    Object.defineProperty(callable, "meta", {
      get: () => agent.meta,
    });

    // Attach tools property
    Object.defineProperty(callable, "tools", {
      get: () => context.tools,
    });

    // Attach setSystemPrompt method
    Object.defineProperty(callable, "setSystemPrompt", {
      value: (prompt: string) => agent.setSystemPrompt(prompt),
    });

    return callable as {
      (message: LlmMessageInput, options?: LlmCallOptions): Promise<T>;
      readonly meta: LlmMeta | null;
      readonly tools: LlmToolProxy[];
      setSystemPrompt(prompt: string): void;
    };
  }

  /**
   * Resolve the LLM provider to use.
   *
   * Configuration Hierarchy (ENV > Config):
   * - MESH_LLM_PROVIDER: Override provider (only for direct mode, not mesh delegation)
   */
  private resolveProvider(context: AgentRunContext): LlmProvider {
    // If mesh provider is resolved, use it (mesh delegation)
    if (context.meshProvider) {
      return new MeshDelegatedProvider(
        context.meshProvider.endpoint,
        context.meshProvider.functionName,
        this.config.parallelToolCalls ?? false
      );
    }

    // Use direct Vercel AI SDK provider
    // Check env var override first (only for string provider, not mesh delegation object)
    let providerSpec: string;
    if (typeof this.config.provider === "string") {
      providerSpec =
        process.env.MESH_LLM_PROVIDER || this.config.provider || "claude";
    } else {
      providerSpec = "claude"; // fallback default for non-mesh object config
    }
    return new VercelDirectProvider(providerSpec);
  }

  /**
   * Get provider name for metadata.
   */
  private getProviderName(context: AgentRunContext): string {
    if (context.meshProvider) {
      return `mesh:${context.meshProvider.endpoint}`;
    }

    if (typeof this.config.provider === "string") {
      // Return env var override if set, otherwise config value
      return process.env.MESH_LLM_PROVIDER || this.config.provider;
    }

    return `mesh:${this.config.provider.capability}`;
  }

  /**
   * Get default model based on provider.
   */
  private getDefaultModel(): string {
    const provider = this.config.provider;

    if (typeof provider === "string") {
      // Map common provider names to models
      const defaultModels: Record<string, string> = {
        claude: "anthropic/claude-sonnet-4-5",
        openai: "gpt-4o",
        anthropic: "anthropic/claude-sonnet-4-5",
        gpt4: "gpt-4o",
        gpt35: "gpt-3.5-turbo",
      };

      return defaultModels[provider.toLowerCase()] ?? provider;
    }

    // Mesh delegation - model will be determined by the provider
    return "default";
  }

  /**
   * Build tool definitions from proxies.
   * When isMeshDelegated is true, enriches each tool with _mesh_endpoint
   * so the provider can execute tools directly via MCP proxies.
   */
  private buildToolDefinitions(tools: LlmToolProxy[], isMeshDelegated = false): LlmToolDefinition[] {
    return tools.map((tool) => {
      const rawSchema = (tool.inputSchema ?? { type: "object", properties: {} }) as Record<string, unknown>;
      const funcDef: Record<string, unknown> = {
        name: tool.name,
        description: tool.description,
        parameters: { type: "object", ...rawSchema },
      };
      if (isMeshDelegated && tool.endpoint) {
        funcDef._mesh_endpoint = tool.endpoint;
      }
      return {
        type: "function" as const,
        function: funcDef as LlmToolDefinition["function"],
      };
    });
  }

  /**
   * Build tool schema section for system prompt injection.
   * Helps the LLM understand available tools and their schemas.
   */
  private buildToolSchemaSection(tools: LlmToolDefinition[]): string {
    if (tools.length === 0) return "";

    const toolDescriptions = tools.map((tool) => {
      const fn = tool.function;
      const schemaStr = fn.parameters
        ? JSON.stringify(fn.parameters, null, 2)
        : "{}";
      return `### ${fn.name}\n${fn.description ?? "No description"}\n\nInput Schema:\n\`\`\`json\n${schemaStr}\n\`\`\``;
    });

    return `\n\n## Available Tools\n\nYou have access to the following tools:\n\n${toolDescriptions.join("\n\n")}`;
  }

  /**
   * Build output schema section for system prompt injection.
   * Guides the LLM to produce structured output matching the schema.
   */
  private buildOutputSchemaSection(): string {
    if (!this.config.returnSchema) return "";

    try {
      const jsonSchema = zodToJsonSchema(this.config.returnSchema);
      const schemaStr = JSON.stringify(jsonSchema, null, 2);

      return `\n\n## Output Format\n\nYour response MUST be valid JSON matching this schema:\n\n\`\`\`json\n${schemaStr}\n\`\`\`\n\nRespond ONLY with the JSON object, no additional text.`;
    } catch {
      // If schema conversion fails, skip injection
      return "";
    }
  }

  /**
   * Execute a tool call and record metadata.
   */
  private async executeToolCall(
    toolCall: LlmToolCallRequest,
    tools: LlmToolProxy[],
    toolCallRecords: LlmToolCall[]
  ): Promise<unknown> {
    const toolName = toolCall.function.name;
    const tool = tools.find((t) => t.name === toolName);

    const startTime = Date.now();
    let args: Record<string, unknown> = {};
    let result: unknown;
    let success = true;
    let error: string | undefined;

    try {
      // Parse arguments
      args = JSON.parse(toolCall.function.arguments);

      if (!tool) {
        throw new Error(`Tool not found: ${toolName}`);
      }

      // Execute tool
      result = await tool(args);
    } catch (err) {
      success = false;
      error = err instanceof Error ? err.message : String(err);
      result = { error };
    }

    const endTime = Date.now();

    // Record tool call
    toolCallRecords.push({
      name: toolName,
      args,
      result,
      success,
      error,
      latencyMs: endTime - startTime,
    });

    return result;
  }
}

/**
 * Create a tool proxy from resolved tool info.
 */
export function createLlmToolProxy(
  toolInfo: {
    functionName: string;
    capability: string;
    endpoint: string;
    agentId: string;
    inputSchema?: string;
  },
  description?: string
): LlmToolProxy {
  const proxy = async (args: Record<string, unknown>): Promise<unknown> => {
    // Set up timeout (default 30s for tool calls)
    const timeoutMs = parseInt(process.env.MESH_TOOL_TIMEOUT_MS || "30000", 10);

    // Tracing: propagate context to downstream tool
    const traceCtx = getCurrentTraceContext();
    const traceSpanId = traceCtx ? generateSpanId() : null;
    const traceStartTime = Date.now() / 1000;

    let traceSuccess = true;
    let traceError: string | null = null;
    let resultType = "unknown";

    try {
      // Make MCP call to the tool
      let response: Response;
      try {
        response = await fetchWithTimeout(`${toolInfo.endpoint}/mcp`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            ...(traceCtx && traceSpanId ? createTraceHeaders(traceCtx.traceId, traceSpanId) : {}),
            ...getCurrentPropagatedHeaders(),
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: Date.now(),
            method: "tools/call",
            params: {
              name: toolInfo.functionName,
              arguments: {
                ...args,
                ...(traceCtx && traceSpanId ? { _trace_id: traceCtx.traceId, _parent_span: traceSpanId } : {}),
                ...(Object.keys(getCurrentPropagatedHeaders()).length > 0 ? { _mesh_headers: getCurrentPropagatedHeaders() } : {}),
              },
            },
          }),
          timeout: timeoutMs,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          dispatcher: getDispatcher(`${toolInfo.endpoint}/mcp`) as any,
        });
      } catch (error) {
        if (isTimeoutError(error)) {
          throw new ToolExecutionError(
            toolInfo.functionName,
            new Error(`Tool call timed out after ${timeoutMs}ms (endpoint: ${toolInfo.endpoint})`)
          );
        }
        throw new ToolExecutionError(
          toolInfo.functionName,
          error instanceof Error ? error : new Error(String(error))
        );
      }

      if (!response.ok) {
        const errorBody = await response.text();
        throw new ToolExecutionError(
          toolInfo.functionName,
          new Error(`Tool call failed: ${response.status} ${errorBody}`)
        );
      }

      // Handle SSE response from FastMCP stateless HTTP stream
      const responseText = await response.text();

      const result = parseSSEResponse<{
        error?: { message: string };
        result?: { content?: Array<{ type: string; text?: string }> };
      }>(responseText);

      if (result.error) {
        throw new Error(`Tool error: ${result.error.message}`);
      }

      // Parse result content
      const content = result.result?.content?.[0];
      if (!content) {
        resultType = "null";
        return null;
      }

      if (content.type === "text" && content.text) {
        // Try to parse as JSON
        try {
          const parsed = JSON.parse(content.text);
          resultType = typeof parsed;
          return parsed;
        } catch {
          resultType = "string";
          return content.text;
        }
      }

      resultType = typeof content;
      return content;
    } catch (err) {
      traceSuccess = false;
      traceError = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      if (traceCtx && traceSpanId) {
        const traceEndTime = Date.now() / 1000;
        const traceDurationMs = (traceEndTime - traceStartTime) * 1000;
        publishTraceSpan({
          traceId: traceCtx.traceId,
          spanId: traceSpanId,
          parentSpan: traceCtx.parentSpanId,
          functionName: "proxy_call_wrapper",
          startTime: traceStartTime,
          endTime: traceEndTime,
          durationMs: traceDurationMs,
          success: traceSuccess,
          error: traceError,
          resultType: traceSuccess ? resultType : "error",
          argsCount: 0,
          kwargsCount: 0,
          dependencies: [toolInfo.endpoint],
          injectedDependencies: 0,
          meshPositions: [],
        }).catch(() => {});
      }
    }
  };

  // Safely parse inputSchema - don't let malformed JSON break proxy creation
  let parsedInputSchema: unknown;
  if (toolInfo.inputSchema) {
    try {
      parsedInputSchema = JSON.parse(toolInfo.inputSchema);
    } catch (error) {
      console.warn(
        `[mesh.llm] Failed to parse inputSchema for tool "${toolInfo.functionName}": ${error instanceof Error ? error.message : String(error)}`
      );
      parsedInputSchema = undefined;
    }
  }

  // Attach metadata using defineProperties to override read-only 'name'
  Object.defineProperties(proxy, {
    name: {
      value: toolInfo.functionName,
      writable: false,
      configurable: true,
    },
    capability: {
      value: toolInfo.capability,
      writable: false,
      configurable: true,
    },
    description: {
      value: description,
      writable: false,
      configurable: true,
    },
    inputSchema: {
      value: parsedInputSchema,
      writable: false,
      configurable: true,
    },
    endpoint: {
      value: toolInfo.endpoint,
      writable: false,
      configurable: true,
    },
    agentId: {
      value: toolInfo.agentId,
      writable: false,
      configurable: true,
    },
  });

  return proxy as LlmToolProxy;
}
