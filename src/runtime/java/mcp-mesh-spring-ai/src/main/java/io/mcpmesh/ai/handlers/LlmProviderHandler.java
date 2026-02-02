package io.mcpmesh.ai.handlers;

import org.springframework.ai.chat.model.ChatModel;

import java.util.*;

/**
 * Interface for vendor-specific LLM provider handlers.
 *
 * <p>Each handler knows how to format messages and call the LLM API
 * for a specific vendor (Anthropic, OpenAI, Gemini, etc.).
 *
 * <p>This pattern allows vendor-specific optimizations:
 * <ul>
 *   <li>Message format conversion</li>
 *   <li>System prompt formatting with structured output instructions</li>
 *   <li>Schema strictness handling</li>
 *   <li>Vendor-specific features (prompt caching, response_format, etc.)</li>
 * </ul>
 *
 * <h2>Structured Output Support</h2>
 * <p>Handlers implement vendor-specific structured output:
 * <ul>
 *   <li>Claude: Hint mode (schema in prompt) or strict mode (response_format)</li>
 *   <li>OpenAI/Gemini: Always use response_format with strict schema</li>
 * </ul>
 *
 * @see LlmProviderHandlerRegistry
 */
public interface LlmProviderHandler {

    // =========================================================================
    // Output Mode Constants (for Claude handler)
    // =========================================================================

    /** Use response_format for guaranteed schema compliance (slowest, 100% reliable) */
    String OUTPUT_MODE_STRICT = "strict";

    /** Use prompt-based JSON instructions (medium speed, ~95% reliable) */
    String OUTPUT_MODE_HINT = "hint";

    /** Plain text output for String return types (fastest) */
    String OUTPUT_MODE_TEXT = "text";

    // =========================================================================
    // Core Methods
    // =========================================================================

    /**
     * Get the vendor name this handler supports.
     *
     * @return Vendor name (e.g., "anthropic", "openai", "gemini")
     */
    String getVendor();

    /**
     * Generate a response with full message history.
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
     * Generate a response with tools and structured output support.
     *
     * <p>This is the main method for LLM generation with full feature support:
     * <ul>
     *   <li>Tool calling (with optional auto-execution)</li>
     *   <li>Structured output via response_format or prompt hints</li>
     *   <li>Vendor-specific optimizations</li>
     * </ul>
     *
     * @param model         The Spring AI ChatModel for this vendor
     * @param messages      List of messages with role and content
     * @param tools         List of tool definitions for the LLM (may be empty)
     * @param toolExecutor  Executor for invoking tools (null = don't execute, return tool_calls)
     * @param outputSchema  Schema for structured output (null = plain text)
     * @param options       Generation options (max_tokens, temperature, etc.)
     * @return Response containing content and any tool calls
     */
    default LlmResponse generateWithTools(
        ChatModel model,
        List<Map<String, Object>> messages,
        List<ToolDefinition> tools,
        ToolExecutorCallback toolExecutor,
        OutputSchema outputSchema,
        Map<String, Object> options
    ) {
        // Default implementation: delegate to legacy method (no tools/structured output)
        String content = generateWithMessages(model, messages, options);
        return new LlmResponse(content, List.of());
    }

    // Legacy overload for backwards compatibility
    default LlmResponse generateWithTools(
        ChatModel model,
        List<Map<String, Object>> messages,
        List<ToolDefinition> tools,
        ToolExecutorCallback toolExecutor,
        Map<String, Object> options
    ) {
        return generateWithTools(model, messages, tools, toolExecutor, null, options);
    }

    // =========================================================================
    // Structured Output Methods
    // =========================================================================

    /**
     * Format system prompt with vendor-specific instructions.
     *
     * <p>Adds appropriate instructions based on vendor:
     * <ul>
     *   <li>Claude (hint mode): Detailed JSON schema in prompt</li>
     *   <li>Claude (strict mode): Brief JSON note (response_format handles it)</li>
     *   <li>OpenAI/Gemini: Brief note only (response_format handles it)</li>
     * </ul>
     *
     * @param basePrompt   The original system prompt
     * @param tools        Tool schemas (for tool calling instructions)
     * @param outputSchema Schema for structured output (null = plain text)
     * @return Formatted system prompt with vendor-specific additions
     */
    default String formatSystemPrompt(
        String basePrompt,
        List<ToolDefinition> tools,
        OutputSchema outputSchema
    ) {
        // Default: return base prompt unchanged
        return basePrompt;
    }

    /**
     * Determine the output mode for this vendor.
     *
     * <p>Used primarily by Claude handler to choose between:
     * <ul>
     *   <li>text: String return type</li>
     *   <li>hint: Simple schema (&lt;5 fields, no nesting)</li>
     *   <li>strict: Complex schema</li>
     * </ul>
     *
     * @param outputSchema The output schema (null = text mode)
     * @return Output mode constant
     */
    default String determineOutputMode(OutputSchema outputSchema) {
        if (outputSchema == null) {
            return OUTPUT_MODE_TEXT;
        }
        return OUTPUT_MODE_STRICT;  // Default to strict for safety
    }

    // =========================================================================
    // Capability Methods
    // =========================================================================

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
     * @return Array of aliases for this vendor
     */
    default String[] getAliases() {
        return new String[0];
    }

    // =========================================================================
    // Data Types
    // =========================================================================

