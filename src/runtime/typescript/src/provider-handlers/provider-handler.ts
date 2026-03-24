/**
 * Base provider handler interface for vendor-specific LLM behavior.
 *
 * This module defines the interface for provider-specific handlers
 * that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
 *
 * Based on Python's BaseProviderHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/base_provider_handler.py
 */

import { createDebug } from "../debug.js";
import type { LlmMessage } from "../types.js";

const debug = createDebug("provider-handler");

// ============================================================================
// Types
// ============================================================================

/**
 * Output mode for structured responses.
 *
 * - strict: Use response_format for guaranteed schema compliance (slowest, 100% reliable)
 * - hint: Use prompt-based JSON instructions (medium speed, ~95% reliable)
 * - text: Plain text output for string return types (fastest)
 */
export type OutputMode = "strict" | "hint" | "text";

/**
 * Vendor capability flags.
 */
export interface VendorCapabilities {
  /** Native function/tool calling support */
  nativeToolCalling: boolean;
  /** Native structured output via response_format */
  structuredOutput: boolean;
  /** Streaming response support */
  streaming: boolean;
  /** Vision/image input support */
  vision: boolean;
  /** JSON mode via response_format */
  jsonMode: boolean;
  /** Prompt caching support (Claude) */
  promptCaching?: boolean;
}

/**
 * Tool schema in OpenAI format.
 */
export interface ToolSchema {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, unknown>;
  };
}

/**
 * Prepared request parameters for the LLM API.
 */
export interface PreparedRequest {
  /** Messages to send (may be transformed) */
  messages: LlmMessage[];
  /** Tools in vendor-specific format (if provided) */
  tools?: ToolSchema[];
  /** Response format configuration (for structured output) */
  responseFormat?: {
    type: "json_schema";
    jsonSchema: {
      name: string;
      schema: Record<string, unknown>;
      strict?: boolean;
    };
  };
  /** Additional vendor-specific parameters */
  [key: string]: unknown;
}

/**
 * JSON Schema for output type validation.
 */
export interface OutputSchema {
  /** Schema name (typically the type name) */
  name: string;
  /** JSON Schema definition */
  schema: Record<string, unknown>;
  /** Number of fields in the schema */
  fieldCount?: number;
  /** Whether the schema has nested objects */
  hasNestedObjects?: boolean;
}

// ============================================================================
// Shared Utilities
// ============================================================================

/**
 * AI SDK v6 tool result output format.
 */
export interface ToolResultOutput {
  type: "text" | "json";
  value: unknown;
}

/**
 * Wrap tool result content in AI SDK v6 ToolResultOutput format.
 *
 * AI SDK v6 requires tool result output to be structured as:
 * - { type: 'text', value: string } for text content
 * - { type: 'json', value: JSONValue } for JSON content
 *
 * @param content - Raw tool result content (string)
 * @returns Properly formatted ToolResultOutput
 */
export function wrapToolResultOutput(content: string | null | undefined): ToolResultOutput {
  if (content === null || content === undefined || content === "") {
    return { type: "text", value: "" };
  }

  try {
    const parsed = JSON.parse(content);
    // JSON-parsed strings should use text type
    if (typeof parsed === "string") {
      return { type: "text", value: parsed };
    }
    // null/undefined from JSON.parse should use text
    if (parsed === null || parsed === undefined) {
      return { type: "text", value: content };
    }
    // Objects, arrays, numbers, booleans use json type
    return { type: "json", value: parsed };
  } catch {
    // Not valid JSON - treat as text
    return { type: "text", value: content };
  }
}

/**
 * Convert messages to Vercel AI SDK format for multi-turn tool conversations.
 *
 * Both Anthropic and OpenAI require specific message formats for tool calls:
 * - Assistant messages with tool_calls → content array with "tool-call" parts
 * - Tool result messages → content array with "tool-result" parts
 *
 * This conversion ensures Vercel AI SDK properly converts to each provider's native format.
 *
 * @param messages - Messages in OpenAI-style format (from mesh network)
 * @returns Messages in Vercel AI SDK format
 */
