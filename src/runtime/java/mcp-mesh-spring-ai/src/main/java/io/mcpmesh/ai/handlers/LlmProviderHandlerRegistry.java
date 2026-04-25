package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for LLM provider handlers.
 *
 * <p>Manages vendor-specific handlers using a plugin pattern:
 * <ul>
 *   <li>Built-in handlers for Anthropic, OpenAI, Gemini</li>
 *   <li>Runtime registration of custom handlers</li>
 *   <li>Automatic fallback to GenericHandler for unknown vendors</li>
 *   <li>Singleton caching for performance</li>
 * </ul>
 *
 * <h2>Usage</h2>
 * <pre>{@code
 * // Get handler for a vendor
 * LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler("anthropic");
 *
 * // Register custom handler
 * LlmProviderHandlerRegistry.register("cohere", CohereHandler.class);
 * }</pre>
 *
 * @see LlmProviderHandler
 */
public class LlmProviderHandlerRegistry {

    private static final Logger log = LoggerFactory.getLogger(LlmProviderHandlerRegistry.class);

    // Registered handler classes by vendor name
    private static final Map<String, Class<? extends LlmProviderHandler>> handlers = new HashMap<>();

    // Cached handler instances (singleton per vendor)
    private static final Map<String, LlmProviderHandler> instances = new ConcurrentHashMap<>();

    // Static initialization of built-in handlers
    static {
        register("anthropic", AnthropicHandler.class);
        register("claude", AnthropicHandler.class);  // Alias
        register("openai", OpenAiHandler.class);
        register("gpt", OpenAiHandler.class);        // Alias
        register("gemini", GeminiHandler.class);
        register("google", GeminiHandler.class);     // Alias
        // Vertex AI uses the same Gemini model family on the wire — same prompt-shaping,
        // same HINT-mode behavior with tools; only the auth/transport differs (IAM via
        // spring-ai-vertex-ai-gemini vs API key via spring-ai-google-genai).
        register("vertex_ai", GeminiHandler.class);  // Alias
        register("vertexai", GeminiHandler.class);   // Forgiving alias for "vertex_ai"
    }

    /**
     * Get a handler for the specified vendor.
     *
     * <p>Returns a cached instance if available, otherwise creates one.
     * Falls back to GenericHandler for unknown vendors.
     *
     * <p>Lookup order:
     * <ol>
     *   <li>Direct lookup of the raw provider name (covers explicit aliases like
     *       {@code "vertex_ai"}, {@code "anthropic"}, {@code "openai"} that don't
     *       follow the {@code "vendor/model"} form and that {@link #extractVendor}
     *       does not recognize as substrings).</li>
     *   <li>Fallback: extract a vendor from a model-string form
     *       (e.g., {@code "vertex_ai/gemini-2.0-flash"} → {@code "vertex_ai"})
     *       and look that up.</li>
     *   <li>Final fallback: {@link GenericHandler}.</li>
     * </ol>
     *
     * @param vendor The vendor name (e.g., "anthropic", "openai", "vertex_ai")
     *               or a model string (e.g., "vertex_ai/gemini-2.0-flash")
     * @return The handler instance
     */
    public static LlmProviderHandler getHandler(String vendor) {
        if (vendor == null || vendor.isEmpty()) {
            vendor = "unknown";
        }

        String normalizedRaw = vendor.toLowerCase().trim();

        // First: check direct registration (covers explicit provider names like
        // "vertex_ai", "vertexai", "anthropic", etc. that don't follow the
        // "vendor/model" form and that extractVendor() does not detect via
        // substring inference).
        LlmProviderHandler cached = instances.get(normalizedRaw);
        if (cached != null) {
            return cached;
        }
        Class<? extends LlmProviderHandler> handlerClass = handlers.get(normalizedRaw);
        String cacheKey = normalizedRaw;

        if (handlerClass == null) {
            // Second: fall back to vendor extraction from model-string form
            // ("anthropic/claude-..." -> "anthropic", "vertex_ai/gemini-..." -> "vertex_ai"
            // via slash split).
            String extracted = extractVendor(vendor).toLowerCase().trim();
            cached = instances.get(extracted);
            if (cached != null) {
                return cached;
            }
            handlerClass = handlers.get(extracted);
            cacheKey = extracted;
        }

        // Create new instance
        LlmProviderHandler handler;
        if (handlerClass != null) {
            try {
                handler = handlerClass.getDeclaredConstructor().newInstance();
                log.debug("Created handler for vendor '{}': {}", cacheKey, handlerClass.getSimpleName());
            } catch (Exception e) {
                log.error("Failed to instantiate handler for '{}', using GenericHandler", cacheKey, e);
                handler = new GenericHandler();
            }
        } else {
            log.warn("Unknown vendor '{}', using GenericHandler", cacheKey);
            handler = new GenericHandler();
        }

        // Cache under the resolved key (prefer extracted form when raw didn't match,
        // so future lookups via either form still hit a cached entry).
        instances.put(cacheKey, handler);
        return handler;
    }

