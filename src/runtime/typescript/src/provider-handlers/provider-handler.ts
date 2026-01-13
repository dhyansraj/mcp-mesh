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
      for (const tc of msg.tool_calls!) {
        // Parse arguments with fallback for malformed JSON
        let args: unknown = {};
        try {
          args = JSON.parse(tc.function.arguments);
        } catch (err) {
          debug(
            `Failed to parse tool call arguments for ${tc.function.name}: ${err}. Using empty object.`
          );
        }

        contentParts.push({
          type: "tool-call",
          toolCallId: tc.id,
          toolName: tc.function.name,
          args,
        });
      }

      return {
        role: "assistant",
        content: contentParts,
      } as unknown as LlmMessage;
    }

    // Tool result messages - convert to content blocks with tool-result type
    if (msg.role === "tool") {
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

    // Fallback - return as-is
    return msg;
  });
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
      maxTokens?: number;
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
