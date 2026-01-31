package io.mcpmesh.ai.handlers;

import org.springframework.ai.chat.model.ChatModel;

import java.util.List;
import java.util.Map;

/**
 * Interface for vendor-specific LLM provider handlers.
 *
 * <p>Each handler knows how to format messages and call the LLM API
 * for a specific vendor (Anthropic, OpenAI, Gemini, etc.).
 *
 * <p>This pattern allows vendor-specific optimizations:
 * <ul>
 *   <li>Message format conversion</li>
 *   <li>System prompt formatting</li>
 *   <li>Schema strictness handling</li>
 *   <li>Vendor-specific features (prompt caching, etc.)</li>
 * </ul>
 *
 * <h2>Adding a New Provider</h2>
 * <pre>{@code
 * public class CohereHandler implements LlmProviderHandler {
 *     @Override
 *     public String getVendor() { return "cohere"; }
 *
 *     @Override
 *     public String generateWithMessages(ChatModel model,
 *             List<Map<String, Object>> messages, Map<String, Object> options) {
 *         // Cohere-specific message conversion and call
 *     }
 * }
 *
 * // Register at startup
 * LlmProviderHandlerRegistry.register("cohere", CohereHandler.class);
 * }</pre>
 *
 * @see LlmProviderHandlerRegistry
 */
public interface LlmProviderHandler {

    /**
     * Get the vendor name this handler supports.
     *
     * @return Vendor name (e.g., "anthropic", "openai", "gemini")
     */
    String getVendor();

    /**
     * Generate a response with full message history.
     *
     * <p>Converts the generic message format to vendor-specific format
     * and calls the ChatModel.
     *
     * @param model    The Spring AI ChatModel for this vendor
     * @param messages List of messages with role and content
     * @param options  Generation options (max_tokens, temperature, etc.)
     * @return The generated response text
     */
    String generateWithMessages(
        ChatModel model,
        List<Map<String, Object>> messages,
        Map<String, Object> options
    );

    /**
     * Get the capabilities supported by this vendor.
     *
     * @return Map of capability names to boolean values
     */
    default Map<String, Boolean> getCapabilities() {
        return Map.of(
            "native_tool_calling", true,
            "structured_output", true,
            "streaming", true,
            "vision", false,
            "json_mode", true
        );
    }

    /**
     * Get vendor-specific aliases.
     *
     * <p>For example, "anthropic" handler also handles "claude".
     *
     * @return Array of aliases for this vendor
     */
    default String[] getAliases() {
        return new String[0];
    }
}
