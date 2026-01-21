/**
 * Claude/Anthropic provider handler.
 *
 * Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
 * using Anthropic's best practices for tool calling and JSON responses.
 *
 * Supports three output modes for performance/reliability tradeoffs:
 * - strict: Use response_format for guaranteed schema compliance (slowest, 100% reliable)
 * - hint: Use prompt-based JSON instructions (medium speed, ~95% reliable)
 * - text: Plain text output for str return types (fastest)
 *
 * Features:
 * - Anti-XML tool calling instructions
 * - Output mode optimization based on return type
 *
 * Note: Prompt caching is not yet implemented for AI SDK v6.
 * TODO: Re-enable via experimental_providerOptions when AI SDK v6 supports it.
 *
 * Based on Python's ClaudeHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/claude_handler.py
 */

import { createDebug } from "../debug.js";
import type { LlmMessage } from "../types.js";
import {
  convertMessagesToVercelFormat,
  makeSchemaStrict,
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
 * - Native structured output via response_format (requires strict schema)
 * - Native tool calling (via Anthropic messages API)
 * - Performs best with anti-XML tool calling instructions
 *
 * Output Modes:
 * - strict: response_format with JSON schema (slowest, guaranteed valid JSON)
 * - hint: JSON schema in prompt (medium speed, usually valid JSON)
 * - text: Plain text output for str return types (fastest)
 *
 * Best Practices (from Anthropic docs):
 * - Use response_format for guaranteed JSON schema compliance
 * - Schema must have additionalProperties: false on all objects
 * - Add anti-XML instructions to prevent <invoke> style tool calls
 * - Use one tool call at a time for better reliability
 */
export class ClaudeHandler implements ProviderHandler {
  readonly vendor = "anthropic";

  /**
   * Prepare request parameters for Claude API with output mode support.
   *
   * Output Mode Strategy:
   * - strict: Use response_format for guaranteed JSON schema compliance (slowest)
   * - hint: No response_format, rely on prompt instructions (medium speed)
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

    // For "hint" mode, append JSON instructions to the system prompt
    // This is the fast, prompt-based approach instead of slow generateObject()
    if (determinedMode === "hint" && outputSchema) {
      convertedMessages = this.appendJsonInstructionsToSystemPrompt(
        convertedMessages,
        outputSchema
      );
      debug(`Using hint mode with JSON instructions in prompt for schema: ${outputSchema.name}`);
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

    // Only add response_format in "strict" mode (not used for Claude anymore)
    if (determinedMode === "strict" && outputSchema) {
      // Claude requires additionalProperties: false on all object types
      // Unlike OpenAI/Gemini, Claude doesn't require all properties in 'required'
      const strictSchema = makeSchemaStrict(outputSchema.schema, { addAllRequired: false });
      request.responseFormat = {
        type: "json_schema",
        jsonSchema: {
          name: outputSchema.name,
          schema: strictSchema,
          strict: false, // Allow optional fields with defaults
        },
      };
      debug(`Using strict mode with response_format for schema: ${outputSchema.name}`);
    }

    return request;
  }

  /**
   * Format system prompt for Claude with output mode support.
   *
   * Output Mode Strategy:
   * - strict: Minimal JSON instructions (response_format handles schema)
   * - hint: Add detailed JSON schema instructions in prompt
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

    if (determinedMode === "strict") {
      // Strict mode: Minimal instructions (response_format handles schema)
      if (outputSchema) {
        systemContent += `

Your final response will be structured as JSON matching the ${outputSchema.name} format.`;
      }
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

      systemContent += `

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
      structuredOutput: true, // Native response_format support via Vercel AI SDK
      streaming: true, // Supports streaming
      vision: true, // Claude 3+ supports vision
      jsonMode: true, // Native JSON mode via response_format
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

  // ==========================================================================
  // Private Helper Methods
  // ==========================================================================

  /**
   * Append JSON schema instructions to the system prompt for "hint" mode.
   *
   * This enables fast, prompt-based structured output instead of slow generateObject().
   * Claude is excellent at following detailed instructions, so this approach is
   * ~95% reliable while being much faster than native structured output.
   *
   * @param messages - Messages with system prompt
   * @param outputSchema - Schema to include in instructions
   * @returns Messages with updated system prompt
   */
  private appendJsonInstructionsToSystemPrompt(
    messages: LlmMessage[],
    outputSchema: OutputSchema
  ): LlmMessage[] {
    const properties = (outputSchema.schema.properties ?? {}) as Record<
      string,
      { type?: string; description?: string }
    >;
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
      Object.entries(properties).map(([k, v]) => [k, `<${v.type ?? "value"}>`])
    );

    const jsonInstructions = `

RESPONSE FORMAT:
You MUST respond with valid JSON matching the ${outputSchema.name} schema:
{
${fieldsText}
}

Example format:
${JSON.stringify(exampleFormat, null, 2)}

CRITICAL: Your response must be ONLY the raw JSON object.
- DO NOT wrap in markdown code fences (\`\`\`json or \`\`\`)
- DO NOT include any text before or after the JSON
- Start directly with { and end with }`;

    // Find and update system message, or prepend one if none exists
    const updatedMessages = [...messages];
    const systemIndex = updatedMessages.findIndex((m) => m.role === "system");

    if (systemIndex >= 0) {
      // Append to existing system message
      const systemMsg = updatedMessages[systemIndex];
      updatedMessages[systemIndex] = {
        ...systemMsg,
        content: (systemMsg.content ?? "") + jsonInstructions,
      };
    } else {
      // Prepend new system message with JSON instructions
      updatedMessages.unshift({
        role: "system",
        content: jsonInstructions.trim(),
      });
    }

    return updatedMessages;
  }
}

// Register with the registry
ProviderHandlerRegistry.register("anthropic", ClaudeHandler);
