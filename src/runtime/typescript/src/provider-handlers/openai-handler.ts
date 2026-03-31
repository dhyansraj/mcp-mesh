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
import { formatSystemPrompt as coreFormatSystemPrompt } from "@mcpmesh/core";
import {
  makeSchemaStrict,
  sanitizeSchemaForStructuredOutput,
  hasMediaParams,
  defaultDetermineOutputMode,
  prepareRequestBaseline,
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
    const { request, outputMode: extractedMode } = prepareRequestBaseline(messages, tools, options);
    const determinedMode = this.determineOutputMode(outputSchema, extractedMode as OutputMode);

    // Skip structured output for text mode or no schema
    if (determinedMode === "text" || !outputSchema) {
      return request;
    }

    // Only add response_format in "strict" mode
    // Hint mode relies on prompt instructions instead
    if (determinedMode === "strict") {
      // Transform schema for OpenAI strict mode
      // OpenAI requires additionalProperties: false and all properties in required
      const sanitizedSchema = sanitizeSchemaForStructuredOutput(outputSchema.schema);
      const strictSchema = makeSchemaStrict(sanitizedSchema, { addAllRequired: true });

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
   * Format system prompt for OpenAI with output mode support.
   * Delegates to Rust core.
   *
   * OpenAI Strategy:
   * - strict mode: Brief JSON note (response_format handles schema)
   * - hint mode: Detailed JSON schema instructions in prompt
   * - text mode: No JSON instructions
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    const mode = this.determineOutputMode(outputSchema, outputMode);
    return coreFormatSystemPrompt(
      "openai",
      basePrompt,
      !!toolSchemas && toolSchemas.length > 0,
      hasMediaParams(toolSchemas),
      outputSchema ? JSON.stringify(outputSchema.schema) : undefined,
      outputSchema?.name ?? undefined,
      mode,
    );
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
