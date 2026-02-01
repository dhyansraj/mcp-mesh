package io.mcpmesh.types;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Interface for LLM-powered agentic capabilities.
 *
 * <p>Instances are injected into methods annotated with {@code @MeshLlm}.
 * The agent handles the agentic loop: LLM generation, tool calling, and
 * response parsing.
 *
 * <h2>Fluent Builder API</h2>
 * <p>The recommended way to use this interface is via the fluent builder:
 *
 * <pre>{@code
 * // Simple prompt
 * String response = llm.request()
 *     .user("Hello, how are you?")
 *     .generate();
 *
 * // With system prompt and options
 * String response = llm.request()
 *     .system("You are a helpful assistant")
 *     .user("What is 2+2?")
 *     .maxTokens(500)
 *     .temperature(0.7)
 *     .generate();
 *
 * // Chat history from database (100s of messages)
 * List<Message> history = Message.fromMaps(redis.getHistory(sessionId));
 * String response = llm.request()
 *     .system("You are a customer support agent")
 *     .messages(history)
 *     .user(currentMessage)
 *     .generate();
 *
 * // With template context
 * String response = llm.request()
 *     .context("userName", "Alice")
 *     .context("domain", "travel")
 *     .user("Book a flight")
 *     .generate();
 *
 * // Structured output
 * AnalysisResult result = llm.request()
 *     .user("Analyze this data")
 *     .generate(AnalysisResult.class);
 * }</pre>
 *
 * <h2>Simple API (Backward Compatible)</h2>
 * <pre>{@code
 * // These convenience methods still work
 * String response = llm.generate("Hello");
 * Result result = llm.generate("Analyze", Result.class);
 * }</pre>
 *
 * @see io.mcpmesh.MeshLlm
 * @see io.mcpmesh.MeshLlmProvider
 */
public interface MeshLlmAgent {

    // =========================================================================
    // Fluent Builder Entry Point
    // =========================================================================

    /**
     * Start building a generation request.
     *
     * <p>Use the returned builder to add messages, set options, and execute.
     *
     * @return A new builder instance
     */
    GenerateBuilder request();

    // =========================================================================
    // Simple API (Backward Compatible)
    // =========================================================================

    /**
     * Generate a text response from the LLM.
     *
     * <p>Equivalent to {@code request().user(prompt).generate()}.
     *
     * @param prompt The user prompt
     * @return The LLM's text response
     */
    default String generate(String prompt) {
        return request().user(prompt).generate();
    }

    /**
     * Generate a structured response from the LLM.
     *
     * <p>Equivalent to {@code request().user(prompt).generate(responseType)}.
     *
     * @param <T>          The expected response type
     * @param prompt       The user prompt
     * @param responseType The class to deserialize the response into
     * @return The parsed response object
     */
    default <T> T generate(String prompt, Class<T> responseType) {
        return request().user(prompt).generate(responseType);
    }

    /**
     * Generate a text response asynchronously.
     *
     * @param prompt The user prompt
     * @return A future that completes with the response
     */
    default CompletableFuture<String> generateAsync(String prompt) {
        return request().user(prompt).generateAsync();
    }

    /**
     * Generate a structured response asynchronously.
     *
     * @param <T>          The expected response type
     * @param prompt       The user prompt
     * @param responseType The class to deserialize the response into
     * @return A future that completes with the parsed response
     */
    default <T> CompletableFuture<T> generateAsync(String prompt, Class<T> responseType) {
        return request().user(prompt).generateAsync(responseType);
    }

    // =========================================================================
    // Metadata
    // =========================================================================

    /**
     * Get the list of tools available to this LLM agent.
     *
     * @return List of available tool information
     */
    List<ToolInfo> getAvailableTools();

    /**
     * Check if the LLM provider is available.
     *
     * @return true if the provider is connected, false otherwise
     */
    boolean isAvailable();

    /**
     * Get the provider name (for direct mode) or endpoint (for mesh mode).
     *
     * @return Provider identifier
     */
    String getProvider();

    // =========================================================================
    // Builder Interface
    // =========================================================================

    /**
     * Fluent builder for constructing LLM generation requests.
     *
     * <p>Provides IDE autocomplete for all available options.
     */
    interface GenerateBuilder {

        // --- Messages ---

        /**
         * Add a system message.
         *
         * @param content The system prompt content
         * @return This builder for chaining
         */
        GenerateBuilder system(String content);

        /**
         * Add a user message.
         *
         * @param content The user message content
         * @return This builder for chaining
         */
        GenerateBuilder user(String content);

        /**
         * Add an assistant message.
         *
         * @param content The assistant message content
         * @return This builder for chaining
         */
        GenerateBuilder assistant(String content);

        /**
         * Add a message with custom role.
         *
         * @param role    The message role (system, user, assistant, tool)
         * @param content The message content
         * @return This builder for chaining
         */
        GenerateBuilder message(String role, String content);

        /**
         * Add a pre-built message.
         *
         * @param message The message to add
         * @return This builder for chaining
         */
        GenerateBuilder message(Message message);