    /**
     * Tool definition for LLM calls.
     */
    record ToolDefinition(
        String name,
        String description,
        Map<String, Object> inputSchema
    ) {}

    /**
     * Output schema for structured responses.
     *
     * <p>Used to configure response_format or add JSON instructions to prompt.
     */
    record OutputSchema(
        /** Schema name (usually the class name) */
        String name,

        /** JSON Schema for the output */
        Map<String, Object> schema,

        /** Whether this is a simple schema (for Claude hint mode detection) */
        boolean simple
    ) {
        /**
         * Create from a JSON schema map.
         */
        public static OutputSchema fromSchema(String name, Map<String, Object> schema) {
            boolean simple = isSimpleSchema(schema);
            return new OutputSchema(name, schema, simple);
        }

        /**
         * Check if a schema is simple (for Claude hint mode).
         *
         * <p>Simple schema criteria:
         * <ul>
         *   <li>Less than 5 fields</li>
         *   <li>No nested objects</li>
         *   <li>No $ref references</li>
         * </ul>
         */
        private static boolean isSimpleSchema(Map<String, Object> schema) {
            @SuppressWarnings("unchecked")
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            if (properties == null) {
                return true;
            }

            // Check field count
            if (properties.size() >= 5) {
                return false;
            }

            // Check for nested objects or complex types
            for (Object fieldSchemaObj : properties.values()) {
                @SuppressWarnings("unchecked")
                Map<String, Object> fieldSchema = (Map<String, Object>) fieldSchemaObj;

                String fieldType = (String) fieldSchema.get("type");

                // Check for nested objects
                if ("object".equals(fieldType) && fieldSchema.containsKey("properties")) {
                    return false;
                }

                // Check for $ref (nested model reference)
                if (fieldSchema.containsKey("$ref")) {
                    return false;
                }

                // Check array items for complex types
                if ("array".equals(fieldType)) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> items = (Map<String, Object>) fieldSchema.get("items");
                    if (items != null) {
                        if ("object".equals(items.get("type")) || items.containsKey("$ref")) {
                            return false;
                        }
                    }
                }
            }

            return true;
        }

        /**
         * Make schema strict for OpenAI/Gemini (add additionalProperties: false, all required).
         *
         * @param addAllRequired Whether to add all properties to required array
         * @return New strict schema
         */
        public Map<String, Object> makeStrict(boolean addAllRequired) {
            return makeSchemaStrict(new LinkedHashMap<>(schema), addAllRequired);
        }

        /**
         * Recursively make a schema strict.
         */
        @SuppressWarnings("unchecked")
        private static Map<String, Object> makeSchemaStrict(Map<String, Object> schema, boolean addAllRequired) {
            Map<String, Object> result = new LinkedHashMap<>(schema);

            // Infer type as "object" if schema has "properties" but no "type" (common omission)
            // Gemini requires "type" field to be present
            if (result.get("type") == null && result.containsKey("properties")) {
                result.put("type", "object");
            }

            // Add additionalProperties: false to all objects
            if ("object".equals(result.get("type"))) {
                result.put("additionalProperties", false);

                // Optionally add all properties to required array
                if (addAllRequired) {
                    Map<String, Object> properties = (Map<String, Object>) result.get("properties");
                    if (properties != null && !properties.isEmpty()) {
                        result.put("required", new ArrayList<>(properties.keySet()));
                    }
                }
            }

            // Recursively process nested schemas
            Map<String, Object> properties = (Map<String, Object>) result.get("properties");
            if (properties != null) {
                Map<String, Object> strictProperties = new LinkedHashMap<>();
                for (Map.Entry<String, Object> entry : properties.entrySet()) {
                    Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();
                    strictProperties.put(entry.getKey(), makeSchemaStrict(fieldSchema, addAllRequired));
                }
                result.put("properties", strictProperties);
            }

            // Process array items
            Map<String, Object> items = (Map<String, Object>) result.get("items");
            if (items != null) {
                result.put("items", makeSchemaStrict(items, addAllRequired));
            }

            // Process $defs (JSON Schema definitions)
            Map<String, Object> defs = (Map<String, Object>) result.get("$defs");
            if (defs != null) {
                Map<String, Object> strictDefs = new LinkedHashMap<>();
                for (Map.Entry<String, Object> entry : defs.entrySet()) {
                    Map<String, Object> defSchema = (Map<String, Object>) entry.getValue();
                    strictDefs.put(entry.getKey(), makeSchemaStrict(defSchema, addAllRequired));
                }
                result.put("$defs", strictDefs);
            }

            return result;
        }
    }

    /**
     * Callback for executing tool calls.
     */
    @FunctionalInterface
    interface ToolExecutorCallback {
        /**
         * Execute a tool call.
         *
         * @param toolName Tool function name
         * @param arguments Tool arguments as JSON string
         * @return Tool result as string
         */
        String execute(String toolName, String arguments) throws Exception;
    }

    /**
     * Response from LLM including content and tool calls.
     */
    record LlmResponse(
        String content,
        List<ToolCall> toolCalls
    ) {
        public boolean hasToolCalls() {
            return toolCalls != null && !toolCalls.isEmpty();
        }
    }

    /**
     * Represents a tool call requested by the LLM.
     */
    record ToolCall(
        String id,
        String name,
        String arguments
    ) {}
}
