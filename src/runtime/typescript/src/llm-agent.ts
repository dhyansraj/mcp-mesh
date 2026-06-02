/**
 * MeshLlmAgent - Agentic loop implementation for LLM-powered tools.
 *
 * This class handles:
 * - System prompt rendering (with Handlebars templates)
 * - Agentic loop with tool execution
 * - LLM provider calls via mesh delegation
 * - Response parsing with Zod validation
 * - Metadata tracking (tokens, latency, tool calls)
 *
 * Configuration Hierarchy (ENV > Config):
 * - MESH_LLM_MODEL: Override model (e.g., "gpt-4o", "gemini-2.5-flash")
 * - MESH_LLM_MAX_ITERATIONS: Override max agentic loop iterations
 *
 * @example
 * ```typescript
 * const agent = new MeshLlmAgent({
 *   provider: { capability: "llm", tags: ["+claude"] },
 *   model: "anthropic/claude-sonnet-4-5",
 *   systemPrompt: "file://prompts/assistant.hbs",
 *   maxIterations: 10,
 *   returnSchema: ResponseSchema,
 * });
 *
 * const result = await agent.run("Help me calculate 2+2", {
 *   templateContext: { user: "John" },
 *   tools: resolvedToolProxies,
 *   meshProvider: { endpoint: "http://provider:9000", functionName: "process_chat" },
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
import { resolveMediaInputs } from "./media/index.js";
import {
  getCurrentTraceContext,
  getCurrentPropagatedHeaders,
  streamMcpTool,
  DEFAULT_CALL_OPTIONS,
} from "./proxy.js";
import {
  generateSpanId,
  publishTraceSpan,
  createTraceHeaders,
  injectTraceAndHeaders,
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
      // Issue #1019: escape-hatch for vendor-specific kwargs not exposed by the
      // typed option surface (e.g., thinking_config, output_config, reasoning_effort).
      modelParams?: Record<string, unknown>;
    }
  ): Promise<LlmCompletionResponse>;
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

  /**
   * Build the MeshLlmRequest body shared by complete() and streamComplete().
   *
   * Assembles model_params (with the escape-hatch merge + typed overrides),
   * wraps messages/tools into the MeshLlmRequest, and returns it pre-wrapped
   * in the ``{ request }`` arguments object. Callers inject trace context /
   * propagated headers into ``args`` afterward (per-caller — complete() uses
   * injectTraceAndHeaders, streamComplete() lets streamMcpTool() handle it).
   */
  private buildMeshLlmRequest(
    model: string,
    messages: LlmMessage[],
    tools: LlmToolDefinition[] | undefined,
    options:
      | {
          maxOutputTokens?: number;
          temperature?: number;
          topP?: number;
          stop?: string[];
          outputSchema?: { schema: Record<string, unknown>; name: string };
          modelParams?: Record<string, unknown>;
        }
      | undefined
  ): { request: Record<string, unknown>; args: Record<string, unknown> } {
    const modelParams: Record<string, unknown> = {};
    // Escape-hatch merge: callers can pass vendor-specific kwargs
    // (e.g., thinking_config, output_config) via options.modelParams.
    // Merged FIRST so typed fields below take precedence on collision.
    if (options?.modelParams) {
      Object.assign(modelParams, options.modelParams);
    }
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

    return { request, args };
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
      // Issue #1019: escape-hatch for vendor-specific kwargs not exposed by the
      // typed option surface (e.g., thinking_config, output_config, reasoning_effort).
      modelParams?: Record<string, unknown>;
    }
  ): Promise<LlmCompletionResponse> {
    // Build MeshLlmRequest structure (matches Python claude_provider schema).
    let { args } = this.buildMeshLlmRequest(model, messages, tools, options);

    // Set up timeout (default 300s to match Python SDK's stream_timeout)
    const timeoutMs = parseInt(process.env.MESH_PROVIDER_TIMEOUT_MS || "300000", 10);

    // Tracing: propagate context to downstream provider
    const traceCtx = getCurrentTraceContext();
    const traceSpanId = traceCtx ? generateSpanId() : null;
    const traceStartTime = Date.now() / 1000;

    // Inject trace context and propagated headers into args (Rust core,
    // manual fallback). Returns a NEW merged object; reassign so the
    // downstream `arguments: args` send picks up the injected fields.
    const delegatedPropHeaders = getCurrentPropagatedHeaders();
    args = injectTraceAndHeaders(args, traceCtx, traceSpanId, delegatedPropHeaders);

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

  /**
   * Stream chunks from the mesh-delegated provider's streaming variant.
   *
   * Builds the same ``{request: <MeshLlmRequest>}`` body that ``complete()``
   * produces, then calls the streaming MCP tool via ``streamMcpTool()`` from
   * ``./proxy``. Each ``notifications/progress`` chunk is yielded as a string;
   * the final ``result`` event ends the stream and is NOT yielded (matches the
   * Python ``MeshLlmAgent.stream()`` contract).
   *
   * The provider's ``functionName`` is expected to already be the streaming
   * variant — the registry resolver picks it based on the consumer's
   * ``ai.mcpmesh.stream`` tag opt-in (see ``MeshLlmAgent.stream()``).
   */
  async *streamComplete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
      outputSchema?: { schema: Record<string, unknown>; name: string };
      // Issue #1019: escape-hatch for vendor-specific kwargs not exposed by the
      // typed option surface (e.g., thinking_config, output_config, reasoning_effort).
      modelParams?: Record<string, unknown>;
    }
  ): AsyncGenerator<string, void, void> {
    // Build MeshLlmRequest body — same shape as complete().
    const { args } = this.buildMeshLlmRequest(model, messages, tools, options);

    // streamMcpTool() handles trace context injection / propagated headers /
    // dispatcher pooling internally — same path as createProxy().stream().
    // Match complete()'s env-backed timeout (MESH_PROVIDER_TIMEOUT_MS) so
    // operators can tune both buffered and streaming provider calls with
    // the same knob. Default 300s (matches Python SDK's stream_timeout).
    const providerTimeoutMs = parseInt(
      process.env.MESH_PROVIDER_TIMEOUT_MS || "300000",
      10,
    );
    const streamOptions = {
      ...DEFAULT_CALL_OPTIONS,
      timeout: providerTimeoutMs,
      streamTimeout: providerTimeoutMs,
    };

    yield* streamMcpTool(
      this.endpoint,
      this.functionName,
      args,
      streamOptions,
      "mesh-llm-stream",
    );
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
  // Cached output schema derived from the immutable returnSchema (Issue #459).
  // Computed once: `null` means "not yet computed", an object holds the result
  // (which may itself be `undefined` when conversion failed).
  private _outputSchema: { schema: Record<string, unknown>; name: string } | undefined | null = null;
  private _outputSchemaSection: string | null = null;

  constructor(config: MeshLlmAgentConfig) {
    this.config = config;
    this.responseParser = new ResponseParser(config.returnSchema as ZodType<T> | undefined);
  }

  /**
   * Build (once) the provider output schema from the immutable returnSchema.
   * Returns `undefined` when there is no schema or conversion failed.
   */
  private getOutputSchema(): { schema: Record<string, unknown>; name: string } | undefined {
    if (this._outputSchema !== null) return this._outputSchema;
    let result: { schema: Record<string, unknown>; name: string } | undefined;
    if (this.config.returnSchema) {
      try {
        const jsonSchema = zodToJsonSchema(this.config.returnSchema) as Record<string, unknown>;
        const schemaName = (jsonSchema.title as string) ?? "Response";
        result = { schema: jsonSchema, name: schemaName };
      } catch {
        // If schema conversion fails, skip
      }
    }
    this._outputSchema = result;
    return result;
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
   * Build the initial LlmMessage[] shared by run() and stream():
   * render the system prompt (+ tool schema injection), optionally append the
   * output-schema hint, resolve media inputs, and unwind multi-turn history
   * (attaching resolved media to the last user message).
   *
   * The ONLY behavioral knob is opts.includeOutputSchemaHint:
   * - run() passes `!meshDelegated` (consumer-side schema hint when not delegated).
   * - stream() passes `false` (always mesh-delegated; provider applies formatting).
   */
  private async buildAgentMessages(
    messageInput: LlmMessageInput,
    context: AgentRunContext,
    opts: { includeOutputSchemaHint: boolean }
  ): Promise<LlmMessage[]> {
    const messages: LlmMessage[] = [];

    // Build tool definitions first (needed for schema injection).
    // When using mesh delegation, enrich tools with endpoint URLs
    // so the provider can execute tools directly via MCP proxies.
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
      if (opts.includeOutputSchemaHint && outputMode !== "text" && this.config.returnSchema) {
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

    return messages;
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

    // Build tool definitions (needed for schema injection + the agentic loop).
    // When using mesh delegation, enrich tools with endpoint URLs
    // so the provider can execute tools directly via MCP proxies.
    const isMeshDelegated = !!context.meshProvider;
    const toolDefs = this.buildToolDefinitions(context.tools, isMeshDelegated);

    // Build initial messages (system prompt + tool schema + output-schema hint
    // + resolved media + multi-turn unwinding). run() includes the output-schema
    // hint only when NOT mesh-delegated.
    const messages = await this.buildAgentMessages(messageInput, context, {
      includeOutputSchemaHint: !isMeshDelegated,
    });

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

    // Build output schema for provider (Issue #459) - computed once, cached
    const outputSchema = this.getOutputSchema();

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
        {
          maxOutputTokens: maxTokens,
          temperature,
          topP: this.config.topP,
          stop: this.config.stop,
          outputSchema,
          // Issue #1019: forward caller-supplied escape-hatch kwargs
          modelParams: context.options?.modelParams,
        }
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
   * Stream the final assistant text token-by-token from a mesh-delegated
   * provider's streaming variant (Python's ``@mesh.llm_provider`` auto-
   * generates a ``process_chat_stream`` MCP tool tagged
   * ``ai.mcpmesh.stream``).
   *
   * **Tag opt-in (REQUIRED):** Unlike Python's ``@mesh.llm`` which auto-adds
   * the ``ai.mcpmesh.stream`` tag based on the function's return-type
   * (``Stream[str]`` vs ``str``), TypeScript users must EXPLICITLY include
   * ``"ai.mcpmesh.stream"`` in their provider tag filter to get the
   * streaming variant of the LLM provider:
   *
   * ```ts
   * server.addTool(mesh.llm({
   *   name: "chat_stream",
   *   provider: { capability: "llm", tags: ["+claude", "ai.mcpmesh.stream"] },
   *   // ...
   *   execute: async ({ message }, { llm }) => {
   *     for await (const chunk of llm.stream(message)) {
   *       process.stdout.write(chunk);
   *     }
   *     return llm.meta?.outputTokens ? "ok" : "no-output";
   *   },
   * }));
   * ```
   *
   * Without the ``ai.mcpmesh.stream`` tag the resolver returns the
   * buffered ``process_chat`` tool, and ``stream()`` will yield zero chunks
   * (the buffered tool emits no progress notifications).
   *
   * @param messageInput - User message string or multi-turn message array
   * @param context - Runtime context with tools, mesh provider, and options
   * @returns AsyncIterable yielding text chunks as the provider emits them
   */
  async *stream(
    messageInput: LlmMessageInput,
    context: AgentRunContext
  ): AsyncGenerator<string, void, void> {
    if (!context.meshProvider) {
      throw new Error(
        "MeshLlmAgent.stream() requires a mesh-delegated provider. " +
          "Configure your agent with provider: { capability: 'llm', tags: ['ai.mcpmesh.stream'] } " +
          "to use a streaming @mesh.llm_provider."
      );
    }

    // Build the same message list complete()/run() builds (system prompt,
    // multipart media, multi-turn array unwinding) — without the agentic
    // loop. The mesh-delegated streaming provider runs its own loop on the
    // server side and emits text chunks via notifications/progress; the
    // consumer just yields each one.

    // Mesh-delegated by definition (we required meshProvider above).
    const toolDefs = this.buildToolDefinitions(context.tools, true);

    // Build initial messages (system prompt + tool schema + resolved media +
    // multi-turn unwinding). stream() NEVER includes the output-schema hint —
    // the provider applies vendor-specific output formatting.
    const messages = await this.buildAgentMessages(messageInput, context, {
      includeOutputSchemaHint: false,
    });

    // Effective options (runtime > env > config)
    const maxTokens = context.options?.maxOutputTokens ?? this.config.maxOutputTokens;
    const temperature = context.options?.temperature ?? this.config.temperature;

    const model =
      context.meshProvider?.model ??
      process.env.MESH_LLM_MODEL ??
      this.config.model ??
      this.getDefaultModel();

    const outputSchema = this.getOutputSchema();

    const provider = new MeshDelegatedProvider(
      context.meshProvider.endpoint,
      context.meshProvider.functionName,
      this.config.parallelToolCalls ?? false,
    );

    yield* provider.streamComplete(
      model,
      messages,
      toolDefs.length > 0 ? toolDefs : undefined,
      {
        maxOutputTokens: maxTokens,
        temperature,
        topP: this.config.topP,
        stop: this.config.stop,
        outputSchema,
        // Issue #1019: forward caller-supplied escape-hatch kwargs
        modelParams: context.options?.modelParams,
      },
    );
  }

  /**
   * Create a callable LlmAgent interface.
   */
  createCallable(context: AgentRunContext): {
    (message: LlmMessageInput, options?: LlmCallOptions): Promise<T>;
    readonly meta: LlmMeta | null;
    readonly tools: LlmToolProxy[];
    setSystemPrompt(prompt: string): void;
    stream(message: LlmMessageInput, options?: LlmCallOptions): AsyncIterable<string>;
  } {
    const agent = this;

    // Shared "context merge vs replace" semantics used by both the buffered
    // callable and the stream method below.
    const mergeRunContext = (options?: LlmCallOptions): AgentRunContext => {
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

      return {
        ...context,
        options: options ? { ...context.options, ...options } : context.options,
        templateContext: mergedTemplateContext,
      };
    };

    const callable = async (message: LlmMessageInput, options?: LlmCallOptions): Promise<T> => {
      return agent.run(message, mergeRunContext(options));
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

    // Attach stream method — async iterable for token-by-token output.
    // Mirrors the callable's option-merging semantics so users get the same
    // "context merge vs replace" behavior as the buffered call.
    Object.defineProperty(callable, "stream", {
      value: (message: LlmMessageInput, options?: LlmCallOptions): AsyncIterable<string> => {
        return agent.stream(message, mergeRunContext(options));
      },
    });

    return callable as {
      (message: LlmMessageInput, options?: LlmCallOptions): Promise<T>;
      readonly meta: LlmMeta | null;
      readonly tools: LlmToolProxy[];
      setSystemPrompt(prompt: string): void;
      stream(message: LlmMessageInput, options?: LlmCallOptions): AsyncIterable<string>;
    };
  }

  /**
   * Resolve the LLM provider to use.
   *
   * Mesh delegation only — a resolved meshProvider is required.
   */
  private resolveProvider(context: AgentRunContext): LlmProvider {
    if (!context.meshProvider) {
      throw new Error(
        "MeshLlmAgent requires a mesh-delegated provider. " +
          "Configure your agent with provider: { capability: 'llm', tags: ['+claude'] } " +
          "and ensure a matching @mesh.llm_provider is registered in the mesh."
      );
    }
    return new MeshDelegatedProvider(
      context.meshProvider.endpoint,
      context.meshProvider.functionName,
      this.config.parallelToolCalls ?? false
    );
  }

  /**
   * Get provider name for metadata.
   */
  private getProviderName(context: AgentRunContext): string {
    if (context.meshProvider) {
      return `mesh:${context.meshProvider.endpoint}`;
    }
    return `mesh:${this.config.provider.capability}`;
  }

  /**
   * Get default model — mesh delegation defers model selection to the provider.
   */
  private getDefaultModel(): string {
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
    if (this._outputSchemaSection !== null) return this._outputSchemaSection;

    const cached = this.getOutputSchema();
    if (!cached) {
      this._outputSchemaSection = "";
      return "";
    }

    const schemaStr = JSON.stringify(cached.schema, null, 2);
    this._outputSchemaSection = `\n\n## Output Format\n\nYour response MUST be valid JSON matching this schema:\n\n\`\`\`json\n${schemaStr}\n\`\`\`\n\nRespond ONLY with the JSON object, no additional text.`;
    return this._outputSchemaSection;
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

    // Build arguments with trace context injection (Rust core, manual fallback)
    const toolPropHeaders = getCurrentPropagatedHeaders();
    const toolArgsWithTrace = injectTraceAndHeaders(args, traceCtx, traceSpanId, toolPropHeaders);

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
            ...toolPropHeaders,
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: Date.now(),
            method: "tools/call",
            params: {
              name: toolInfo.functionName,
              arguments: toolArgsWithTrace,
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