        /**
         * Add multiple messages (e.g., chat history from database).
         *
         * @param messages List of messages to add
         * @return This builder for chaining
         */
        GenerateBuilder messages(List<Message> messages);

        // --- Generation Options ---

        /**
         * Set maximum tokens for the response.
         *
         * @param tokens Max tokens (overrides @MeshLlm setting)
         * @return This builder for chaining
         */
        GenerateBuilder maxTokens(int tokens);

        /**
         * Set temperature for generation.
         *
         * @param temperature Temperature 0.0-1.0 (overrides @MeshLlm setting)
         * @return This builder for chaining
         */
        GenerateBuilder temperature(double temperature);

        /**
         * Set top-p (nucleus sampling) for generation.
         *
         * @param topP Top-p value 0.0-1.0
         * @return This builder for chaining
         */
        GenerateBuilder topP(double topP);

        /**
         * Set stop sequences.
         *
         * @param sequences Sequences that will stop generation
         * @return This builder for chaining
         */
        GenerateBuilder stop(String... sequences);

        // --- Template Context ---

        /**
         * Set the entire context map for template rendering.
         *
         * @param context Map of template variables
         * @return This builder for chaining
         */
        GenerateBuilder context(Map<String, Object> context);

        /**
         * Add a single context variable for template rendering.
         *
         * @param key   Variable name
         * @param value Variable value
         * @return This builder for chaining
         */
        GenerateBuilder context(String key, Object value);

        /**
         * Set how runtime context merges with auto-populated context.
         *
         * @param mode Context merge mode
         * @return This builder for chaining
         */
        GenerateBuilder contextMode(ContextMode mode);

        // --- Execute ---

        /**
         * Execute the generation and return text response.
         *
         * @return The LLM's text response
         */
        String generate();

        /**
         * Execute the generation and parse to structured type.
         *
         * @param <T>          The expected response type
         * @param responseType The class to deserialize into
         * @return The parsed response object
         */
        <T> T generate(Class<T> responseType);

        /**
         * Execute the generation asynchronously.
         *
         * @return A future that completes with the text response
         */
        CompletableFuture<String> generateAsync();

        /**
         * Execute the generation asynchronously with structured output.
         *
         * @param <T>          The expected response type
         * @param responseType The class to deserialize into
         * @return A future that completes with the parsed response
         */
        <T> CompletableFuture<T> generateAsync(Class<T> responseType);

        /**
         * Get metadata from the last generation call.
         *
         * <p>Returns null if generate() hasn't been called yet.
         *
         * @return Metadata from last call, or null
         */
        GenerationMeta lastMeta();
    }

    // =========================================================================
    // Supporting Types
    // =========================================================================

    /**
     * A message in the conversation.
     *
     * @param role    The role: "system", "user", "assistant", or "tool"
     * @param content The message content
     */
    record Message(String role, String content) {

        /** Create a system message. */
        public static Message system(String content) {
            return new Message("system", content);
        }

        /** Create a user message. */
        public static Message user(String content) {
            return new Message("user", content);
        }

        /** Create an assistant message. */
        public static Message assistant(String content) {
            return new Message("assistant", content);
        }

        /** Create a tool result message. */
        public static Message tool(String content) {
            return new Message("tool", content);
        }

        /**
         * Create a message from a Map (common DB storage format).
         *
         * @param map Map with "role" and "content" keys
         * @return The message
         */
        public static Message fromMap(Map<String, String> map) {
            return new Message(map.get("role"), map.get("content"));
        }

        /**
         * Bulk convert from list of maps (e.g., Redis/DB results).
         *
         * @param maps List of maps with "role" and "content" keys
         * @return List of messages
         */
        public static List<Message> fromMaps(List<Map<String, String>> maps) {
            return maps.stream().map(Message::fromMap).toList();
        }

        /**
         * Convert this message to a Map.
         *
         * @return Map with "role" and "content" keys
         */
        public Map<String, String> toMap() {
            return Map.of("role", role, "content", content);
        }
    }

    /**
     * Metadata from a generation call.
     *
     * @param inputTokens  Number of input tokens
     * @param outputTokens Number of output tokens
     * @param totalTokens  Total tokens (input + output)
     * @param latencyMs    Total latency in milliseconds
     * @param iterations   Number of agentic loop iterations
     * @param model        The model used
     */
    record GenerationMeta(
        int inputTokens,
        int outputTokens,
        int totalTokens,
        long latencyMs,
        int iterations,
        String model
    ) {}

    /**
     * How runtime context merges with auto-populated context.
     */
    enum ContextMode {
        /** Runtime context is added after auto context (runtime wins on conflicts). */
        APPEND,
        /** Runtime context completely replaces auto context. */
        REPLACE,
        /** Runtime context is added before auto context (auto wins on conflicts). */
        PREPEND
    }

    /**
     * Information about an available tool.
     */
    record ToolInfo(
        String name,
        String description,
        String capability,
        String agentId,
        String endpoint,
        Map<String, Object> inputSchema
    ) {}
}
