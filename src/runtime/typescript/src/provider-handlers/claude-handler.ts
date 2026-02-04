/**
 * Claude/Anthropic provider handler.
 *
 * Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
 * using Anthropic's best practices for tool calling and JSON responses.
 *
 * Supports two output modes (TEXT + HINT only):
 * - hint: Use prompt-based JSON instructions with DECISION GUIDE (~95% reliable)
 * - text: Plain text output for str return types (fastest)
 *
 * Native response_format (strict mode) is NOT used due to cross-runtime
 * incompatibilities when tools are present, and grammar compilation overhead.
 *
 * Features:
 * - Anti-XML tool calling instructions
 * - DECISION GUIDE for tool vs. direct JSON response decisions
 *
 * Note: Prompt caching is not yet implemented for AI SDK v6.
 * TODO: Re-enable via experimental_providerOptions when AI SDK v6 supports it.
 */

import { createDebug } from "../debug.js";
import type { LlmMessage } from "../types.js";
import {
  convertMessagesToVercelFormat,
  BASE_TOOL_INSTRUCTIONS,
  CLAUDE_ANTI_XML_INSTRUCTION,
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
 * Output Modes (TEXT + HINT only):
 * - hint: JSON schema in prompt with DECISION GUIDE (~95% reliable)
 * - text: Plain text output for str return types (fastest)
 *
 * Native response_format (strict mode) is not used. HINT mode with
 * detailed prompt instructions provides sufficient reliability (~95%)
 * without cross-runtime incompatibilities and grammar compilation overhead.
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
   * Output Mode Strategy (TEXT + HINT only):
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
    const { outputMode, temperature, maxOutputTokens: maxTokens, topP, ...rest } = options ?? {};
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Convert messages to Vercel AI SDK format (shared utility)
    let convertedMessages = convertMessagesToVercelFormat(messages);

    // Note: In hint mode, JSON instructions are added by formatSystemPrompt() which
    // is called by llm-provider.ts before prepareRequest(). We don't duplicate here.
    // The formatSystemPrompt() method handles the DECISION GUIDE when tools are present.
    if (determinedMode === "hint" && outputSchema) {
      debug(`Using hint mode (JSON instructions added by formatSystemPrompt)`);
    }

    const request: PreparedRequest = {
      messages: convertedMessages,
      ...rest,
    };

    // Add tools if provided
    // Vercel AI SDK will convert OpenAI tool format to Anthropic's format
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

    return request;
  }

  /**
   * Format system prompt for Claude with output mode support.
   *
   * Output Mode Strategy (TEXT + HINT only):
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

    // Hint mode: Add detailed JSON schema instructions
    if (determinedMode === "hint" && outputSchema) {
      const properties = (outputSchema.schema.properties ?? {}) as Record<string, { type?: string; description?: string }>;
      const required = (outputSchema.schema.required ?? []) as string[];

      // Build human-readable schema description
      const fieldDescriptions: string[] = [];
      for (const [fieldName, fieldSchema] of Object.entries(properties)) {
        const fieldType = fieldSchema.type ?? "any";
        const isRequired = required.includes(fieldName);
        const reqMarker = isRequired ? " (required)" : " (optional)";
        const desc = fieldSchema.description ?? "";
        const descText = desc ? ` - ${desc}` : "";
        fieldDescriptions.push(`  - ${fieldName}: ${fieldType}${reqMarker}${descText}`);
      }

      const fieldsText = fieldDescriptions.join("\n");
      const exampleFormat = Object.fromEntries(
        Object.entries(properties).map(([k, v]) => [k, `<${(v as { type?: string }).type ?? "value"}>`])
      );

      // Add DECISION GUIDE when tools are present to help Claude know when NOT to use tools
      let decisionGuide = "";
      if (toolSchemas && toolSchemas.length > 0) {
        decisionGuide = `
DECISION GUIDE:
- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.
- After calling a tool and receiving results, STOP calling tools and return your final JSON response.
`;
      }

      systemContent += `
${decisionGuide}
RESPONSE FORMAT:
You MUST respond with valid JSON matching this schema:
{
${fieldsText}
}

Example format:
${JSON.stringify(exampleFormat, null, 2)}

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
      structuredOutput: false, // Uses HINT mode (prompt-based), not native response_format
      streaming: true, // Supports streaming
      vision: true, // Claude 3+ supports vision
      jsonMode: false, // No native JSON mode used
      promptCaching: false, // TODO: Re-enable via experimental_providerOptions
    };
  }

  /**
   * Determine the output mode based on schema complexity.
   *
   * Claude Strategy (Option A):
   * - Always use "hint" mode (prompt-based) for schemas, never "strict"
   * - Vercel AI SDK's generateObject() for Anthropic has issues with nested schemas
   * - Anthropic's native structured output is slow and requires beta header
   * - Prompt-based JSON instructions are fast and ~95% reliable for Claude
   *
   * Logic:
   * - If overrideMode specified, use it
   * - If no schema (string return type), use "text" mode
   * - If schema exists, always use "hint" mode (prompt-based)
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode {
    // Allow explicit override
    if (overrideMode) {
      return overrideMode;
    }

    // No schema means text mode (string return type)
    if (!outputSchema) {
      return "text";
    }

    // Always use hint mode for Claude - generateObject() has issues with Anthropic
    // and native structured output is slow. Prompt-based JSON is fast and reliable.
    return "hint";
  }

}

// Register with the registry
ProviderHandlerRegistry.register("anthropic", ClaudeHandler);
