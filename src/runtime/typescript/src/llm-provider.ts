/**
 * LLM Provider implementation for @mcpmesh/sdk.
 *
 * Provides mesh.llmProvider() for zero-code LLM providers using Vercel AI SDK.
 * This is the TypeScript equivalent of Python's @mesh.llm_provider decorator.
 *
 * @example
 * ```typescript
 * import { FastMCP } from "fastmcp";
 * import { mesh } from "@mcpmesh/sdk";
 *
 * const server = new FastMCP({ name: "Claude Provider", version: "1.0.0" });
 *
 * // Zero-code LLM provider
 * server.addTool(mesh.llmProvider({
 *   model: "anthropic/claude-sonnet-4-5",
 *   capability: "llm",
 *   tags: ["llm", "claude", "anthropic", "provider"],
 * }));
 *
 * const agent = mesh(server, { name: "claude-provider", httpPort: 9011 });
 * ```
 */

import { z } from "zod";
import { createDebug } from "./debug.js";
import type {
  LlmProviderConfig,
  MeshLlmResponse,
  LlmMessage,
  LlmToolCallRequest,
} from "./types.js";
import { ProviderHandlerRegistry, makeSchemaStrict } from "./provider-handlers/index.js";
import { generateTraceId, generateSpanId, publishTraceSpan, matchesPropagateHeader } from "./tracing.js";
import type { TraceContext } from "./tracing.js";
import { runWithTraceContext, runWithPropagatedHeaders, callMcpTool } from "./proxy.js";
import { resolveResourceLinks, resolveResourceLinksForToolMessage, hasResourceLink, TOOL_IMAGE_UNSUPPORTED_VENDORS, type ResolvedContent } from "./media/index.js";

const debug = createDebug("llm-provider");

// ============================================================================
// Vendor Extraction
// ============================================================================

/**
 * Known vendors and their Vercel AI SDK provider import paths.
 */
const VENDOR_PROVIDERS: Record<string, string> = {
  anthropic: "@ai-sdk/anthropic",
  openai: "@ai-sdk/openai",
  google: "@ai-sdk/google",
  gemini: "@ai-sdk/google", // gemini/ model prefix uses Google AI SDK
  // Can extend with more providers as needed
};

/**
 * Mapping from vendor name to the export name in the provider module.
 * Most providers export a function with the same name as the vendor,
 * but some (like gemini) use a different name (google).
 */
const VENDOR_EXPORTS: Record<string, string> = {
  gemini: "google", // @ai-sdk/google exports 'google', not 'gemini'
};

/**
 * Normalize environment variables for cross-SDK compatibility.
 *
 * Different SDKs use different env var names:
 * - Python/LiteLLM: GOOGLE_API_KEY
 * - Vercel AI SDK: GOOGLE_GENERATIVE_AI_API_KEY
 *
 * This function ensures either env var works for both SDKs.
 */
function normalizeEnvVars(vendor: string): void {
  if (vendor === "gemini" || vendor === "google") {
    // Vercel AI SDK expects GOOGLE_GENERATIVE_AI_API_KEY
    // LiteLLM expects GOOGLE_API_KEY
    // Support both by copying if one is set but not the other
    const vercelKey = process.env.GOOGLE_GENERATIVE_AI_API_KEY;
    const litellmKey = process.env.GOOGLE_API_KEY;

    if (!vercelKey && litellmKey) {
      process.env.GOOGLE_GENERATIVE_AI_API_KEY = litellmKey;
      debug("Set GOOGLE_GENERATIVE_AI_API_KEY from GOOGLE_API_KEY");
    } else if (vercelKey && !litellmKey) {
      process.env.GOOGLE_API_KEY = vercelKey;
      debug("Set GOOGLE_API_KEY from GOOGLE_GENERATIVE_AI_API_KEY");
    }
  }
}

/**
 * Extract vendor name from model string.
 *
 * Uses vendor/model format (e.g., "anthropic/claude-sonnet-4-5" → "anthropic").
 *
 * @param model - Model string (e.g., "anthropic/claude-sonnet-4-5")
 * @returns Vendor name or null if not extractable
 *
 * @example
 * ```typescript
 * extractVendorFromModel("anthropic/claude-sonnet-4-5") // "anthropic"
 * extractVendorFromModel("openai/gpt-4o") // "openai"
 * extractVendorFromModel("gpt-4") // null
 * ```
 */
export function extractVendorFromModel(model: string): string | null {
  if (!model) {
    return null;
  }

  // Handle slash format (e.g., "anthropic/claude-sonnet-4-5")
  if (model.includes("/")) {
    const vendor = model.split("/")[0].toLowerCase().trim();
    return vendor || null;
  }

  return null;
}

/**
 * Extract model name without vendor prefix.
 *
 * @param model - Model string (e.g., "anthropic/claude-sonnet-4-5")
 * @returns Model name without vendor prefix
 *
 * @example
 * ```typescript
 * extractModelName("anthropic/claude-sonnet-4-5") // "claude-sonnet-4-5"
 * extractModelName("gpt-4") // "gpt-4"
 * ```
 */
