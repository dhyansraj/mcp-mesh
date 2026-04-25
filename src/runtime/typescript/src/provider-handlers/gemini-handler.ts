/**
 * Gemini/Google provider handler for Gemini 3.x models.
 *
 * Optimized for Gemini models (Gemini 3 Flash Preview, Gemini 2.0 Flash, etc.)
 * using Google's best practices for tool calling and structured output.
 *
 * Features:
 * - Native structured output via response_format (via Vercel AI SDK)
 * - Native function calling support
 * - Support for Gemini 2.x and 3.x models
 * - Large context windows (up to 2M tokens)
 *
 * Based on Python's GeminiHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/gemini_handler.py
 *
 * Reference:
 * - https://ai.google.dev/gemini-api/docs
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

const debug = createDebug("gemini-handler");

/**
 * Provider handler for Google Gemini models.
 *
 * Gemini Characteristics:
 * - Native structured output via response_format (Vercel AI SDK translates)
 * - Native function calling support
 * - Large context windows (1M-2M tokens)
 * - Multimodal support (text, images, video, audio)
 * - Works well with concise, focused prompts
 *
 * Key Similarities with OpenAI:
 * - Uses response_format for structured output (via Vercel AI SDK)
 * - Native function calling format
 * - Similar schema enforcement requirements
 *
 * Supported Models (via Vercel AI SDK):
 * - gemini-3-flash-preview (reasoning support)
 * - gemini-3-pro-preview (advanced reasoning)
 * - gemini-2.0-flash (fast, efficient)
 * - gemini-2.0-flash-lite (fastest, most efficient)
 * - gemini-1.5-pro (high capability)
 * - gemini-1.5-flash (balanced)
 */
export class GeminiHandler implements ProviderHandler {
  readonly vendor = "google";

  /**
   * Prepare request parameters for Gemini API via Vercel AI SDK.
   *
   * Gemini Strategy:
   * - Use response_format parameter for structured JSON output
   * - Vercel AI SDK handles translation to Gemini's native format
   * - Skip structured output for text mode (string return types)
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
      // Vercel AI SDK translates this to Gemini's native format
      const sanitizedSchema = sanitizeSchemaForStructuredOutput(outputSchema.schema);
      const strictSchema = makeSchemaStrict(sanitizedSchema, { addAllRequired: true });

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
   * Format system prompt for Gemini with output mode support.
   * Delegates to Rust core.
   *
   * Gemini Strategy:
   * - strict mode: Brief JSON note (response_format handles schema)
   * - hint mode: Detailed JSON schema instructions in prompt
   * - text mode: No JSON instructions
   *
   * When tools are present with strict mode, downgrades to hint mode
   * because generateObject() doesn't support tools.
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    let mode = this.determineOutputMode(outputSchema, outputMode);
    if (mode === "strict" && toolSchemas && toolSchemas.length > 0) {
      mode = "hint";
    }
    return coreFormatSystemPrompt(
      "gemini",
      basePrompt,
      !!toolSchemas && toolSchemas.length > 0,
      hasMediaParams(toolSchemas),
      outputSchema ? JSON.stringify(outputSchema.schema) : undefined,
      outputSchema?.name ?? undefined,
      mode,
    );
  }

  /**
   * Return Gemini-specific capabilities.
   */
  getCapabilities(): VendorCapabilities {
    return {
      nativeToolCalling: true, // Gemini has native function calling
      structuredOutput: true, // Supports structured output via response_format
      streaming: true, // Supports streaming
      vision: true, // Gemini supports multimodal (images, video, audio)
      jsonMode: true, // Native JSON mode via response_format
    };
  }

  /**
   * Determine output mode - Gemini uses strict mode for schemas.
   *
   * Uses the default implementation since Gemini has good structured output support.
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode {
    return defaultDetermineOutputMode(outputSchema, overrideMode);
  }
}

// Register with the registry
// Use "gemini" as vendor name to match model prefix (e.g., "gemini/gemini-3-flash-preview")
// This is consistent with Python SDK's registration
ProviderHandlerRegistry.register("gemini", GeminiHandler);

// Also register under "vertex_ai" — same Gemini model family, same prompt-shaping
// rules (HINT mode for tool calls, STRICT mode for tool-free structured output);
// only the auth/transport differs (IAM via @ai-sdk/google-vertex vs API key via
// @ai-sdk/google). Mirrors Python's GeminiHandler registry alias.
ProviderHandlerRegistry.register("vertex_ai", GeminiHandler);
