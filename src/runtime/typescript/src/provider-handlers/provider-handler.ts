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
    if (msg.role === "system" || msg.role === "user") {
      return {
        role: msg.role,
        content: msg.content ?? "",
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

      // Add text content if present
      if (msg.content) {
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
          output: wrapToolResultOutput(msg.content),
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
  stripUnsupportedKeywordsRecursive(result);
  return result;
}

/**
 * Recursively strip unsupported validation keywords from a schema object.
 *
 * @param obj - Schema object to process (mutated in place)
 */
function stripUnsupportedKeywordsRecursive(obj: unknown): void {
  if (typeof obj !== "object" || obj === null) {
    return;
  }

  const record = obj as Record<string, unknown>;

  // Remove unsupported keywords at this level
  for (const keyword of UNSUPPORTED_SCHEMA_KEYWORDS) {
    delete record[keyword];
  }

  // Process $defs (used for nested models)
  if (record.$defs && typeof record.$defs === "object") {
    for (const defSchema of Object.values(record.$defs as Record<string, unknown>)) {
      stripUnsupportedKeywordsRecursive(defSchema);
    }
  }

  // Process properties
  if (record.properties && typeof record.properties === "object") {
    for (const propSchema of Object.values(record.properties as Record<string, unknown>)) {
      stripUnsupportedKeywordsRecursive(propSchema);
    }
  }

  // Process items (for arrays)
  if (record.items) {
    if (Array.isArray(record.items)) {
      for (const item of record.items as unknown[]) {
        stripUnsupportedKeywordsRecursive(item);
      }
    } else {
      stripUnsupportedKeywordsRecursive(record.items);
    }
  }

  // Process prefixItems (tuple validation)
  if (Array.isArray(record.prefixItems)) {
    for (const item of record.prefixItems as unknown[]) {
      stripUnsupportedKeywordsRecursive(item);
    }
  }

  // Process anyOf, oneOf, allOf
  for (const key of ["anyOf", "oneOf", "allOf"]) {
    if (Array.isArray(record[key])) {
      for (const item of record[key] as unknown[]) {
        stripUnsupportedKeywordsRecursive(item);
      }
    }
  }
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
  addStrictConstraintsRecursive(result, addAllRequired);
  return result;
}

/**
 * Recursively add strict constraints to a schema object.
 *
 * @param obj - Schema object to process (mutated in place)
 * @param addAllRequired - Whether to set required to all property keys
 */
function addStrictConstraintsRecursive(obj: unknown, addAllRequired: boolean): void {
  if (typeof obj !== "object" || obj === null) {
    return;
  }

  const record = obj as Record<string, unknown>;

  // If this is an object type, add additionalProperties: false
  if (record.type === "object") {
    record.additionalProperties = false;

    // Optionally set required to include all property keys
    if (addAllRequired && record.properties && typeof record.properties === "object") {
      record.required = Object.keys(record.properties as Record<string, unknown>);
    }
  }

  // Process $defs (used for nested models)
  if (record.$defs && typeof record.$defs === "object") {
    for (const defSchema of Object.values(record.$defs as Record<string, unknown>)) {
      addStrictConstraintsRecursive(defSchema, addAllRequired);
    }
  }

  // Process properties
  if (record.properties && typeof record.properties === "object") {
    for (const propSchema of Object.values(record.properties as Record<string, unknown>)) {
      addStrictConstraintsRecursive(propSchema, addAllRequired);
    }
  }

  // Process items (for arrays)
  // items can be an object (single schema) or an array (tuple validation in older drafts)
  if (record.items) {
    if (Array.isArray(record.items)) {
      for (const item of record.items as unknown[]) {
        addStrictConstraintsRecursive(item, addAllRequired);
      }
    } else {
      addStrictConstraintsRecursive(record.items, addAllRequired);
    }
  }

  // Process prefixItems (tuple validation in JSON Schema draft 2020-12)
  if (Array.isArray(record.prefixItems)) {
    for (const item of record.prefixItems as unknown[]) {
      addStrictConstraintsRecursive(item, addAllRequired);
    }
  }

  // Process anyOf, oneOf, allOf
  for (const key of ["anyOf", "oneOf", "allOf"] as const) {
    if (Array.isArray(record[key])) {
      for (const item of record[key] as unknown[]) {
        addStrictConstraintsRecursive(item, addAllRequired);
      }
    }
  }
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