export function extractModelName(model: string): string {
  // Handle slash format (e.g., "anthropic/claude-sonnet-4-5")
  if (model.includes("/")) {
    return model.split("/").slice(1).join("/");
  }
  return model;
}

// ============================================================================
// Vercel AI SDK Integration
// ============================================================================

/**
 * Dynamically load a Vercel AI SDK provider.
 *
 * @param vendor - Vendor name (e.g., "anthropic", "openai")
 * @returns Provider create function or null if not available
 */
export async function loadProvider(
  vendor: string
): Promise<((modelId: string) => unknown) | null> {
  // Normalize environment variables for cross-SDK compatibility
  normalizeEnvVars(vendor);

  const providerPath = VENDOR_PROVIDERS[vendor];
  if (!providerPath) {
    debug(`Unknown vendor: ${vendor}`);
    return null;
  }

  try {
    // Dynamic import of the provider module
    const providerModule = (await import(providerPath)) as Record<
      string,
      unknown
    >;

    // Get the export name (may differ from vendor name, e.g., gemini -> google)
    const exportName = VENDOR_EXPORTS[vendor] ?? vendor;

    // Each provider exports a function with the vendor name (e.g., anthropic, openai)
    const createModel = providerModule[exportName] as
      | ((modelId: string) => unknown)
      | undefined;
    if (typeof createModel !== "function") {
      debug(`Provider ${vendor} does not export a model creator function (looked for '${exportName}')`);
      return null;
    }

    return createModel;
  } catch (err) {
    debug(`Failed to load provider ${vendor}: ${err}`);
    return null;
  }
}

/**
 * Vercel AI SDK CoreMessage type (simplified - actual types are more complex).
 * Messages are passed through handler.prepareRequest() which does vendor-specific conversion.
 */
type VercelCoreMessage = Record<string, unknown>;

/**
 * Convert LlmMessage array to base format for Vercel AI SDK.
 *
 * NOTE: This is a simple pass-through conversion. Vendor-specific message
 * transformations (e.g., Anthropic's tool-call content blocks) are handled
 * by the provider handlers in their prepareRequest() method.
 */
function convertToVercelMessages(messages: LlmMessage[]): VercelCoreMessage[] {
  // Pass through - the handler.prepareRequest() has already transformed messages
  // for the specific vendor format
  return messages as unknown as VercelCoreMessage[];
}

/**
 * AI SDK v6 tool call structure.
 * Note: AI SDK v6 uses 'input' for tool call arguments (not 'args').
 */
interface VercelToolCall {
  type?: string;
  toolCallId: string;
  toolName: string;
  input: Record<string, unknown>;  // AI SDK v6 uses 'input', not 'args'
}

/**
 * Convert Vercel AI SDK v6 tool calls to standard format.
 */
function convertToolCalls(toolCalls: VercelToolCall[]): LlmToolCallRequest[] {
  return toolCalls.map((tc) => ({
    id: tc.toolCallId,
    type: "function" as const,
    function: {
      name: tc.toolName,
      arguments: JSON.stringify(tc.input ?? {}),  // Use 'input' for AI SDK v6
    },
  }));
}

// ============================================================================
// LLM Provider Implementation
// ============================================================================

/**
 * Zod schema for MeshLlmRequest input.
 */
const MeshLlmRequestSchema = z.object({
  request: z.object({
    messages: z.array(
      z.object({
        role: z.enum(["system", "user", "assistant", "tool"]),
        content: z.string().nullable(),
        tool_calls: z
          .array(
            z.object({
              id: z.string(),
              type: z.literal("function"),
              function: z.object({
                name: z.string(),
                arguments: z.string(),
              }),
            })
          )
          .optional(),
        tool_call_id: z.string().optional(),
        name: z.string().optional(),
      })
    ),
    tools: z
      .array(
        z.object({
          type: z.literal("function"),
          function: z.object({
            name: z.string(),
            description: z.string().optional(),
            parameters: z.record(z.unknown()).optional(),
            _mesh_endpoint: z.string().optional(),
          }).passthrough(),
        })
      )
      .nullish(),
    model_params: z.record(z.unknown()).nullish(),
    context: z.record(z.unknown()).nullish(),
    request_id: z.string().nullish(),
    caller_agent: z.string().nullish(),
  }),
});

type MeshLlmRequestInput = z.infer<typeof MeshLlmRequestSchema>;

/**
 * Create a zero-code LLM provider tool definition.
 *
 * This is the TypeScript equivalent of Python's @mesh.llm_provider decorator.
 * It generates a process_chat function that handles MeshLlmRequest and returns
 * MeshLlmResponse with tool_calls and usage metadata.
 *
 * @param config - LLM provider configuration
 * @returns fastmcp tool definition
 *
 * @example
 * ```typescript
 * import { FastMCP } from "fastmcp";
 * import { mesh } from "@mcpmesh/sdk";
 *
 * const server = new FastMCP({ name: "Claude Provider", version: "1.0.0" });
 *
 * server.addTool(mesh.llmProvider({
 *   model: "anthropic/claude-sonnet-4-5",
 *   capability: "llm",
 *   tags: ["llm", "claude", "anthropic", "provider"],
 *   maxOutputTokens: 4096,
 *   temperature: 0.7,
 * }));
 *
 * const agent = mesh(server, { name: "claude-provider", httpPort: 9011 });
 * ```
 */
