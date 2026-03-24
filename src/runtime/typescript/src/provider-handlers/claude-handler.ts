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
import {
  sanitizeSchemaForStructuredOutput,
  makeSchemaStrict,
  defaultDetermineOutputMode,
  prepareRequestBaseline,
  buildSchemaPromptContent,
  BASE_TOOL_INSTRUCTIONS,
  CLAUDE_ANTI_XML_INSTRUCTION,
  DECISION_GUIDE,
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
    let systemContent = basePrompt;
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Add tool calling instructions if tools available
    // These prevent Claude from using XML-style <invoke> syntax
    if (toolSchemas && toolSchemas.length > 0) {
      // Use base instructions but insert anti-XML rule for Claude
      const instructions = BASE_TOOL_INSTRUCTIONS.replace(
        "- Make ONE tool call at a time",
        `- Make ONE tool call at a time\n${CLAUDE_ANTI_XML_INSTRUCTION}`
      );
      systemContent += instructions;
    }

    // Add output format instructions based on mode
    if (determinedMode === "text") {
      // Text mode: No JSON instructions
      return systemContent;
    }

    // Skip JSON instructions for no schema
    if (!outputSchema) {
      return systemContent;
    }

    // Strict mode: response_format handles enforcement.
    // When tools are present, add DECISION GUIDE so Claude knows when to
    // call tools vs return JSON directly (matches Java handler behavior).
    if (determinedMode === "strict") {
      if (toolSchemas && toolSchemas.length > 0) {
        systemContent += DECISION_GUIDE;
      }
      systemContent += `\n\nYour final response will be structured as JSON matching the ${outputSchema.name} format.`;
      return systemContent;
    }

    // Hint mode: Add detailed JSON schema instructions
    if (determinedMode === "hint" && outputSchema) {
      const { fieldsText, exampleJson } = buildSchemaPromptContent(outputSchema);

      // Add DECISION GUIDE when tools are present to help Claude know when NOT to use tools
      const decisionGuide = (toolSchemas && toolSchemas.length > 0) ? DECISION_GUIDE + "\n" : "";

      systemContent += `
${decisionGuide}
RESPONSE FORMAT:
You MUST respond with valid JSON matching this schema:
{
${fieldsText}
}

Example format:
${exampleJson}

CRITICAL: Your response must be ONLY the raw JSON object.
- DO NOT wrap in markdown code fences (\`\`\`json or \`\`\`)
- DO NOT include any text before or after the JSON
- Start directly with { and end with }`;
    }

    return systemContent;
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
