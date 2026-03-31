/**
 * Generic provider handler for unknown/unsupported vendors.
 *
 * Provides sensible defaults using prompt-based approach similar to Claude.
 *
 * Based on Python's GenericHandler:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/generic_handler.py
 */

import type { LlmMessage } from "../types.js";
import { formatSystemPrompt as coreFormatSystemPrompt } from "@mcpmesh/core";
import {
  hasMediaParams,
  type ProviderHandler,
  type VendorCapabilities,
  type ToolSchema,
  type OutputSchema,
  type PreparedRequest,
  type OutputMode,
} from "./provider-handler.js";
import { ProviderHandlerRegistry } from "./provider-handler-registry.js";

/**
 * Generic provider handler for vendors without specific handlers.
 *
 * This handler provides a safe, conservative approach that should work
 * with most LLM providers that follow OpenAI-compatible APIs:
 * - Uses prompt-based JSON instructions
 * - Standard tool calling format (via Vercel AI SDK normalization)
 * - No vendor-specific features
 * - Maximum compatibility
 *
 * Use Cases:
 * - Fallback for unknown vendors
 * - New providers before dedicated handler is created
 * - Testing with custom/local models
 * - Providers like: Cohere, Together, Replicate, Ollama, etc.
 *
 * Strategy:
 * - Conservative, prompt-based approach
 * - Relies on Vercel AI SDK to normalize vendor differences
 * - Works with any provider that Vercel AI SDK supports
 */
export class GenericHandler implements ProviderHandler {
  readonly vendor: string;

  constructor(vendor: string = "unknown") {
    this.vendor = vendor;
  }

  /**
   * Prepare request with standard parameters.
   *
   * Generic Strategy:
   * - Use standard message format
   * - Include tools if provided (Vercel AI SDK will normalize)
   * - No vendor-specific parameters
   * - Let Vercel AI SDK handle vendor differences
   */
  prepareRequest(
    messages: LlmMessage[],
    tools: ToolSchema[] | null,
    _outputSchema: OutputSchema | null, // unused in generic handler, but required by interface
    options?: {
      outputMode?: OutputMode;
      temperature?: number;
      maxOutputTokens?: number;
      topP?: number;
      [key: string]: unknown;
    }
  ): PreparedRequest {
    const { outputMode, temperature, maxOutputTokens: maxTokens, topP, ...rest } = options ?? {};

    const request: PreparedRequest = {
      messages: [...messages],
      ...rest,
    };

    // Add tools if provided (Vercel AI SDK will convert to vendor format)
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

    // Don't add responseFormat - not all vendors support it
    // Rely on prompt-based JSON instructions instead

    return request;
  }

  /**
   * Format system prompt with explicit JSON instructions.
   * Delegates to Rust core.
   *
   * Generic Strategy:
   * - Use detailed prompt instructions (works with most models)
   * - Explicit JSON schema (since we can't assume response_format)
   * - Clear tool calling guidelines
   * - Maximum explicitness for compatibility
   * - Skip JSON schema for text mode (string return type)
   */
  formatSystemPrompt(
    basePrompt: string,
    toolSchemas: ToolSchema[] | null,
    outputSchema: OutputSchema | null,
    outputMode?: OutputMode
  ): string {
    const mode = this.determineOutputMode(outputSchema, outputMode);
    return coreFormatSystemPrompt(
      this.vendor,
      basePrompt,
      !!toolSchemas && toolSchemas.length > 0,
      hasMediaParams(toolSchemas),
      outputSchema ? JSON.stringify(outputSchema.schema) : undefined,
      outputSchema?.name ?? undefined,
      mode,
    );
  }

  /**
   * Return conservative capability flags.
   *
   * For generic handler, we assume minimal capabilities
   * to ensure maximum compatibility.
   */
  getCapabilities(): VendorCapabilities {
    return {
      nativeToolCalling: true, // Most modern LLMs support this via Vercel AI SDK
      structuredOutput: false, // Can't assume all vendors support response_format
      streaming: false, // Conservative - not all vendors support streaming
      vision: false, // Conservative - not all models support vision
      jsonMode: false, // Conservative - use prompt-based JSON instead
    };
  }

  /**
   * Determine output mode - generic handler always uses "hint" for schemas.
   *
   * Since we can't assume structured output support, we rely on
   * prompt-based instructions (hint mode) for JSON schema compliance.
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

    // Generic handler uses hint mode (prompt-based JSON instructions)
    // since we can't assume structured output support
    return "hint";
  }
}

// Register as fallback handler
ProviderHandlerRegistry.setFallbackHandler(GenericHandler);