export function llmProvider(config: LlmProviderConfig): {
  name: string;
  description: string;
  parameters: ReturnType<typeof MeshLlmRequestSchema.passthrough>;
  execute: (args: MeshLlmRequestInput) => Promise<string>;
  // Mesh metadata attached to the tool definition
  _meshMeta?: {
    capability: string;
    tags: string[];
    version: string;
    vendor: string;
  };
} {
  const {
    model,
    capability = "llm",
    tags = [],
    version = "1.0.0",
    maxOutputTokens: maxTokens,
    temperature,
    topP,
    name = "process_chat",
    description = `LLM provider using ${model}`,
  } = config;

  // Extract vendor from model
  const vendor = extractVendorFromModel(model) ?? "unknown";

  debug(`Creating LLM provider: model=${model}, vendor=${vendor}, capability=${capability}`);

  // Cache the loaded provider
  let cachedProvider: ((modelId: string) => unknown) | null = null;
  let providerLoadAttempted = false;

  /**
   * Process a chat request using Vercel AI SDK.
   */
  const execute = async (args: MeshLlmRequestInput): Promise<string> => {
    // Extract trace context from arguments (injected by upstream consumer)
    let incomingTraceId: string | null = null;
    let incomingParentSpan: string | null = null;

    if (args && typeof args === "object") {
      const argsObj = args as Record<string, unknown>;
      if (typeof argsObj._trace_id === "string") {
        incomingTraceId = argsObj._trace_id;
      }
      if (typeof argsObj._parent_span === "string") {
        incomingParentSpan = argsObj._parent_span;
      }
    }

    // Extract _mesh_headers from arguments for header propagation
    let propagatedHeaders: Record<string, string> = {};
    if (args && typeof args === "object") {
      const argsObj = args as Record<string, unknown>;
      if (argsObj._mesh_headers && typeof argsObj._mesh_headers === "object") {
        const meshHeaders = argsObj._mesh_headers as Record<string, unknown>;
        for (const [key, value] of Object.entries(meshHeaders)) {
          if (typeof value === "string" && matchesPropagateHeader(key)) {
            propagatedHeaders[key.toLowerCase()] = value;
          }
        }
      }
    }

    // Set up trace context
    const traceId = incomingTraceId ?? generateTraceId();
    const spanId = generateSpanId();
    const parentSpanId = incomingParentSpan ?? null;
    const traceContext: TraceContext = { traceId, parentSpanId: spanId };

    const traceStartTime = Date.now() / 1000;
    let traceSuccess = true;
    let traceError: string | null = null;

    try {
      const runInner = async () => {
        try {
    const { request } = args;
    const startTime = Date.now();

    debug(`Processing chat request: messages=${request.messages.length}, tools=${request.tools?.length ?? 0}`);
    debug(`Received model_params keys: ${JSON.stringify(Object.keys(request.model_params ?? {}))}`);

    // Determine effective model (check for consumer override)
    let effectiveModel = model;
    const modelParams = { ...(request.model_params ?? {}) };

    if (modelParams.model && typeof modelParams.model === "string") {
      const overrideModel = modelParams.model;
      delete modelParams.model; // Remove to avoid duplication

      // Validate vendor compatibility
      const overrideVendor = extractVendorFromModel(overrideModel);

      if (overrideVendor && overrideVendor !== vendor) {
        // Vendor mismatch - log warning and fall back to provider's model
        debug(
          `Model override '${overrideModel}' ignored - vendor mismatch ` +
            `(override vendor: '${overrideVendor}', provider vendor: '${vendor}'). ` +
            `Using provider's default model: '${model}'`
        );
      } else {
        // Vendor matches or can't be determined - use override
        effectiveModel = overrideModel;
        debug(`Using model override '${effectiveModel}' (requested by consumer)`);
      }
    }

    // Issue #459: Extract output_schema for structured output via generateObject()
    const outputSchema = modelParams.output_schema as Record<string, unknown> | undefined;
    const outputTypeName = modelParams.output_type_name as string | undefined;
    delete modelParams.output_schema;
    delete modelParams.output_type_name;

    // Build OutputSchema object for handler (prompt formatting) - generateObject uses it directly
    const outputSchemaObj = outputSchema ? {
      schema: outputSchema,
      name: outputTypeName ?? "Response",
    } : null;

    if (outputSchemaObj) {
      debug(`Received output_schema for structured output: ${outputSchemaObj.name}`);
    }

    const effectiveModelName = extractModelName(effectiveModel);

    // Load provider if not cached
    if (!providerLoadAttempted) {
      providerLoadAttempted = true;
      cachedProvider = await loadProvider(vendor);
    }

    if (!cachedProvider) {
      throw new Error(
        `Vercel AI SDK provider for '${vendor}' not available. ` +
          `Install: npm install ${VENDOR_PROVIDERS[vendor] ?? `@ai-sdk/${vendor}`}`
      );
    }

    // Create the model instance
    const aiModel = cachedProvider(effectiveModelName);

    // Get vendor-specific handler for optimizations
    const handler = ProviderHandlerRegistry.getHandler(vendor);
    debug(`Using provider handler: ${handler.constructor.name} for vendor: ${vendor}`);

    // Determine output mode early (needed for system prompt formatting and prepareRequest)
    const hasTools = request.tools && request.tools.length > 0;
    const outputMode = handler.determineOutputMode(outputSchemaObj);

    // When tools are present with structured output, we use generateText() with two strategies:
    // 1. HINT mode instructions in the system prompt (DECISION GUIDE + JSON schema + field
    //    descriptions + example format) so the LLM knows exactly what JSON structure to return
    // 2. responseFormat via providerOptions (native enforcement via prepareRequest)
    // The prompt uses "hint" mode for detailed instructions, while prepareRequest keeps
    // "strict" mode to set responseFormat for native API enforcement.
    const promptOutputMode = (hasTools && outputSchemaObj && outputMode === "strict")
      ? "hint" as const
      : outputMode;
    if (promptOutputMode !== outputMode) {
      debug(`Tools present with structured output: using hint mode for prompt (strict for responseFormat)`);
    }
    debug(`Output mode: ${outputMode}, prompt mode: ${promptOutputMode}`);

    // Format system prompt with vendor-specific instructions (JSON format, tool rules, etc.)
    // Uses promptOutputMode so handlers add detailed HINT instructions (DECISION GUIDE,
    // JSON schema, field descriptions, example format) when tools + structured output
    // are both present. Without this, LLMs return wrong data.
    const formattedMessages = request.messages.map(msg => {
      if (msg.role === "system" && msg.content) {
        const formattedContent = handler.formatSystemPrompt(
          msg.content,
          request.tools ?? null,  // ToolSchema[] format (OpenAI function calling)
          outputSchemaObj,
          promptOutputMode
        );
        debug(`Formatted system prompt (${promptOutputMode} mode): ${formattedContent.substring(0, 200)}...`);
        return { ...msg, content: formattedContent };
      }
      return msg;
    });

    // Import generateText from ai package
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const aiModule = await import("ai") as any;
    const generateText = aiModule.generateText as (options: {
      model: unknown;
      messages: Array<{
        role: "system" | "user" | "assistant" | "tool";
        content: string;
        toolCallId?: string;
        name?: string;
      }>;
      tools?: Record<
        string,
        {
          description?: string;
          parameters?: Record<string, unknown>;
        }
      >;
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      providerOptions?: Record<string, Record<string, unknown>>;
    }) => Promise<{
      text: string;
      toolCalls?: Array<{
        type?: string;
        toolCallId: string;
        toolName: string;
        input: Record<string, unknown>;  // AI SDK v6 uses 'input', not 'args'
      }>;
      usage?: {
        inputTokens: number;
        outputTokens: number;
      };
      finishReason: string;
    }>;

    // Convert tools to Vercel AI SDK format using the tool() helper
    // Import jsonSchema and tool from ai package for proper schema handling
    const { jsonSchema, tool: aiTool } = aiModule as {
      jsonSchema: (schema: Record<string, unknown>) => unknown;
      tool: (config: { description?: string; inputSchema: unknown; execute?: (args: unknown) => Promise<unknown> }) => unknown;
    };

    // Extract _mesh_endpoint from tool schemas for provider-side execution.
    // When the consumer sends tools enriched with _mesh_endpoint, the provider
    // executes tools internally via MCP calls instead of returning tool_calls.
    const toolEndpoints: Record<string, string> = {};
    if (request.tools && request.tools.length > 0) {
      for (const tool of request.tools) {
        const funcDef = tool.function as Record<string, unknown>;
        const endpoint = funcDef._mesh_endpoint;
        if (typeof endpoint === "string") {
          toolEndpoints[tool.function.name] = endpoint;
          delete funcDef._mesh_endpoint;
        }
      }
    }
    const hasToolEndpoints = Object.keys(toolEndpoints).length > 0;
    // Gemini: use AI SDK's maxSteps with execute functions instead of manual loop.
    // The manual loop drops Gemini's thought_signature from assistant messages,
    // causing 400 errors in multi-turn tool conversations. AI SDK preserves it.
    // Claude/OpenAI keep the manual loop (they need response_format on every call).
    const useMaxSteps = hasToolEndpoints && (vendor === "gemini" || vendor === "google");
    if (hasToolEndpoints) {
      debug(`Provider-managed loop: ${Object.keys(toolEndpoints).length} tools with endpoints${useMaxSteps ? " (Gemini maxSteps mode)" : ""}`);
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let vercelTools: Record<string, any> | undefined;
    if (request.tools && request.tools.length > 0) {
      vercelTools = {};
      for (const tool of request.tools) {
        // Get the raw schema parameters
        const rawSchema = tool.function.parameters ?? { type: "object", properties: {} };

        // Clean up schema for AI SDK compatibility:
        // - Remove $schema field (not needed for API calls)
        // - Ensure type: "object" is present (required by Anthropic API)
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { $schema, ...schemaWithoutMeta } = rawSchema as Record<string, unknown>;
        const cleanSchema = {
          type: "object", // Ensure type is always present
          ...schemaWithoutMeta,
        };

        debug(`Tool '${tool.function.name}' cleanSchema: ${JSON.stringify(cleanSchema, null, 2)}`);

        const toolName = tool.function.name;

        if (useMaxSteps) {
          // Gemini: use execute functions + maxSteps (AI SDK preserves thought_signature)
          const toolEndpoint = toolEndpoints[toolName];
          vercelTools[toolName] = aiTool({
            description: tool.function.description ?? "",
            inputSchema: jsonSchema(cleanSchema),
            execute: async (args: unknown) => {
              const toolArgs = (args ?? {}) as Record<string, unknown>;
              debug(`Provider executing tool '${toolName}' at ${toolEndpoint}`);
              try {
                const result = await callMcpTool(toolEndpoint, toolName, toolArgs, 30000, 1, "tool");
                // Resolve resource_links to provider-native media content
                if (hasResourceLink(result)) {
                  debug(`Tool '${toolName}' result contains resource_link, resolving for ${vendor}`);
                  const resolved = await resolveResourceLinksForToolMessage(result, vendor);
                  // Return resolved content as structured result for AI SDK
                  return resolved.length === 1 ? resolved[0] : resolved;
                }
                if (typeof result === "object") {
                  debug(`Tool '${toolName}' result: [multi_content]`);
                  return result;
                }
                debug(`Tool '${toolName}' result: ${result.substring(0, 200)}`);
                try { return JSON.parse(result); } catch { return result; }
              } catch (err) {
                const errorMsg = err instanceof Error ? err.message : String(err);
                debug(`Tool '${toolName}' execution failed: ${errorMsg}`);
                return { error: errorMsg };
              }
            },
          });
          debug(`Tool '${toolName}' vercelTool created (with execute for Gemini maxSteps)`);
        } else {
          // Claude/OpenAI or no endpoints: schema only (manual loop or consumer handles)
          vercelTools[toolName] = aiTool({
            description: tool.function.description ?? "",
            inputSchema: jsonSchema(cleanSchema),
          });
          debug(`Tool '${toolName}' vercelTool created (schema only, no execute)`);
        }
      }
    }

    // Apply vendor-specific request preparation (e.g., Claude prompt caching)
    // The handler may transform messages or add vendor-specific options
    // Use formattedMessages which have the system prompt already formatted by the handler
    const preparedRequest = handler.prepareRequest(
      formattedMessages as LlmMessage[],
      null, // tools handled separately for Vercel AI SDK
      outputSchemaObj, // Pass output schema for additional vendor-specific options
      {
        outputMode,  // Pass output mode determined earlier
        temperature: temperature ?? modelParams.temperature as number | undefined,
        maxOutputTokens: maxTokens ?? modelParams.max_tokens as number | undefined,
        topP: topP ?? modelParams.top_p as number | undefined,
      }
    );

    // Build request options - use explicit object construction to avoid spread type issues
    const convertedMessages = convertToVercelMessages(preparedRequest.messages);

    debug(`Messages to AI SDK: ${JSON.stringify(convertedMessages, null, 2)}`);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const requestOptions: {
      model: unknown;
      messages: any; // VercelCoreMessage[] - Vercel AI SDK validates at runtime
      tools?: Record<string, any>;
      maxSteps?: number;
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
      providerOptions?: Record<string, Record<string, unknown>>;
    } = {
      model: aiModel,
      messages: convertedMessages,
    };

    // Add tools if present
    if (vercelTools && Object.keys(vercelTools).length > 0) {
      requestOptions.tools = vercelTools;
      if (useMaxSteps) {
        // Gemini: let AI SDK manage the agentic loop via maxSteps.
        // AI SDK preserves thought_signature across turns automatically.
        requestOptions.maxSteps = 10;
        debug(`Gemini provider-managed loop via maxSteps=10 (AI SDK preserves thought_signature)`);
      }
      // Note: for non-Gemini vendors, maxSteps is NOT set. We manage
      // the agentic loop manually so that providerOptions (including
      // response_format) is applied on every LLM call, not just the first.
    }

    // Apply default config values
    if (maxTokens) {
      requestOptions.maxOutputTokens = maxTokens;
    }
    if (temperature !== undefined) {
      requestOptions.temperature = temperature;
    }
    if (topP !== undefined) {
      requestOptions.topP = topP;
    }

    // Apply model_params overrides (take precedence)
    if (modelParams.max_tokens) {
      requestOptions.maxOutputTokens = modelParams.max_tokens as number;
    }
    if (modelParams.temperature !== undefined) {
      requestOptions.temperature = modelParams.temperature as number;
    }
    if (modelParams.top_p !== undefined) {
      requestOptions.topP = modelParams.top_p as number;
    }

    // Pass responseFormat from handler's prepareRequest to generateText via providerOptions.
    // This enables native structured output (response_format) alongside tools in generateText(),
    // which generateObject() doesn't support. The handler sets responseFormat when in strict mode.
    // EXCEPTION: Gemini 3 + response_format + tools causes infinite tool loops,
    // so skip responseFormat when Gemini has tools (matching Python handler guard).
    const skipResponseFormat = (vendor === "gemini" || vendor === "google") && hasTools;
    if (preparedRequest.responseFormat && !skipResponseFormat) {
      requestOptions.providerOptions = {
        [vendor]: {
          response_format: preparedRequest.responseFormat,
        },
      };
      debug(`Passing responseFormat via providerOptions for vendor: ${vendor}`);
    } else if (skipResponseFormat) {
      debug(`Skipping responseFormat for Gemini (tools present — avoids infinite loop)`);
    }

    debug(`Calling Vercel AI SDK: model=${effectiveModelName}`);

    // Issue #459: Use generateObject for structured output based on handler's output mode
    // - "strict" mode: Use generateObject() for native structured output (OpenAI/Gemini)
    // - "hint" mode: Use generateText() with prompt-based JSON instructions (Claude)
    // - "text" mode: Use generateText() for plain text output
    // NOTE: generateObject() doesn't support tools in Vercel AI SDK, so when tools are
    // present we must use generateText(). The handler's formatSystemPrompt() adds JSON
    // instructions to ensure the LLM returns structured output even via generateText().
    // outputMode was determined earlier (before formatSystemPrompt call)
    const useStructuredOutput = outputMode === "strict" && outputSchema && !vercelTools;
    debug(`Output mode: ${outputMode}, useStructuredOutput: ${useStructuredOutput}`);

    let response: MeshLlmResponse | undefined;
    let latencyMs: number = 0;
    let resultUsage: { inputTokens?: number; outputTokens?: number } | undefined;

    if (useStructuredOutput) {
      // Use generateObject for structured output
      debug(`Using generateObject for structured output: ${outputTypeName}`);

      const generateObject = aiModule.generateObject as (options: {
        model: unknown;
        messages: unknown[];
        schema: unknown;
        schemaName?: string;
        schemaDescription?: string;
        maxOutputTokens?: number;
        temperature?: number;
        topP?: number;
      }) => Promise<{
        object: Record<string, unknown>;
        usage?: {
          inputTokens: number;
          outputTokens: number;
        };
        finishReason: string;
      }>;

      // Import jsonSchema helper to wrap JSON Schema for generateObject
      const { jsonSchema } = aiModule as { jsonSchema: (schema: Record<string, unknown>) => unknown };

      // Clean up schema - remove $schema and other meta fields
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { $schema, title, ...cleanSchema } = outputSchema as Record<string, unknown>;

      // Apply strict constraints recursively to all nested objects
      // This adds additionalProperties: false and required fields at all levels
      // Required for OpenAI/Gemini structured output, and enables future Claude support
      const strictSchema = makeSchemaStrict(cleanSchema as Record<string, unknown>, { addAllRequired: true });

      const objectResult = await generateObject({
        model: aiModel,
        messages: convertedMessages,
        schema: jsonSchema(strictSchema),
        schemaName: outputTypeName,
        maxOutputTokens: requestOptions.maxOutputTokens,
        temperature: requestOptions.temperature,
        topP: requestOptions.topP,
      });

      latencyMs = Date.now() - startTime;
      debug(
        `generateObject response received: ` +
          `finishReason=${objectResult.finishReason}, ` +
          `latency=${latencyMs}ms`
      );

      // Build response with structured object as JSON string content
      response = {
        role: "assistant",
        content: JSON.stringify(objectResult.object),
      };
      resultUsage = objectResult.usage;
    } else if (hasToolEndpoints && !useMaxSteps) {
      // Provider-managed agentic loop: execute tools internally.
      // Unlike AI SDK's maxSteps, this manual loop ensures providerOptions
      // (including response_format for structured output) is applied on
      // EVERY LLM call, not just the first one.
      let iteration = 0;
      const maxIterations = 10;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let currentMessages: any[] = [...convertedMessages];

      while (iteration < maxIterations) {
        iteration++;

        // Build request for this iteration — reuse all options but update messages
        const iterRequest = {
          ...requestOptions,
          messages: currentMessages,
        };
        // Do NOT set maxSteps — we manage the loop manually

        const result = await generateText(iterRequest);

        // Accumulate usage across iterations
        if (result.usage) {
          if (!resultUsage) {
            resultUsage = { inputTokens: 0, outputTokens: 0 };
          }
          resultUsage.inputTokens = (resultUsage.inputTokens ?? 0) + (result.usage.inputTokens ?? 0);
          resultUsage.outputTokens = (resultUsage.outputTokens ?? 0) + (result.usage.outputTokens ?? 0);
        }

        if (result.toolCalls && result.toolCalls.length > 0) {
          debug(`Provider executing ${result.toolCalls.length} tool calls (iteration ${iteration}/${maxIterations})`);

          // Add assistant message with tool calls (Vercel AI SDK content block format)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const assistantContentParts: any[] = [];
          if (result.text) {
            assistantContentParts.push({ type: "text", text: result.text });
          }
          for (const tc of result.toolCalls) {
            assistantContentParts.push({
              type: "tool-call",
              toolCallId: tc.toolCallId,
              toolName: tc.toolName,
              input: tc.input,
            });
          }
          currentMessages.push({
            role: "assistant",
            content: assistantContentParts,
          });

          // Collect images that cannot go in tool messages (OpenAI/Gemini).
          // After ALL tool results, we inject ONE user message with all images.
          // This keeps the message sequence valid:
          // assistant(tool_calls) -> tool -> tool -> ... -> user(images)
          const accumulatedImageParts: ResolvedContent[] = [];

          // Execute each tool call and add results as tool messages
          for (const tc of result.toolCalls) {
            const toolName = tc.toolName;
            const toolEndpoint = toolEndpoints[toolName];
            let toolResultStr: string;
            // Track raw result for resource_link resolution
            let rawToolResult: unknown = null;

            if (toolEndpoint) {
              try {
                const toolArgs = (tc.input ?? {}) as Record<string, unknown>;
                debug(`Provider executing tool '${toolName}' at ${toolEndpoint}`);
                const rawResult = await callMcpTool(
                  toolEndpoint,
                  toolName,
                  toolArgs,
                  30000, // 30s timeout
                  1,     // 1 attempt
                  "tool",
                );
                rawToolResult = rawResult;
                toolResultStr = typeof rawResult === "object"
                  ? JSON.stringify(rawResult)
                  : rawResult;
                debug(`Tool '${toolName}' result: ${toolResultStr.substring(0, 200)}`);
              } catch (err) {
                const errorMsg = err instanceof Error ? err.message : String(err);
                debug(`Tool '${toolName}' execution failed: ${errorMsg}`);
                toolResultStr = JSON.stringify({ error: errorMsg });
              }
            } else {
              toolResultStr = JSON.stringify({ error: `No endpoint for tool ${toolName}` });
            }

            // Resolve resource_links to provider-native multimodal content.
            // Claude supports images in tool messages directly.
            // OpenAI/Gemini: text-only in tool message, images accumulated for user message.
            if (hasResourceLink(rawToolResult)) {
              debug(`Tool '${toolName}' result contains resource_link, resolving for ${vendor}`);
              const allParts = await resolveResourceLinks(rawToolResult, vendor);

              // Build tool result message with text-only content for OpenAI/Gemini,
              // or full multimodal content for Claude.
              const imageTypes = new Set(["image", "image_url"]);
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              let toolResultOutput: any;
              if (TOOL_IMAGE_UNSUPPORTED_VENDORS.has(vendor)) {
                // OpenAI/Gemini: text-only in tool message, images accumulated separately
                const textParts = allParts.filter(p => !imageTypes.has(p.type));
                toolResultOutput = { type: "text", value: textParts.map(p => (p.text as string) || "[image]").join("\n") };
              } else {
                // Claude/Anthropic: preserve full multimodal content in tool message
                toolResultOutput = { type: "json", value: allParts };
              }
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const toolResultContent: any[] = [{
                type: "tool-result",
                toolCallId: tc.toolCallId,
                toolName,
                output: toolResultOutput,
              }];
              currentMessages.push({
                role: "tool",
                content: toolResultContent,
              });

              // Accumulate images for a single user message after ALL tool results.
              // For vendors that don't support images in tool messages, extract image
              // parts from the already-resolved content (no second fetch needed).
              if (TOOL_IMAGE_UNSUPPORTED_VENDORS.has(vendor)) {
                const imageParts = allParts.filter(p => imageTypes.has(p.type));
                accumulatedImageParts.push(...imageParts);
                debug(`Tool '${toolName}' resolved multimodal (vendor=${vendor}, images_accumulated=${imageParts.length})`);
              } else {
                debug(`Tool '${toolName}' resolved multimodal (vendor=${vendor}, inline in tool message)`);
              }
            } else {
              // No resource_links — standard tool result
              let toolOutput: { type: string; value: unknown };
              try {
                toolOutput = { type: "json", value: JSON.parse(toolResultStr) };
              } catch {
                toolOutput = { type: "text", value: toolResultStr };
              }

              // Add tool result message in Vercel AI SDK format
              currentMessages.push({
                role: "tool",
                content: [{
                  type: "tool-result",
                  toolCallId: tc.toolCallId,
                  toolName,
                  output: toolOutput,
                }],
              });
            }
          }

          // After ALL tool results: inject accumulated images as one user message.
          // Sequence: assistant(tool_calls) -> tool -> tool -> ... -> user(images)
          // This is valid because it comes after all tool results and before the
          // next LLM call.
          if (accumulatedImageParts.length > 0) {
            currentMessages.push({
              role: "user",
              content: [
                { type: "text", text: "Here are the images from the tool results above:" },
                ...accumulatedImageParts,
              ],
            });
            debug(`Injected user message with ${accumulatedImageParts.length} accumulated images (vendor=${vendor})`);
          }
        } else {
          // No tool calls — final response
          latencyMs = Date.now() - startTime;
          debug(`Provider-managed loop completed in ${iteration} iterations, latency=${latencyMs}ms`);

          response = {
            role: "assistant",
            content: result.text ?? "",
          };
          break;
        }
      }

      // Safety: max iterations reached without a final text response
      if (iteration >= maxIterations && !response) {
        latencyMs = Date.now() - startTime;
        debug(`Provider-managed loop hit max iterations (${maxIterations}), latency=${latencyMs}ms`);
        response = {
          role: "assistant",
          content: "Maximum tool call iterations reached",
        };
      }
    } else {
      // generateText path covers:
      // 1. Gemini maxSteps: AI SDK manages the tool loop (execute functions + maxSteps)
      // 2. No tool endpoints: consumer-managed tools or plain text
      const result = await generateText(requestOptions);

      latencyMs = Date.now() - startTime;
      debug(
        `LLM response received: ` +
          `finishReason=${result.finishReason}, ` +
          `toolCalls=${result.toolCalls?.length ?? 0}, ` +
          `latency=${latencyMs}ms`
      );

      // Build response
      response = {
        role: "assistant",
        content: result.text ?? "",
      };

      // Include tool_calls for consumer-managed execution only.
      // When hasToolEndpoints is true (Gemini maxSteps), tools were already
      // executed by AI SDK via execute functions — don't return tool_calls.
      if (!hasToolEndpoints && result.toolCalls && result.toolCalls.length > 0) {
        response.tool_calls = convertToolCalls(result.toolCalls);
      }
      resultUsage = result.usage;
    }

    // All code paths above must set response; assert it here
    const finalResponse = response!;

    // Include usage metadata for cost tracking (shared for all paths)
    if (resultUsage) {
      finalResponse._mesh_usage = {
        prompt_tokens: resultUsage.inputTokens ?? 0,
        completion_tokens: resultUsage.outputTokens ?? 0,
        model: effectiveModel,
      };
    }

    debug(
      `LLM provider processed request ` +
        `(model=${effectiveModel}, messages=${request.messages.length}, ` +
        `structured=${useStructuredOutput}, tool_calls=${finalResponse.tool_calls?.length ?? 0})`
    );

    // Return JSON-stringified response
    // The consumer (MeshDelegatedProvider.complete) expects content.text to be
    // a JSON string that it can parse to get the MeshLlmResponse object.
    // FastMCP wraps this in { content: [{ type: "text", text: <return_value> }] }
    return JSON.stringify(finalResponse);
        } catch (err) {
          console.error("[llm-provider] execute error:", err);
          if (err instanceof Error) {
            console.error("[llm-provider] stack:", err.stack);
          }
          throw err;
        }
      };

      const runWithHeaders = async () => {
        if (Object.keys(propagatedHeaders).length > 0) {
          return await runWithPropagatedHeaders(propagatedHeaders, runInner);
        }
        return await runInner();
      };

      return await runWithTraceContext(traceContext, runWithHeaders);
    } catch (err) {
      traceSuccess = false;
      traceError = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      const traceEndTime = Date.now() / 1000;
      const traceDurationMs = (traceEndTime - traceStartTime) * 1000;

      publishTraceSpan({
        traceId,
        spanId,
        parentSpan: parentSpanId,
        functionName: name,
        startTime: traceStartTime,
        endTime: traceEndTime,
        durationMs: traceDurationMs,
        success: traceSuccess,
        error: traceError,
        resultType: "string",
        argsCount: 0,
        kwargsCount: typeof args === "object" ? Object.keys(args as object).length : 0,
        dependencies: [],
        injectedDependencies: 0,
        meshPositions: [],
      }).catch(() => {});
    }
  };

  // Build the tool definition
  const toolDef = {
    name,
    description,
    // Use passthrough() to allow trace context fields (_trace_id, _parent_span)
    // to pass through Zod validation without being stripped
    parameters: MeshLlmRequestSchema.passthrough(),
    execute,
    // Attach mesh metadata for registration
    _meshMeta: {
      capability,
      tags,
      version,
      vendor,
    },
  };

  debug(
    `Created LLM provider '${name}' ` +
      `(model=${model}, capability=${capability}, tags=${JSON.stringify(tags)}, vendor=${vendor})`
  );

  return toolDef;
}

/**
 * Check if a tool definition is an LLM provider.
 */
export function isLlmProviderTool(
  tool: unknown
): tool is ReturnType<typeof llmProvider> {
  return (
    typeof tool === "object" &&
    tool !== null &&
    "_meshMeta" in tool &&
    typeof (tool as { _meshMeta?: unknown })._meshMeta === "object"
  );
}

/**
 * Get LLM provider metadata from a tool definition.
 */
export function getLlmProviderMeta(tool: ReturnType<typeof llmProvider>): {
  capability: string;
  tags: string[];
  version: string;
  vendor: string;
} | null {
  return tool._meshMeta ?? null;
}