export function convertMessagesToVercelFormat(messages: LlmMessage[]): LlmMessage[] {
  // Build a map of tool_call_id -> tool_name from assistant messages
  // This is needed because tool result messages may not include the tool name,
  // but Gemini API requires it (function_response.name cannot be empty)
  const toolCallIdToName: Map<string, string> = new Map();
  for (const msg of messages) {
    if (msg.role === "assistant" && msg.tool_calls) {
      for (const tc of msg.tool_calls) {
        toolCallIdToName.set(tc.id, tc.function.name);
      }
    }
  }

  return messages.map((msg) => {
    // System and user messages pass through
    // Preserve array content (multipart: text + images) for user messages
    if (msg.role === "system" || msg.role === "user") {
      return {
        role: msg.role,
        content: Array.isArray(msg.content) ? msg.content : (msg.content ?? ""),
      };
    }

    // Assistant messages - convert tool_calls to content blocks
    if (msg.role === "assistant") {
      const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;

      if (!hasToolCalls) {
        return {
          role: "assistant",
          content: msg.content ?? "",
        };
      }

      // For tool calls, use content blocks format
      // This is what Vercel AI SDK expects for proper provider conversion
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const contentParts: any[] = [];

      // Add text content if present (assistant content is always a string)
      if (typeof msg.content === "string" && msg.content) {
        contentParts.push({ type: "text", text: msg.content });
      }

      // Add tool calls as content blocks
      // AI SDK v6 uses 'input' instead of 'args' for tool call parameters
      for (const tc of msg.tool_calls!) {
        // Parse arguments with fallback for malformed JSON
        let input: unknown = {};
        try {
          input = JSON.parse(tc.function.arguments);
        } catch (err) {
          debug(
            `Failed to parse tool call arguments for ${tc.function.name}: ${err}. Using empty object.`
          );
        }

        contentParts.push({
          type: "tool-call",
          toolCallId: tc.id,
          toolName: tc.function.name,
          input,
        });
      }

      return {
        role: "assistant",
        content: contentParts,
      } as unknown as LlmMessage;
    }

    // Tool result messages - convert to content blocks with tool-result type
    if (msg.role === "tool") {
      // Get tool name from message, or look it up from the tool call map
      // Gemini API requires function_response.name to be non-empty
      const toolCallId = msg.tool_call_id ?? "";
      const toolName = msg.name || toolCallIdToName.get(toolCallId) || "";

      if (!toolName) {
        debug(`Warning: Tool result for call ${toolCallId} has no tool name. Gemini API may reject this.`);
      }

      return {
        role: "tool",
        content: [{
          type: "tool-result",
          toolCallId,
          toolName,
          output: wrapToolResultOutput(typeof msg.content === "string" ? msg.content : null),
        }],
      } as unknown as LlmMessage;
    }

    // Fallback - return as-is
    return msg;
  });
}

// ============================================================================
// Shared Constants
// ============================================================================

/**
 * Base tool calling instructions shared across all providers.
 *
 * Claude handler adds anti-XML instruction on top of this.
 */
export const BASE_TOOL_INSTRUCTIONS = `
IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time
- After receiving tool results, you can make additional calls if needed
- Once you have all needed information, provide your final response
`;

/**
 * Anti-XML instruction for Claude (prevents <invoke> style tool calls).
 */
export const CLAUDE_ANTI_XML_INSTRUCTION = `- NEVER use XML-style syntax like <invoke name="tool_name"/>`;

/**
 * Decision guide shared across all providers.
 *
 * Helps LLMs decide when to call tools vs. return JSON directly.
 * Used in both strict mode (with tools) and hint mode.
 */
export const DECISION_GUIDE = `
DECISION GUIDE:
- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.
- After calling a tool and receiving results, STOP calling tools and return your final JSON response.`;

// ============================================================================
// Shared Schema Utilities
// ============================================================================

/**
 * Keywords that are validation-only and not supported by LLM structured output APIs.
 */
const UNSUPPORTED_SCHEMA_KEYWORDS = new Set([
  "minimum",
  "maximum",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "minLength",
  "maxLength",
  "minItems",
  "maxItems",
  "pattern",
  "multipleOf",
]);

// ---- Shared schema walker ------------------------------------------------

type SchemaVisitor = (node: Record<string, unknown>) => void;

/**
 * Walk a JSON Schema tree, invoking `visitor` on every schema node.
 *
 * Recurses into $defs, properties, items, prefixItems, and anyOf/oneOf/allOf.
 */
