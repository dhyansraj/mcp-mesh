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
          }),
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
  parameters: typeof MeshLlmRequestSchema;
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

    // Determine output mode early (needed for system prompt formatting)
    // When tools are present, we can't use generateObject() (it doesn't support tools),
    // so we must fall back to "hint" mode to add JSON instructions to the system prompt.
    // This ensures the LLM knows to return structured JSON even when using generateText().
    const hasTools = request.tools && request.tools.length > 0;
    let outputMode = handler.determineOutputMode(outputSchemaObj);
    if (outputMode === "strict" && hasTools && outputSchemaObj) {
      debug(`Forcing hint mode: tools present (${request.tools?.length}), can't use generateObject`);
      outputMode = "hint";
    }
    debug(`Output mode for system prompt: ${outputMode}`);

    // Format system prompt with vendor-specific instructions (JSON format, tool rules, etc.)
    // This is critical for structured output - handlers add JSON instructions in "hint" mode
    // and brief notes in "strict" mode. Without this, LLMs may return plain text.
    const formattedMessages = request.messages.map(msg => {
      if (msg.role === "system" && msg.content) {
        const formattedContent = handler.formatSystemPrompt(
          msg.content,
          request.tools ?? null,  // ToolSchema[] format (OpenAI function calling)
          outputSchemaObj,
          outputMode
        );
        debug(`Formatted system prompt (${outputMode} mode): ${formattedContent.substring(0, 200)}...`);
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

    // Convert tools to Vercel AI SDK format
    // Note: Vercel AI SDK expects Zod schemas for parameters, but we receive JSON Schema
    // from MCP tools. We use jsonSchema() from the AI SDK to wrap JSON Schema properly.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let vercelTools: Record<string, any> | undefined;
    if (request.tools && request.tools.length > 0) {
      // Import jsonSchema helper from ai package
      const { jsonSchema } = aiModule as { jsonSchema: (schema: Record<string, unknown>) => unknown };
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

        debug(`Tool '${tool.function.name}' schema: ${JSON.stringify(cleanSchema)}`);

        vercelTools[tool.function.name] = {
          description: tool.function.description ?? "",
          inputSchema: jsonSchema(cleanSchema),
        };
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
      maxOutputTokens?: number;
      temperature?: number;
      topP?: number;
    } = {
      model: aiModel,
      messages: convertedMessages,
    };

    // Add tools if present
    if (vercelTools && Object.keys(vercelTools).length > 0) {
      requestOptions.tools = vercelTools;
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

    let response: MeshLlmResponse;
    let latencyMs: number;
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
    } else {
      // Use generateText for regular text or tool-calling scenarios
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

      // Include tool_calls if present (critical for agentic loop!)
      if (result.toolCalls && result.toolCalls.length > 0) {
        response.tool_calls = convertToolCalls(result.toolCalls);
      }
      resultUsage = result.usage;
    }

    // Include usage metadata for cost tracking (shared for both paths)
    if (resultUsage) {
      response._mesh_usage = {
        prompt_tokens: resultUsage.inputTokens ?? 0,
        completion_tokens: resultUsage.outputTokens ?? 0,
        model: effectiveModel,
      };
    }

    debug(
      `LLM provider processed request ` +
        `(model=${effectiveModel}, messages=${request.messages.length}, ` +
        `structured=${useStructuredOutput}, tool_calls=${response.tool_calls?.length ?? 0})`
    );

    // Return JSON-stringified response
    // The consumer (MeshDelegatedProvider.complete) expects content.text to be
    // a JSON string that it can parse to get the MeshLlmResponse object.
    // FastMCP wraps this in { content: [{ type: "text", text: <return_value> }] }
    return JSON.stringify(response);
    } catch (err) {
      console.error("[llm-provider] execute error:", err);
      if (err instanceof Error) {
        console.error("[llm-provider] stack:", err.stack);
      }
      throw err;
    }
  };

  // Build the tool definition
  const toolDef = {
    name,
    description,
    parameters: MeshLlmRequestSchema,
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
