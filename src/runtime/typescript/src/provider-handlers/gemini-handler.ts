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
import {
  convertMessagesToVercelFormat,
  makeSchemaStrict,
  sanitizeSchemaForStructuredOutput,
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
    const { outputMode, temperature, maxOutputTokens: maxTokens, topP, ...rest } = options ?? {};
    const determinedMode = this.determineOutputMode(outputSchema, outputMode);

    // Convert messages to Vercel AI SDK format (shared utility)
    const convertedMessages = convertMessagesToVercelFormat(messages);

    const request: PreparedRequest = {
      messages: convertedMessages,
      ...rest,
    };

    // Add tools if provided
    // Vercel AI SDK will convert to Gemini's function_declarations format
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
   *
   * Gemini Strategy:
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

    // Add DECISION GUIDE when tools are present to help Gemini know when NOT to use tools
    let decisionGuide = "";
    if (toolSchemas && toolSchemas.length > 0) {
      decisionGuide = `
DECISION GUIDE:
- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.
`;
    }

    systemContent += `
${decisionGuide}
FINAL RESPONSE FORMAT:
After gathering all needed information using tools, your FINAL response MUST be valid JSON matching this schema:
{
${fieldsText}
}

Example format:
${JSON.stringify(exampleObj, null, 2)}

IMPORTANT:
- First, use the available tools to gather information if needed
- Only after you have all the data, provide your final JSON response
- The final response must be ONLY valid JSON - no markdown code fences, no preamble text`;

    return systemContent;
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