function walkSchemaRecursive(obj: unknown, visitor: SchemaVisitor): void {
  if (typeof obj !== "object" || obj === null) return;
  const record = obj as Record<string, unknown>;

  visitor(record);

  // Recurse into $defs
  if (record.$defs && typeof record.$defs === "object") {
    for (const def of Object.values(record.$defs as Record<string, unknown>)) {
      walkSchemaRecursive(def, visitor);
    }
  }

  // Recurse into properties
  if (record.properties && typeof record.properties === "object") {
    for (const prop of Object.values(record.properties as Record<string, unknown>)) {
      walkSchemaRecursive(prop, visitor);
    }
  }

  // Recurse into items (single schema or legacy array form)
  if (record.items) {
    if (Array.isArray(record.items)) {
      for (const item of record.items as unknown[]) {
        walkSchemaRecursive(item, visitor);
      }
    } else {
      walkSchemaRecursive(record.items, visitor);
    }
  }

  // Recurse into prefixItems (tuple validation in JSON Schema draft 2020-12)
  if (Array.isArray(record.prefixItems)) {
    for (const item of record.prefixItems as unknown[]) {
      walkSchemaRecursive(item, visitor);
    }
  }

  // Recurse into anyOf/oneOf/allOf
  for (const keyword of ["anyOf", "oneOf", "allOf"]) {
    if (Array.isArray(record[keyword])) {
      for (const variant of record[keyword] as unknown[]) {
        walkSchemaRecursive(variant, visitor);
      }
    }
  }
}

// ---- Public schema utilities ---------------------------------------------

/**
 * Sanitize a JSON schema by removing validation keywords unsupported by LLM APIs.
 *
 * LLM structured output APIs (Claude, OpenAI, Gemini) typically only support
 * the structural parts of JSON Schema, not validation constraints. This function
 * removes unsupported keywords to ensure uniform behavior across all providers.
 *
 * @param schema - JSON schema to sanitize
 * @returns New schema with unsupported validation keywords removed
 */
export function sanitizeSchemaForStructuredOutput(
  schema: Record<string, unknown>
): Record<string, unknown> {
  // Deep clone to avoid mutating original
  const result = JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
  walkSchemaRecursive(result, (node) => {
    for (const keyword of UNSUPPORTED_SCHEMA_KEYWORDS) {
      delete node[keyword];
    }
  });
  return result;
}

/**
 * Options for making a schema strict.
 */
export interface MakeSchemaStrictOptions {
  /**
   * If true, set 'required' to include ALL property keys.
   * OpenAI and Gemini require this; Claude does not.
   * Default: true
   */
  addAllRequired?: boolean;
}

/**
 * Make a JSON schema strict for structured output.
 *
 * This is a shared utility used by OpenAI, Gemini, and Claude handlers.
 * Adds additionalProperties: false to all object types and optionally
 * ensures 'required' includes all property keys.
 *
 * @param schema - JSON schema to make strict
 * @param options - Configuration options
 * @returns New schema with strict constraints (original not mutated)
 */
export function makeSchemaStrict(
  schema: Record<string, unknown>,
  options: MakeSchemaStrictOptions = {}
): Record<string, unknown> {
  const { addAllRequired = true } = options;

  // Deep clone to avoid mutating original
  const result = JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
  walkSchemaRecursive(result, (node) => {
    if (node.type === "object") {
      node.additionalProperties = false;
      if (addAllRequired && node.properties && typeof node.properties === "object") {
        node.required = Object.keys(node.properties as Record<string, unknown>);
      }
    }
  });
  return result;
}

/**
 * Build human-readable schema description and example JSON for prompt-based hints.
 *
 * Extracts field names, types, required markers, and descriptions from an
 * OutputSchema and returns formatted text suitable for embedding in a system prompt.
 *
 * @param outputSchema - The output schema to describe
 * @returns fieldsText (multi-line field list) and exampleJson (pretty-printed example)
 */