    /**
     * Register a handler class for a vendor.
     *
     * @param vendor       The vendor name
     * @param handlerClass The handler class
     */
    public static void register(String vendor, Class<? extends LlmProviderHandler> handlerClass) {
        String normalizedVendor = vendor.toLowerCase().trim();
        handlers.put(normalizedVendor, handlerClass);
        // Clear cached instance if exists (allows re-registration)
        instances.remove(normalizedVendor);
        log.debug("Registered handler for vendor '{}': {}", normalizedVendor, handlerClass.getSimpleName());
    }

    /**
     * Check if a handler is registered for a vendor.
     *
     * @param vendor The vendor name
     * @return true if a handler is registered
     */
    public static boolean hasHandler(String vendor) {
        if (vendor == null || vendor.isEmpty()) {
            return false;
        }
        String normalizedRaw = vendor.toLowerCase().trim();
        // Mirror getHandler's two-tier lookup: direct match first (catches
        // "vertex_ai" and other explicit aliases), then extraction fallback.
        if (handlers.containsKey(normalizedRaw)) {
            return true;
        }
        return handlers.containsKey(extractVendor(vendor).toLowerCase().trim());
    }

    /**
     * List all registered vendors.
     *
     * @return Map of vendor names to handler class names
     */
    public static Map<String, String> listVendors() {
        Map<String, String> result = new HashMap<>();
        for (Map.Entry<String, Class<? extends LlmProviderHandler>> entry : handlers.entrySet()) {
            result.put(entry.getKey(), entry.getValue().getSimpleName());
        }
        return result;
    }

    /**
     * Clear the instance cache.
     *
     * <p>Useful for testing or when handlers need to be re-created.
     */
    public static void clearCache() {
        instances.clear();
        log.debug("Handler cache cleared");
    }

    /**
     * Extract vendor from a model string.
     *
     * <p>Handles formats like:
     * <ul>
     *   <li>"anthropic/claude-sonnet-4-5" → "anthropic"</li>
     *   <li>"openai/gpt-4" → "openai"</li>
     *   <li>"claude-sonnet-4-5" → "anthropic" (inferred)</li>
     *   <li>"gpt-4" → "openai" (inferred)</li>
     * </ul>
     *
     * @param model The model string
     * @return The vendor name
     */
    public static String extractVendor(String model) {
        if (model == null || model.isEmpty()) {
            return "unknown";
        }

        // Check for explicit vendor prefix (vendor/model)
        int slashIndex = model.indexOf('/');
        if (slashIndex > 0) {
            return model.substring(0, slashIndex).toLowerCase();
        }

        // Infer vendor from model name
        String lowerModel = model.toLowerCase();
        if (lowerModel.contains("claude") || lowerModel.contains("anthropic")) {
            return "anthropic";
        }
        if (lowerModel.contains("gpt") || lowerModel.contains("openai") || lowerModel.startsWith("o1")) {
            return "openai";
        }
        if (lowerModel.contains("gemini") || lowerModel.contains("google")) {
            return "gemini";
        }

        return "unknown";
    }
}
