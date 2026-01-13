/**
 * Generic provider handler for unknown/unsupported vendors.
 *
 * Provides sensible defaults using prompt-based approach similar to Claude.
 *
 * Based on Python's GenericHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/generic_handler.py
 */

import type { LlmMessage } from "../types.js";
import type {
  ProviderHandler,
  VendorCapabilities,
  ToolSchema,
  OutputSchema,
  PreparedRequest,
  OutputMode,
} from "./provider-handler.js";
import { ProviderHandlerRegistry } from "./provider-handler-registry.js";

/**
 * Generic provider handler for vendors without specific handlers.
 *
 * This handler provides a safe, conservative approach that should work
 * with most LLM providers that follow OpenAI-compatible APIs:
 * - Uses prompt-based JSON instructions
 * - Standard tool calling format (via Vercel AI SDK normalization)
 * - No vendor-specific features
 * - Maximum compatibility
 *
 * Use Cases:
 * - Fallback for unknown vendors
 * - New providers before dedicated handler is created
 * - Testing with custom/local models
 * - Providers like: Cohere, Together, Replicate, Ollama, etc.
 *
 * Strategy:
 * - Conservative, prompt-based approach
 * - Relies on Vercel AI SDK to normalize vendor differences
 * - Works with any provider that Vercel AI SDK supports
 */
export class GenericHandler implements ProviderHandler {
  readonly vendor: string;

  constructor(vendor: string = "unknown") {
    this.vendor = vendor;
  }

  /**
   * Prepare request with standard parameters.
   *
   * Generic Strategy:
   * - Use standard message format
   * - Include tools if provided (Vercel AI SDK will normalize)
   * - No vendor-specific parameters
   * - Let Vercel AI SDK handle vendor differences
   */
  prepareRequest(
    messages: LlmMessage[],
    tools: ToolSchema[] | null,
    _outputSchema: OutputSchema | null, // unused in generic handler, but required by interface
    options?: {
      outputMode?: OutputMode;
      temperature?: number;
      maxTokens?: number;
      topP?: number;
      [key: string]: unknown;
    }
  ): PreparedRequest {
    const { outputMode, temperature, maxTokens, topP, ...rest } = options ?? {};

    const request: PreparedRequest = {
      messages: [...messages],
      ...rest,
    };

    // Add tools if provided (Vercel AI SDK will convert to vendor format)
    if (tools && tools.length > 0) {
      request.tools = tools;
    }

    // Add standard parameters if provided
    if (temperature !== undefined) {
      request.temperature = temperature;
    }
    if (maxTokens !== undefined) {
      request.maxTokens = maxTokens;
    }
    if (topP !== undefined) {
      request.topP = topP;
    }

    // Don't add responseFormat - not all vendors support it
    // Rely on prompt-based JSON instructions instead

    return request;
  }

  /**
   * Format system prompt with explicit JSON instructions.
   *
   * Generic Strategy:
   * - Use detailed prompt instructions (works with most models)
   * - Explicit JSON schema (since we can't assume response_format)
   * - Clear tool calling guidelines
   * - Maximum explicitness for compatibility
   * - Skip JSON schema for text mode (string return type)
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    let systemContent = basePrompt;
    const mode = this.determineOutputMode(outputSchema, outputMode);

    // Add tool calling instructions if tools available
    if (toolSchemas && toolSchemas.length > 0) {
      systemContent += `

TOOL CALLING RULES:
- You can call tools to gather information
- Make one tool call at a time
- Wait for tool results before making additional calls
- Use standard JSON function calling format
- Provide your final response after gathering needed information
`;
    }

    // Skip JSON schema for text mode
    if (mode === "text" || !outputSchema) {
      return systemContent;
    }

    // Add explicit JSON schema instructions
    // (since we can't rely on vendor-specific structured output)
    const schemaStr = JSON.stringify(outputSchema.schema, null, 2);
    systemContent += `

IMPORTANT: Return your final response as valid JSON matching this exact schema:
${schemaStr}

Rules:
- Return ONLY the JSON object, no markdown, no additional text
- Ensure all required fields are present
- Match the schema exactly
- Use double quotes for strings
- Do not include comments`;

    return systemContent;
  }

  /**
   * Return conservative capability flags.
   *
   * For generic handler, we assume minimal capabilities
   * to ensure maximum compatibility.
   */
  getCapabilities(): VendorCapabilities {
    return {
      nativeToolCalling: true, // Most modern LLMs support this via Vercel AI SDK
      structuredOutput: false, // Can't assume all vendors support response_format
      streaming: false, // Conservative - not all vendors support streaming
      vision: false, // Conservative - not all models support vision
      jsonMode: false, // Conservative - use prompt-based JSON instead
    };
  }

  /**
   * Determine output mode - generic handler always uses "hint" for schemas.
   *
   * Since we can't assume structured output support, we rely on
   * prompt-based instructions (hint mode) for JSON schema compliance.
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode {
    // Allow explicit override
    if (overrideMode) {
      return overrideMode;
    }

    // No schema means text mode
    if (!outputSchema) {
      return "text";
    }

    // Generic handler uses hint mode (prompt-based JSON instructions)
    // since we can't assume structured output support
    return "hint";
  }
}

// Register as fallback handler
ProviderHandlerRegistry.setFallbackHandler(GenericHandler);
