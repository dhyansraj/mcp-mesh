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
 * - Automatic prompt caching for system messages (up to 90% cost reduction)
 * - Anti-XML tool calling instructions
 * - Output mode optimization based on return type
 *
 * Based on Python's ClaudeHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/claude_handler.py
 */

import { createDebug } from "../debug.js";
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

const debug = createDebug("claude-handler");

// ============================================================================
// Constants
// ============================================================================

/** Simple schema threshold - schemas with fewer fields use hint mode */
const SIMPLE_SCHEMA_FIELD_THRESHOLD = 5;

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
 * - Automatic prompt caching for cost optimization
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
 * - Use cache_control for system prompts to reduce costs
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
      maxTokens?: number;
      topP?: number;
      [key: string]: unknown;
    }
  ): PreparedRequest {
    const { outputMode, temperature, maxTokens, topP, ...rest } = options ?? {};
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Convert messages to Vercel AI SDK format for Anthropic
    const convertedMessages = this.convertMessagesForAnthropic(messages);

    // Apply prompt caching to system messages for cost optimization
    const cachedMessages = this.applyPromptCaching(convertedMessages);

    const request: PreparedRequest = {
      messages: cachedMessages,
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
      request.maxTokens = maxTokens;
    }
    if (topP !== undefined) {
      request.topP = topP;
    }

    // Only add response_format in "strict" mode
    if (determinedMode === "strict" && outputSchema) {
      // Claude requires additionalProperties: false on all object types
      const strictSchema = this.makeSchemaStrict(outputSchema.schema);
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
   * Convert messages to Vercel AI SDK format for Anthropic.
   *
   * Anthropic requires specific message format for tool calls:
   * - Assistant with tool_calls → content array with "tool-call" parts
   * - Tool results → role "tool" with "tool-result" content parts
   *
   * This conversion ensures Vercel AI SDK properly converts to Anthropic's native format.
   */
  private convertMessagesForAnthropic(messages: LlmMessage[]): LlmMessage[] {
    return messages.map((msg) => {
      if (msg.role === "system" || msg.role === "user") {
        return {
          role: msg.role,
          content: msg.content ?? "",
        };
      }

      if (msg.role === "assistant") {
        const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;

        if (!hasToolCalls) {
          return {
            role: "assistant",
            content: msg.content ?? "",
          };
        }

        // For tool calls, use content blocks format
        // This is what Vercel AI SDK expects for proper Anthropic conversion
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const contentParts: any[] = [];

        // Add text content if present
        if (msg.content) {
          contentParts.push({ type: "text", text: msg.content });
        }

        // Add tool calls as content blocks
        for (const tc of msg.tool_calls!) {
          contentParts.push({
            type: "tool-call",
            toolCallId: tc.id,
            toolName: tc.function.name,
            args: JSON.parse(tc.function.arguments),
          });
        }

        return {
          role: "assistant",
          content: contentParts,
        } as unknown as LlmMessage;
      }

      if (msg.role === "tool") {
        // Tool result message - Vercel AI SDK expects content as array with toolName
        return {
          role: "tool",
          content: [{
            type: "tool-result",
            toolCallId: msg.tool_call_id ?? "",
            toolName: msg.name ?? "",
            result: msg.content ?? "",
          }],
        } as unknown as LlmMessage;
      }

      // Fallback
      return msg;
    });
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
      systemContent += `

IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time
- NEVER use XML-style syntax like <invoke name="tool_name"/>
- After receiving tool results, you can make additional calls if needed
- Once you have all needed information, provide your final response
`;
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

IMPORTANT: Respond ONLY with valid JSON. No markdown code fences, no preamble text.`;
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
      promptCaching: true, // Automatic system prompt caching for cost savings
    };
  }

  /**
   * Determine the output mode based on schema complexity.
   *
   * Logic:
   * - If overrideMode specified, use it
   * - If no schema (string return type), use "text" mode
   * - If schema is simple (<5 fields, basic types), use "hint" mode
   * - Otherwise, use "strict" mode
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

    // Check if schema is simple
    if (this.isSimpleSchema(outputSchema)) {
      return "hint";
    }

    // Complex schema - use strict mode
    return "strict";
  }

  // ==========================================================================
  // Private Helper Methods
  // ==========================================================================

  /**
   * Check if a schema is simple enough for hint mode.
   *
   * Simple schema criteria:
   * - Less than 5 fields
   * - No nested objects (hasNestedObjects flag or $defs present)
   */
  private isSimpleSchema(outputSchema: OutputSchema): boolean {
    // Use pre-computed values if available
    if (outputSchema.fieldCount !== undefined) {
      if (outputSchema.fieldCount >= SIMPLE_SCHEMA_FIELD_THRESHOLD) {
        return false;
      }
    }

    if (outputSchema.hasNestedObjects !== undefined) {
      return !outputSchema.hasNestedObjects;
    }

    // Analyze schema directly
    const schema = outputSchema.schema;
    const properties = schema.properties as Record<string, unknown> | undefined;

    // Check field count
    if (properties && Object.keys(properties).length >= SIMPLE_SCHEMA_FIELD_THRESHOLD) {
      return false;
    }

    // Check for $defs (indicates nested models)
    if (schema.$defs) {
      return false;
    }

    // Check for nested objects in properties
    if (properties) {
      for (const fieldSchema of Object.values(properties)) {
        const fs = fieldSchema as Record<string, unknown>;
        // Check for nested objects
        if (fs.type === "object" && fs.properties) {
          return false;
        }
        // Check for $ref (nested model reference)
        if (fs.$ref) {
          return false;
        }
        // Check array items for complex types
        if (fs.type === "array") {
          const items = fs.items as Record<string, unknown> | undefined;
          if (items?.type === "object" || items?.$ref) {
            return false;
          }
        }
      }
    }

    return true;
  }

  /**
   * Make a JSON schema strict for Claude's structured output.
   *
   * Claude requires additionalProperties: false on all object types.
   * This recursively processes the schema to add this constraint.
   */
  private makeSchemaStrict(schema: Record<string, unknown>): Record<string, unknown> {
    if (typeof schema !== "object" || schema === null) {
      return schema;
    }

    const result = { ...schema };

    // If this is an object type, add additionalProperties: false
    if (result.type === "object") {
      result.additionalProperties = false;
    }

    // Recursively process nested schemas
    if (result.properties && typeof result.properties === "object") {
      result.properties = Object.fromEntries(
        Object.entries(result.properties as Record<string, unknown>).map(([k, v]) => [
          k,
          this.makeSchemaStrict(v as Record<string, unknown>),
        ])
      );
    }

    // Process $defs (used for nested models)
    if (result.$defs && typeof result.$defs === "object") {
      result.$defs = Object.fromEntries(
        Object.entries(result.$defs as Record<string, unknown>).map(([k, v]) => [
          k,
          this.makeSchemaStrict(v as Record<string, unknown>),
        ])
      );
    }

    // Process items for arrays
    if (result.items && typeof result.items === "object") {
      result.items = this.makeSchemaStrict(result.items as Record<string, unknown>);
    }

    // Process anyOf, oneOf, allOf
    for (const key of ["anyOf", "oneOf", "allOf"] as const) {
      if (Array.isArray(result[key])) {
        result[key] = (result[key] as Record<string, unknown>[]).map((s) =>
          this.makeSchemaStrict(s)
        );
      }
    }

    return result;
  }

  /**
   * Apply prompt caching to system messages for Claude.
   *
   * Claude's prompt caching feature caches the system prompt prefix,
   * reducing costs by up to 90% and improving latency for repeated calls.
   *
   * The cache_control with type "ephemeral" tells Claude to cache
   * this content for the duration of the session (typically 5 minutes).
   *
   * Reference: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
   */
  private applyPromptCaching(messages: LlmMessage[]): LlmMessage[] {
    const cachedMessages: LlmMessage[] = [];

    for (const msg of messages) {
      if (msg.role === "system") {
        const content = msg.content ?? "";

        // Convert string content to cached content block format
        // Note: This format is specific to Anthropic's API
        // Vercel AI SDK should preserve this structure
        const cachedMsg: LlmMessage = {
          role: "system",
          content: JSON.stringify([
            {
              type: "text",
              text: content,
              cache_control: { type: "ephemeral" },
            },
          ]),
        };

        cachedMessages.push(cachedMsg);
        debug(`Applied prompt caching to system message (${content.length} chars)`);
      } else {
        // Non-system messages pass through unchanged
        cachedMessages.push(msg);
      }
    }

    return cachedMessages;
  }
}

// Register with the registry
ProviderHandlerRegistry.register("anthropic", ClaudeHandler);