export function buildSchemaPromptContent(outputSchema: OutputSchema): {
  fieldsText: string;
  exampleJson: string;
} {
  const properties = (outputSchema.schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = (outputSchema.schema?.required ?? []) as string[];

  const fieldDescriptions: string[] = [];
  const exampleObj: Record<string, string> = {};

  for (const [fieldName, fieldSchema] of Object.entries(properties)) {
    const fieldType = (fieldSchema.type as string) ?? "any";
    const isRequired = required.includes(fieldName);
    const reqMarker = isRequired ? " (required)" : " (optional)";
    const desc = fieldSchema.description as string | undefined;
    const descText = desc ? ` - ${desc}` : "";
    fieldDescriptions.push(`  - ${fieldName}: ${fieldType}${reqMarker}${descText}`);
    exampleObj[fieldName] = `<${fieldType}>`;
  }

  return {
    fieldsText: fieldDescriptions.join("\n"),
    exampleJson: JSON.stringify(exampleObj, null, 2),
  };
}

/**
 * Build the common baseline for prepareRequest across all providers.
 *
 * Handles the boilerplate shared by all handlers:
 * - Destructure standard options (outputMode, temperature, maxOutputTokens, topP)
 * - Convert messages to Vercel AI SDK format
 * - Attach tools and standard parameters when provided
 *
 * @param messages - Raw messages from mesh
 * @param tools - Tool schemas (or null)
 * @param options - Provider options bag
 * @returns The partially-built request, extracted outputMode, and remaining options
 */
export function prepareRequestBaseline(
  messages: LlmMessage[],
  tools: ToolSchema[] | null,
  options?: Record<string, unknown>,
): { request: PreparedRequest; outputMode?: string; rest: Record<string, unknown> } {
  const { outputMode, temperature, maxOutputTokens: maxTokens, topP, ...rest } = (options ?? {}) as {
    outputMode?: string;
    temperature?: number;
    maxOutputTokens?: number;
    topP?: number;
    [key: string]: unknown;
  };
  const convertedMessages = convertMessagesToVercelFormat(messages);
  const request: PreparedRequest = { messages: convertedMessages, ...rest };

  if (tools && tools.length > 0) { request.tools = tools; }
  if (temperature !== undefined) { request.temperature = temperature; }
  if (maxTokens !== undefined) { request.maxOutputTokens = maxTokens; }
  if (topP !== undefined) { request.topP = topP; }

  return { request, outputMode: outputMode as string | undefined, rest };
}

/**
 * Default implementation of determineOutputMode.
 *
 * Most providers (OpenAI, Gemini) use strict mode for schemas.
 * Claude overrides this with more sophisticated logic.
 *
 * @param outputSchema - The output schema (null for string return type)
 * @param overrideMode - Optional explicit mode override
 * @returns The determined output mode
 */
export function defaultDetermineOutputMode(
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

  // Default: use strict mode for schemas
  return "strict";
}

// ============================================================================
// Provider Handler Interface
// ============================================================================

/**
 * Interface for provider-specific LLM handlers.
 *
 * Each vendor (Claude, OpenAI, Gemini, etc.) can have its own handler
 * that customizes request preparation, system prompt formatting, and
 * response parsing to work optimally with that vendor's API.
 *
 * Handler Selection:
 *   The ProviderHandlerRegistry selects handlers based on the vendor
 *   extracted from the model string (e.g., "anthropic/claude-sonnet-4-5" → "anthropic").
 *
 * Extensibility:
 *   New handlers can be added by:
 *   1. Implementing ProviderHandler interface
 *   2. Registering in ProviderHandlerRegistry
 *
 * @example
 * ```typescript
 * class MyHandler implements ProviderHandler {
 *   readonly vendor = "myvendor";
 *
 *   prepareRequest(messages, tools, outputSchema, options) {
 *     return { messages, tools, ...vendorSpecificParams };
 *   }
 *
 *   formatSystemPrompt(basePrompt, toolSchemas, outputSchema) {
 *     return basePrompt + "\n\nVendor-specific instructions...";
 *   }
 *
 *   getCapabilities() {
 *     return { nativeToolCalling: true, structuredOutput: true, ... };
 *   }
 * }
 * ```
 */
export interface ProviderHandler {
  /** Vendor name (e.g., "anthropic", "openai", "google") */
  readonly vendor: string;

  /**
   * Prepare vendor-specific request parameters.
   *
   * This method allows customization of the request sent to the LLM provider.
   * For example:
   * - Claude: Add cache_control for prompt caching
   * - OpenAI: Add response_format for structured output
   * - Gemini: Add generation config
   *
   * @param messages - List of messages to send
   * @param tools - Optional list of tool schemas (OpenAI format)
   * @param outputSchema - Optional schema for expected response
   * @param options - Additional options (outputMode, temperature, etc.)
   * @returns Prepared request parameters
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
  ): PreparedRequest;

  /**
   * Format system prompt for vendor-specific requirements.
   *
   * Different vendors have different best practices for system prompts:
   * - Claude: Prefers detailed instructions, handles XML well, needs anti-XML for tools
   * - OpenAI: Structured output mode makes JSON instructions optional
   * - Gemini: System instructions separate from messages
   *
   * @param basePrompt - Base system prompt (from template or config)
   * @param toolSchemas - Optional list of tool schemas (if tools available)
   * @param outputSchema - Optional schema for response validation
   * @param outputMode - Optional override for output mode
   * @returns Formatted system prompt string optimized for this vendor
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string;

  /**
   * Get vendor-specific capability flags.
   *
   * @returns Dictionary of capability flags
   */
  getCapabilities(): VendorCapabilities;

  /**
   * Determine the optimal output mode based on schema complexity.
   *
   * @param outputSchema - The output schema (null for string return type)
   * @param overrideMode - Optional explicit mode override
   * @returns The determined output mode
   */
  determineOutputMode(
    outputSchema: OutputSchema | null,
    overrideMode?: OutputMode
  ): OutputMode;
}
