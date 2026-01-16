/**
 * Provider-specific handlers for LLM vendors.
 *
 * This package provides vendor-specific customization for different LLM providers
 * (Claude, OpenAI, Gemini, etc.) to optimize API calls and response handling.
 *
 * Usage:
 * ```typescript
 * import { ProviderHandlerRegistry } from "@mcpmesh/sdk/provider-handlers";
 *
 * const handler = ProviderHandlerRegistry.getHandler("anthropic");
 * const request = handler.prepareRequest(messages, tools, outputSchema);
 * ```
 *
 * Based on Python's provider_handlers package:
 * src/runtime/python/_mcp_mesh/engine/provider_handlers/
 */

// Export types and utilities
export type {
  ProviderHandler,
  VendorCapabilities,
  ToolSchema,
  OutputSchema,
  PreparedRequest,
  OutputMode,
} from "./provider-handler.js";

export { convertMessagesToVercelFormat } from "./provider-handler.js";

// Export registry
export {
  ProviderHandlerRegistry,
  type ProviderHandlerConstructor,
} from "./provider-handler-registry.js";

// Import handlers to trigger their self-registration
// Order matters: generic-handler sets fallback, then specific handlers register
import "./generic-handler.js";
import "./claude-handler.js";
import "./openai-handler.js";
import "./gemini-handler.js";

// Re-export handler classes for direct use or extension
export { GenericHandler } from "./generic-handler.js";
export { ClaudeHandler } from "./claude-handler.js";
export { OpenAIHandler } from "./openai-handler.js";
export { GeminiHandler } from "./gemini-handler.js";
