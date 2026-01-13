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
import type {
  ProviderHandler,
  VendorCapabilities,
  ToolSchema,
  OutputSchema,
  PreparedRequest,
  OutputMode,
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
      maxTokens?: number;
      topP?: number;
      [key: string]: unknown;
    }
  ): PreparedRequest {
    const { outputMode, temperature, maxTokens, topP, ...rest } = options ?? {};
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Convert messages to Vercel AI SDK format for OpenAI
    const convertedMessages = this.convertMessagesForOpenAI(messages);

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
      request.maxTokens = maxTokens;
    }
    if (topP !== undefined) {
      request.topP = topP;
    }

    // Skip structured output for text mode
    if (determinedMode === "text" || !outputSchema) {
      return request;
    }

    // CRITICAL: Add response_format for structured output
    // This is what makes OpenAI construct responses according to schema
    // rather than relying on prompt instructions alone

    // Transform schema for OpenAI strict mode
    // OpenAI requires additionalProperties: false on all object schemas
    const strictSchema = this.addAdditionalPropertiesFalse(outputSchema.schema);

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
      systemContent += `

IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time
- After receiving tool results, you can make additional calls if needed
- Once you have all needed information, provide your final response
`;
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
   * Since OpenAI has excellent structured output support via response_format,
   * we use strict mode by default for all schemas.
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

    // OpenAI has excellent structured output - always use strict
    return "strict";
  }

  // ==========================================================================
  // Private Helper Methods
  // ==========================================================================

  /**
   * Recursively add additionalProperties: false to all object schemas.
   *
   * OpenAI strict mode requires this for all object schemas.
   * Also ensures 'required' includes ALL property keys.
   *
   * See: https://platform.openai.com/docs/guides/structured-outputs
   */
  private addAdditionalPropertiesFalse(
    schema: Record<string, unknown>
  ): Record<string, unknown> {
    // Deep clone to avoid mutating original
    const result = JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
    this.addAdditionalPropertiesRecursive(result);
    return result;
  }

  /**
   * Recursively process schema for OpenAI strict mode compliance.
   */
  private addAdditionalPropertiesRecursive(obj: unknown): void {
    if (typeof obj !== "object" || obj === null) {
      return;
    }

    const record = obj as Record<string, unknown>;

    // If this is an object type, add additionalProperties: false
    // and ensure required includes all properties
    if (record.type === "object") {
      record.additionalProperties = false;

      // OpenAI strict mode: required must include ALL property keys
      if (record.properties && typeof record.properties === "object") {
        record.required = Object.keys(record.properties as Record<string, unknown>);
      }
    }

    // Process $defs (used for nested models)
    if (record.$defs && typeof record.$defs === "object") {
      for (const defSchema of Object.values(record.$defs as Record<string, unknown>)) {
        this.addAdditionalPropertiesRecursive(defSchema);
      }
    }

    // Process properties
    if (record.properties && typeof record.properties === "object") {
      for (const propSchema of Object.values(record.properties as Record<string, unknown>)) {
        this.addAdditionalPropertiesRecursive(propSchema);
      }
    }

    // Process items (for arrays)
    if (record.items) {
      this.addAdditionalPropertiesRecursive(record.items);
    }

    // Process anyOf, oneOf, allOf
    for (const key of ["anyOf", "oneOf", "allOf"] as const) {
      if (Array.isArray(record[key])) {
        for (const item of record[key] as unknown[]) {
          this.addAdditionalPropertiesRecursive(item);
        }
      }
    }
  }

  /**
   * Convert messages to Vercel AI SDK format for OpenAI.
   *
   * OpenAI via Vercel AI SDK requires specific message format for tool calls:
   * - Assistant with tool_calls → content array with "tool-call" parts
   * - Tool results → role "tool" with "tool-result" content parts
   *
   * This conversion ensures Vercel AI SDK properly converts to OpenAI's native format.
   */
  private convertMessagesForOpenAI(messages: LlmMessage[]): LlmMessage[] {
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
        // This is what Vercel AI SDK expects for proper OpenAI conversion
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
}

// Register with the registry
ProviderHandlerRegistry.register("openai", OpenAIHandler);
