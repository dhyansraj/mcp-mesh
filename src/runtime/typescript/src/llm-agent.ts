/**
 * MeshLlmAgent - Agentic loop implementation for LLM-powered tools.
 *
 * This class handles:
 * - System prompt rendering (with Handlebars templates)
 * - Agentic loop with tool execution
 * - LLM provider calls (direct LiteLLM or mesh delegation)
 * - Response parsing with Zod validation
 * - Metadata tracking (tokens, latency, tool calls)
 *
 * @example
 * ```typescript
 * const agent = new MeshLlmAgent({
 *   provider: "claude",
 *   model: "anthropic/claude-sonnet-4-20250514",
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
  maxTokens?: number;
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
      maxTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
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
      maxTokens?: number;
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

    if (options?.maxTokens) body.max_tokens = options.maxTokens;
    if (options?.temperature !== undefined) body.temperature = options.temperature;
    if (options?.topP !== undefined) body.top_p = options.topP;
    if (options?.stop) body.stop = options.stop;

    // Set up timeout with AbortController (default 300s to match Python SDK's stream_timeout)
    const timeoutMs = parseInt(process.env.LITELLM_TIMEOUT_MS || "300000", 10);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === "AbortError") {
        throw new LLMAPIError(408, `Request timed out after ${timeoutMs}ms`, "litellm");
      }
      throw new LLMAPIError(0, `Fetch failed: ${error instanceof Error ? error.message : String(error)}`, "litellm");
    }
    clearTimeout(timeoutId);

    if (!response.ok) {
      const error = await response.text();
      throw new LLMAPIError(response.status, error, "litellm");
    }

    return (await response.json()) as LlmCompletionResponse;
  }
}

/**
 * Mesh provider that delegates to an LLM provider discovered via mesh.
 */
export class MeshDelegatedProvider implements LlmProvider {
  private endpoint: string;
  private functionName: string;

  constructor(endpoint: string, functionName: string) {
    this.endpoint = endpoint;
    this.functionName = functionName;
  }

  async complete(
    model: string,
    messages: LlmMessage[],
    tools?: LlmToolDefinition[],
    options?: {
      maxTokens?: number;
      temperature?: number;
      topP?: number;
      stop?: string[];
    }
  ): Promise<LlmCompletionResponse> {
    // Build MeshLlmRequest structure (matches Python claude_provider schema)
    const modelParams: Record<string, unknown> = {};
    // Only pass model if it's a real model name (not "default")
    if (model && model !== "default") {
      modelParams.model = model;
    }
    if (options?.maxTokens) modelParams.max_tokens = options.maxTokens;
    if (options?.temperature !== undefined) modelParams.temperature = options.temperature;
    if (options?.topP !== undefined) modelParams.top_p = options.topP;
    if (options?.stop) modelParams.stop = options.stop;

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
    const args = { request };

    // Set up timeout with AbortController (default 300s to match Python SDK's stream_timeout)
    const timeoutMs = parseInt(process.env.MESH_PROVIDER_TIMEOUT_MS || "300000", 10);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    // Call the mesh provider via MCP
    let response: Response;
    try {
      response = await fetch(`${this.endpoint}/mcp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json, text/event-stream",
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
        signal: controller.signal,
      });
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === "AbortError") {
        throw new LLMAPIError(408, `Request timed out after ${timeoutMs}ms`, `mesh:${this.endpoint}`);
      }
      throw new LLMAPIError(0, `Fetch failed: ${error instanceof Error ? error.message : String(error)}`, `mesh:${this.endpoint}`);
    }
    clearTimeout(timeoutId);

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

    // Parse the Python claude_provider response
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
    const startTime = Date.now();
    const toolCalls: LlmToolCall[] = [];
    let totalInputTokens = 0;
    let totalOutputTokens = 0;

    // Resolve provider
    const provider = this.resolveProvider(context);

    // Build initial messages
    const messages: LlmMessage[] = [];

    // Build tool definitions first (needed for schema injection)
    const toolDefs = this.buildToolDefinitions(context.tools);

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

      // Inject output schema hint if using "hint" or "strict" mode with a schema
      const outputMode = this.config.outputMode ?? "hint";
      if (outputMode !== "text" && this.config.returnSchema) {
        const outputSchemaSection = this.buildOutputSchemaSection();
        systemContent += outputSchemaSection;
      }

      messages.push({ role: "system", content: systemContent });
    }

    // Handle multi-turn conversation input
    if (typeof messageInput === "string") {
      // Simple string - add as user message
      messages.push({ role: "user", content: messageInput });
    } else {
      // Array of messages - add all
      for (const msg of messageInput) {
        messages.push({ role: msg.role, content: msg.content });
      }
    }

    // Get effective options
    const maxIterations = context.options?.maxIterations ?? this.config.maxIterations;
    const maxTokens = context.options?.maxTokens ?? this.config.maxTokens;
    const temperature = context.options?.temperature ?? this.config.temperature;

    // Determine model
    const model = context.meshProvider?.model ?? this.config.model ?? this.getDefaultModel();

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
        { maxTokens, temperature, topP: this.config.topP, stop: this.config.stop }
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
        // Execute tool calls
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

        // Continue loop to get next response
        continue;
      }

      // No tool calls - this is the final response
      finalContent = assistantMessage.content ?? "";
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
   */
  private resolveProvider(context: AgentRunContext): LlmProvider {
    // If mesh provider is resolved, use it
    if (context.meshProvider) {
      return new MeshDelegatedProvider(
        context.meshProvider.endpoint,
        context.meshProvider.functionName
      );
    }

    // Use direct LiteLLM provider
    return new LiteLLMProvider();
  }

  /**
   * Get provider name for metadata.
   */
  private getProviderName(context: AgentRunContext): string {
    if (context.meshProvider) {
      return `mesh:${context.meshProvider.endpoint}`;
    }

    if (typeof this.config.provider === "string") {
      return this.config.provider;
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
        claude: "anthropic/claude-sonnet-4-20250514",
        openai: "gpt-4o",
        anthropic: "anthropic/claude-sonnet-4-20250514",
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
   */
  private buildToolDefinitions(tools: LlmToolProxy[]): LlmToolDefinition[] {
    return tools.map((tool) => ({
      type: "function" as const,
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.inputSchema ?? { type: "object", properties: {} },
      },
    }));
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
    // Set up timeout with AbortController (default 30s for tool calls)
    const timeoutMs = parseInt(process.env.MESH_TOOL_TIMEOUT_MS || "30000", 10);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    // Make MCP call to the tool
    let response: Response;
    try {
      response = await fetch(`${toolInfo.endpoint}/mcp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json, text/event-stream",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: Date.now(),
          method: "tools/call",
          params: {
            name: toolInfo.functionName,
            arguments: args,
          },
        }),
        signal: controller.signal,
      });
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === "AbortError") {
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
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`Tool call failed: ${response.status}`);
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
      return null;
    }

    if (content.type === "text" && content.text) {
      // Try to parse as JSON
      try {
        return JSON.parse(content.text);
      } catch {
        return content.text;
      }
    }

    return content;
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
