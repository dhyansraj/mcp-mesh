/**
 * OpenAI provider handler.
 *
 * Optimized for OpenAI models (GPT-4, GPT-4 Turbo, GPT-3.5-turbo)
 * using OpenAI's native structured output capabilities.
 *
 * Based on Python's OpenAIHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/openai_handler.py
 */

import { createDebug } from "../debug.js";
import type { LlmMessage } from "../types.js";
import {
  convertMessagesToVercelFormat,
  makeSchemaStrict,
  defaultDetermineOutputMode,
  BASE_TOOL_INSTRUCTIONS,
  type ProviderHandler,
  type VendorCapabilities,
  type ToolSchema,
  type OutputSchema,
  type PreparedRequest,
  type OutputMode,
} from "./provider-handler.js";
import { ProviderHandlerRegistry } from "./provider-handler-registry.js";

const debug = createDebug("openai-handler");

/**
 * Provider handler for OpenAI models.
 *
 * OpenAI Characteristics:
 * - Native structured output via response_format parameter
 * - Strict JSON schema enforcement
 * - Built-in function calling
 * - Works best with concise, focused prompts
 * - response_format ensures valid JSON matching schema
 *
 * Key Difference from Claude:
 * - Uses response_format instead of prompt-based JSON instructions
 * - OpenAI API guarantees JSON schema compliance
 * - More strict parsing, less tolerance for malformed JSON
 * - Shorter system prompts work better
 *
 * Supported Models:
 * - gpt-4-turbo-preview and later
 * - gpt-4-0125-preview and later
 * - gpt-3.5-turbo-0125 and later
 * - All gpt-4o models
 *
 * Reference: https://platform.openai.com/docs/guides/structured-outputs
 */
export class OpenAIHandler implements ProviderHandler {
  readonly vendor = "openai";

  /**
   * Prepare request parameters for OpenAI API with structured output.
   *
   * OpenAI Strategy:
   * - Use response_format parameter for guaranteed JSON schema compliance
   * - This is the KEY difference from Claude handler
   * - response_format.json_schema ensures the response matches output schema
   * - Skip structured output for text mode (string return types)
   *
   * Message Format (OpenAI-specific):
   * - Assistant messages with tool_calls → content blocks with type "tool-call"
   * - Tool result messages → content blocks with type "tool-result"
   * This is required for Vercel AI SDK to properly convert to OpenAI's native format.
   */
  prepareRequest(
    messages: LlmMessage[],
    tools: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    options?: {
      outputMode?: OutputMode;
      temperature?: number;
      maxOutputTokens?: number;
      topP?: number;
      [key: string]: unknown;
    }
  ): PreparedRequest {
    const { outputMode, temperature, maxOutputTokens: maxTokens, topP, ...rest } = options ?? {};
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Convert messages to Vercel AI SDK format (shared utility)
    const convertedMessages = convertMessagesToVercelFormat(messages);

    const request: PreparedRequest = {
      messages: convertedMessages,
      ...rest,
    };

    // Add tools if provided
    if (tools && tools.length > 0) {
      request.tools = tools;
    }

    // Add standard parameters if provided
    if (temperature !== undefined) {
      request.temperature = temperature;
    }
    if (maxTokens !== undefined) {
      request.maxOutputTokens = maxTokens;
    }
    if (topP !== undefined) {
      request.topP = topP;
    }

    // Skip structured output for text mode or no schema
    if (determinedMode === "text" || !outputSchema) {
      return request;
    }

    // Only add response_format in "strict" mode
    // Hint mode relies on prompt instructions instead
    if (determinedMode === "strict") {
      // Transform schema for OpenAI strict mode
      // OpenAI requires additionalProperties: false and all properties in required
      const strictSchema = makeSchemaStrict(outputSchema.schema, { addAllRequired: true });

      // OpenAI structured output format
      // See: https://platform.openai.com/docs/guides/structured-outputs
      request.responseFormat = {
        type: "json_schema",
        jsonSchema: {
          name: outputSchema.name,
          schema: strictSchema,
          strict: true, // Enforce schema compliance
        },
      };

      debug(`Using response_format with strict schema: ${outputSchema.name}`);
    }

    return request;
  }

  /**
   * Format system prompt for OpenAI (concise approach).
   *
   * OpenAI Strategy:
   * 1. Use base prompt as-is
   * 2. Add tool calling instructions if tools present
   * 3. NO JSON schema instructions (response_format handles this)
   * 4. Keep prompt concise - OpenAI works well with shorter prompts
   * 5. Skip JSON note for text mode (string return type)
   *
   * Key Difference from Claude:
   * - No JSON schema in prompt (response_format ensures compliance)
   * - Shorter, more focused instructions
   * - Let response_format handle output structure
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    let systemContent = basePrompt;
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Add tool calling instructions if tools available
    if (toolSchemas && toolSchemas.length > 0) {
      systemContent += BASE_TOOL_INSTRUCTIONS;
    }

    // Skip JSON note for text mode
    if (determinedMode === "text" || !outputSchema) {
      return systemContent;
    }

    // NOTE: We do NOT add JSON schema instructions here!
    // OpenAI's response_format parameter handles JSON structure automatically.
    // Adding explicit JSON instructions can actually confuse the model.

    // Optional: Add a brief note that response should be JSON
    // (though response_format enforces this anyway)
    systemContent += `

Your final response will be structured as JSON matching the ${outputSchema.name} format.`;

    return systemContent;
  }

  /**
   * Return OpenAI-specific capabilities.
   */
  getCapabilities(): VendorCapabilities {
    return {
      nativeToolCalling: true, // OpenAI has native function calling
      structuredOutput: true, // Native response_format support!
      streaming: true, // Supports streaming
      vision: true, // GPT-4V and later support vision
      jsonMode: true, // Has dedicated JSON mode via response_format
    };
  }

  /**
   * Determine output mode - OpenAI always uses strict mode for schemas.
   *
   * Uses the default implementation since OpenAI has excellent structured output support.
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode {
    return defaultDetermineOutputMode(outputSchema, overrideMode);
  }
}

// Register with the registry
ProviderHandlerRegistry.register("openai", OpenAIHandler);
