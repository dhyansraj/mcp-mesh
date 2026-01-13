/**
 * Provider handler registry for vendor-specific LLM behavior.
 *
 * Manages selection and instantiation of provider handlers based on vendor name.
 *
 * Based on Python's ProviderHandlerRegistry:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/provider_handler_registry.py
 */

import { createDebug } from "../debug.js";
import type { ProviderHandler } from "./provider-handler.js";

const debug = createDebug("provider-handler-registry");

// ============================================================================
// Handler Constructor Type
// ============================================================================

/**
 * Constructor type for provider handlers.
 */
export type ProviderHandlerConstructor = new () => ProviderHandler;

// ============================================================================
// Registry Singleton
// ============================================================================

/**
 * Registry for provider-specific handlers.
 *
 * Manages mapping from vendor names to handler classes and provides
 * handler selection logic. Handlers customize LLM API calls for
 * optimal performance with each vendor.
 *
 * Vendor Mapping:
 * - "anthropic" -> ClaudeHandler
 * - "openai" -> OpenAIHandler
 * - "unknown" or others -> GenericHandler
 *
 * Usage:
 * ```typescript
 * const handler = ProviderHandlerRegistry.getHandler("anthropic");
 * const request = handler.prepareRequest(messages, tools, outputSchema);
 * const systemPrompt = handler.formatSystemPrompt(base, tools, outputSchema);
 * ```
 *
 * Extensibility:
 * ```typescript
 * ProviderHandlerRegistry.register("cohere", CohereHandler);
 * ```
 */
export class ProviderHandlerRegistry {
  /** Built-in vendor mappings */
  private static handlers: Map<string, ProviderHandlerConstructor> = new Map();

  /** Cache of instantiated handlers (singleton per vendor) */
  private static instances: Map<string, ProviderHandler> = new Map();

  /** Fallback handler class (set by generic-handler.ts) */
  private static fallbackHandlerClass: ProviderHandlerConstructor | null = null;

  /**
   * Register a custom provider handler.
   *
   * Allows runtime registration of new handlers without modifying registry code.
   *
   * @param vendor - Vendor name (e.g., "cohere", "gemini", "together")
   * @param handlerClass - Handler class (must implement ProviderHandler)
   *
   * @example
   * ```typescript
   * class CohereHandler implements ProviderHandler {
   *   // ...
   * }
   *
   * ProviderHandlerRegistry.register("cohere", CohereHandler);
   * ```
   */
  static register(vendor: string, handlerClass: ProviderHandlerConstructor): void {
    const normalizedVendor = vendor.toLowerCase().trim();
    this.handlers.set(normalizedVendor, handlerClass);
    debug(`Registered provider handler: ${normalizedVendor} -> ${handlerClass.name}`);

    // Clear cached instance if it exists (force re-instantiation)
    if (this.instances.has(normalizedVendor)) {
      this.instances.delete(normalizedVendor);
    }
  }

  /**
   * Set the fallback handler class.
   *
   * Called by generic-handler.ts during module initialization.
   *
   * @param handlerClass - Fallback handler class
   */
  static setFallbackHandler(handlerClass: ProviderHandlerConstructor): void {
    this.fallbackHandlerClass = handlerClass;
    debug(`Set fallback handler: ${handlerClass.name}`);
  }

  /**
   * Get provider handler for vendor.
   *
   * Selection Logic:
   * 1. If vendor matches registered handler -> use that handler
   * 2. If vendor is null or "unknown" -> use GenericHandler
   * 3. If vendor unknown -> use GenericHandler with warning
   *
   * Handlers are cached (singleton per vendor) for performance.
   *
   * @param vendor - Vendor name from model string (e.g., "anthropic", "openai")
   * @returns Provider handler instance for the vendor
   *
   * @example
   * ```typescript
   * // Get Claude handler
   * const handler = ProviderHandlerRegistry.getHandler("anthropic");
   *
   * // Get OpenAI handler
   * const handler = ProviderHandlerRegistry.getHandler("openai");
   *
   * // Get generic fallback
   * const handler = ProviderHandlerRegistry.getHandler("unknown");
   * ```
   */
  static getHandler(vendor: string | null): ProviderHandler {
    // Normalize vendor name (handle null, empty string)
    const normalizedVendor = (vendor ?? "unknown").toLowerCase().trim();

    // Check cache first
    const cached = this.instances.get(normalizedVendor);
    if (cached) {
      debug(`Using cached handler for vendor: ${normalizedVendor}`);
      return cached;
    }

    // Get handler class (or fallback to Generic)
    let handlerClass = this.handlers.get(normalizedVendor);
    let handler: ProviderHandler;

    if (handlerClass) {
      debug(`Selected ${handlerClass.name} for vendor: ${normalizedVendor}`);
      handler = new handlerClass();
    } else {
      // Use fallback handler
      if (!this.fallbackHandlerClass) {
        throw new Error(
          `No handler registered for vendor '${normalizedVendor}' and no fallback handler set. ` +
          `Import provider-handlers/index.ts to initialize handlers.`
        );
      }

      if (normalizedVendor !== "unknown") {
        debug(`No specific handler for vendor '${normalizedVendor}', using GenericHandler`);
      } else {
        debug(`Using GenericHandler for unknown vendor`);
      }

      handler = new this.fallbackHandlerClass();
    }

    // Cache the instance
    this.instances.set(normalizedVendor, handler);
    debug(`Instantiated handler: ${handler.constructor.name} for vendor: ${normalizedVendor}`);

    return handler;
  }

  /**
   * List all registered vendors and their handlers.
   *
   * @returns Map of vendor name -> handler class name
   *
   * @example
   * ```typescript
   * const vendors = ProviderHandlerRegistry.listVendors();
   * // Map { 'anthropic' => 'ClaudeHandler', 'openai' => 'OpenAIHandler' }
   * ```
   */
  static listVendors(): Map<string, string> {
    const result = new Map<string, string>();
    for (const [vendor, handlerClass] of this.handlers) {
      result.set(vendor, handlerClass.name);
    }
    return result;
  }

  /**
   * Clear cached handler instances.
   *
   * Useful for testing or when handler behavior needs to be reset.
   * Next getHandler() call will create fresh instances.
   */
  static clearCache(): void {
    this.instances.clear();
    debug(`Cleared provider handler cache`);
  }

  /**
   * Check if a handler is registered for a vendor.
   *
   * @param vendor - Vendor name
   * @returns True if a specific handler is registered
   */
  static hasHandler(vendor: string): boolean {
    return this.handlers.has(vendor.toLowerCase().trim());
  }
}
