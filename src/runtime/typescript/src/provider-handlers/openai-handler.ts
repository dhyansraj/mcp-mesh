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
   * Format system prompt for OpenAI with output mode support.
   *
   * OpenAI Strategy:
   * - strict mode: Brief JSON note (response_format handles schema)
   * - hint mode: Detailed JSON schema instructions in prompt
   * - text mode: No JSON instructions
   *
   * When tools are present, llm-provider forces "hint" mode because
   * generateObject() doesn't support tools, so we need prompt-based
   * JSON instructions to ensure structured output.
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

    // Skip JSON instructions for text mode or no schema
    if (determinedMode === "text" || !outputSchema) {
      return systemContent;
    }

    // Strict mode: Brief note (response_format handles enforcement)
    if (determinedMode === "strict") {
      systemContent += `

Your final response will be structured as JSON matching the ${outputSchema.name} format.`;
      return systemContent;
    }

    // Hint mode: Add detailed JSON schema instructions
    // This is used when tools are present (can't use generateObject)
    const schema = outputSchema.schema;
    const properties = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
    const required = (schema.required ?? []) as string[];

    // Build human-readable schema description
    const fieldDescriptions: string[] = [];
    for (const [fieldName, fieldSchema] of Object.entries(properties)) {
      const fieldType = fieldSchema.type ?? "any";
      const isRequired = required.includes(fieldName);
      const reqMarker = isRequired ? " (required)" : " (optional)";
      const desc = fieldSchema.description as string | undefined;
      const descText = desc ? ` - ${desc}` : "";
      fieldDescriptions.push(`  - ${fieldName}: ${fieldType}${reqMarker}${descText}`);
    }

    const fieldsText = fieldDescriptions.join("\n");
    const exampleObj: Record<string, string> = {};
    for (const [k, v] of Object.entries(properties)) {
      exampleObj[k] = `<${v.type ?? "value"}>`;
    }

    systemContent += `

FINAL RESPONSE FORMAT:
After gathering all needed information using tools, your FINAL response MUST be valid JSON matching this schema:
{
${fieldsText}
}

Example format:
${JSON.stringify(exampleObj, null, 2)}

IMPORTANT:
- First, use the available tools to gather information
- Only after you have all the data, provide your final JSON response
- The final response must be ONLY valid JSON - no markdown code fences, no preamble text`;

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
