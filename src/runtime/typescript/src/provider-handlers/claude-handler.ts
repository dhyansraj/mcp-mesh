/**
 * Claude/Anthropic provider handler.
 *
 * Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
 * using Anthropic's best practices for tool calling and JSON responses.
 *
 * Dual output strategy (matching Python SDK):
 * - formatSystemPrompt (direct calls): HINT mode — prompt-based JSON instructions
 *   with DECISION GUIDE for callers that don't control the provider-side API call.
 * - prepareRequest (mesh delegation): native response_format with strict JSON schema
 *   for provider-side enforcement. The caller controls the full API call and can
 *   pass response_format directly to the Anthropic API.
 *
 * Features:
 * - Anti-XML tool calling instructions
 * - DECISION GUIDE for tool vs. direct JSON response decisions
 * - Native response_format for structured output in mesh delegation
 *
 * Note: Prompt caching is not yet implemented for AI SDK v6.
 * TODO: Re-enable via experimental_providerOptions when AI SDK v6 supports it.
 */

import { createDebug } from "../debug.js";
import type { LlmMessage } from "../types.js";
import { formatSystemPrompt as coreFormatSystemPrompt } from "@mcpmesh/core";
import {
  sanitizeSchemaForStructuredOutput,
  makeSchemaStrict,
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

const debug = createDebug("claude-handler");

// ============================================================================
// Claude Handler Implementation
// ============================================================================

/**
 * Provider handler for Claude/Anthropic models.
 *
 * Claude Characteristics:
 * - Excellent at following detailed instructions
 * - Native tool calling (via Anthropic messages API)
 * - Performs best with anti-XML tool calling instructions
 *
 * Dual output strategy (matching Python SDK):
 * - formatSystemPrompt: Adds brief JSON note in strict mode, detailed HINT
 *   instructions in hint mode. Used for belt-and-suspenders prompt guidance.
 * - prepareRequest: Sets native response_format with strict JSON schema when
 *   outputMode is "strict". Used for mesh delegation where the provider
 *   controls the full API call.
 *
 * Best Practices (from Anthropic docs):
 * - Add anti-XML instructions to prevent <invoke> style tool calls
 * - Use one tool call at a time for better reliability
 */
export class ClaudeHandler implements ProviderHandler {
  readonly vendor = "anthropic";

  /**
   * Prepare request parameters for Claude API with output mode support.
   *
   * Output Mode Strategy:
   * - strict: Set response_format with strict JSON schema (native enforcement)
   * - hint: No response_format, rely on prompt instructions (~95% reliable)
   * - text: No response_format, plain text output (fastest)
   *
   * Message Format (Anthropic-specific):
   * - Assistant messages with tool_calls → content blocks with type "tool-call"
   * - Tool result messages → content blocks with type "tool-result"
   * This is required for Vercel AI SDK to properly convert to Anthropic's native format.
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

    // Only add response_format in "strict" mode (native enforcement)
    // Hint mode relies on prompt instructions instead
    if (determinedMode === "strict") {
      const sanitizedSchema = sanitizeSchemaForStructuredOutput(outputSchema.schema);
      const strictSchema = makeSchemaStrict(sanitizedSchema, { addAllRequired: true });

      request.responseFormat = {
        type: "json_schema",
        jsonSchema: {
          name: outputSchema.name,
          schema: strictSchema,
          strict: true,
        },
      };

      debug(`Using response_format with strict schema: ${outputSchema.name}`);
    } else if (determinedMode === "hint" && outputSchema) {
      debug(`Using hint mode (JSON instructions added by formatSystemPrompt)`);
    }

    return request;
  }

  /**
   * Format system prompt for Claude with output mode support.
   * Delegates to Rust core.
   *
   * Output Mode Strategy:
   * - strict: Brief JSON note (response_format handles schema enforcement)
   * - hint: Add detailed JSON schema instructions with DECISION GUIDE in prompt
   * - text: No JSON instructions (plain text output)
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    const mode = this.determineOutputMode(outputSchema, outputMode);
    return coreFormatSystemPrompt(
      "anthropic",
      basePrompt,
      !!toolSchemas && toolSchemas.length > 0,
      hasMediaParams(toolSchemas),
      outputSchema ? JSON.stringify(outputSchema.schema) : undefined,
      outputSchema?.name ?? undefined,
      mode,
    );
  }

  /**
   * Return Claude-specific capabilities.
   */
  getCapabilities(): VendorCapabilities {
    return {
      nativeToolCalling: true, // Claude has native function calling
      structuredOutput: true, // Native response_format support in mesh delegation
      streaming: true, // Supports streaming
      vision: true, // Claude 3+ supports vision
      jsonMode: false, // No native JSON mode used
      promptCaching: false, // TODO: Re-enable via experimental_providerOptions
    };
  }

  /**
   * Determine the optimal output mode for Claude.
   *
   * Uses the default implementation which returns "strict" for schemas.
   * This enables native response_format enforcement in mesh delegation
   * (provider-side), matching the Python SDK behavior.
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode {
    return defaultDetermineOutputMode(outputSchema, overrideMode);
  }

}

// Register with the registry
ProviderHandlerRegistry.register("anthropic", ClaudeHandler);
