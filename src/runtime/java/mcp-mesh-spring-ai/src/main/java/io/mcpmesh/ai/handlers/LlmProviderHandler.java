package io.mcpmesh.ai.handlers;

import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;

import java.util.*;
import java.util.function.Function;

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

    /**
     * Sentinel for an unset/auto output mode. When the incoming
     * {@code model_params.output_mode} is unset (or invalid), handlers fall back
     * to per-vendor auto-selection via {@link #determineOutputMode(OutputSchema)}.
     */
    String OUTPUT_MODE_UNSET = "";

    /** Key under which a consumer-supplied output-mode override travels in the options map. */
    String OPTION_OUTPUT_MODE = "output_mode";

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
     * Shared structured-output system-prompt formatting used by the vendor handlers
     * (Anthropic, OpenAI, Gemini) that delegate prompt construction to the Rust core.
     *
     * <p>Computes the output mode and tool presence, serializes the output schema,
     * scans tool input schemas for media params via {@link io.mcpmesh.core.MeshCoreBridge},
     * and delegates to {@code MeshCoreBridge.formatSystemPrompt} using {@link #getVendor()}
     * as the vendor argument.
     *
     * <p>The no-op {@link #formatSystemPrompt} default is intentionally kept separate so
     * passthrough handlers (e.g. {@code GenericHandler}) return the base prompt unchanged.
     *
     * @param basePrompt   The original system prompt
     * @param tools        Tool schemas (for tool calling instructions)
     * @param outputSchema Schema for structured output (null = plain text)
     * @return Formatted system prompt produced by the Rust core
     */
    default String formatSystemPromptViaCore(
        String basePrompt,
        List<ToolDefinition> tools,
        OutputSchema outputSchema
    ) {
        return formatSystemPromptViaCore(basePrompt, tools, outputSchema, determineOutputMode(outputSchema));
    }

    /**
     * Overload of {@link #formatSystemPromptViaCore(String, List, OutputSchema)}
     * that uses an explicitly-supplied {@code effectiveOutputMode} instead of
     * re-running per-vendor auto-selection.
     *
     * <p>Used to honor a consumer-supplied {@code output_mode} override: the
     * caller computes the effective mode once via
     * {@link #determineOutputMode(OutputSchema, String)} and threads it both here
     * (prompt construction) and into the structured-output application so both
     * surfaces agree.
     *
     * @param basePrompt          The original system prompt
     * @param tools               Tool schemas (for tool calling instructions)
     * @param outputSchema        Schema for structured output (null = plain text)
     * @param effectiveOutputMode The already-resolved output mode to use
     * @return Formatted system prompt produced by the Rust core
     */
    default String formatSystemPromptViaCore(
        String basePrompt,
        List<ToolDefinition> tools,
        OutputSchema outputSchema,
        String effectiveOutputMode
    ) {
        String outputMode = effectiveOutputMode;
        boolean hasTools = tools != null && !tools.isEmpty();

        // Delegate to Rust core
        String schemaJson = null;
        String schemaName = null;
        if (outputSchema != null) {
            schemaName = outputSchema.name();
            try {
                schemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(outputSchema.schema());
            } catch (Exception e) {
                LoggerFactory.getLogger(getClass()).warn("Failed to serialize schema for Rust core: {}", e.getMessage());
            }
        }

        boolean hasMediaParams = false;
        if (tools != null) {
            for (ToolDefinition tool : tools) {
                if (tool.inputSchema() != null) {
                    try {
                        String toolSchemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(tool.inputSchema());
                        try {
                            if (io.mcpmesh.core.MeshCoreBridge.detectMediaParams(toolSchemaJson)) {
                                hasMediaParams = true;
                                break;
                            }
                        } catch (UnsatisfiedLinkError e) {
                            // Native library unavailable (e.g., CI) — safe default
                        }
                    } catch (Exception e) {
                        LoggerFactory.getLogger(getClass()).warn("Failed to serialize tool schema for media params detection: {}", e.getMessage());
                    }
                }
            }
        }

        return io.mcpmesh.core.MeshCoreBridge.formatSystemPrompt(
            getVendor(), basePrompt, hasTools, hasMediaParams, schemaJson, schemaName, outputMode);
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

    /**
     * Determine the effective output mode, honoring a consumer-supplied override.
     *
     * <p>If {@code overrideMode} is a recognized mode
     * ({@code strict}/{@code hint}/{@code text}) it fully replaces the per-vendor
     * auto-selection and is returned as-is. Otherwise — unset, blank, or an
     * unrecognized value — this delegates to {@link #determineOutputMode(OutputSchema)}
     * so the no-override path stays byte-identical to today's behavior. An
     * unrecognized (non-blank) value is logged as a warning before falling back.
     *
     * @param outputSchema The output schema (null = text mode in auto-selection)
     * @param overrideMode The incoming {@code model_params.output_mode} (may be null/blank)
     * @return The effective output mode constant
     */
    default String determineOutputMode(OutputSchema outputSchema, String overrideMode) {
        if (overrideMode == null || overrideMode.isEmpty()) {
            return determineOutputMode(outputSchema);
        }
        switch (overrideMode) {
            case OUTPUT_MODE_STRICT:
            case OUTPUT_MODE_HINT:
            case OUTPUT_MODE_TEXT:
                return overrideMode;
            default:
                LoggerFactory.getLogger(getClass()).warn(
                    "Ignoring invalid output_mode override '{}' (expected strict|hint|text); "
                    + "falling back to auto-selection.", overrideMode);
                return determineOutputMode(outputSchema);
        }
    }

    /**
     * Read the consumer-supplied output-mode override from the options map.
     *
     * @param options the generation options (may be null)
     * @return the raw override string, or {@link #OUTPUT_MODE_UNSET} if absent
     */
    static String outputModeOverride(Map<String, Object> options) {
        if (options == null) {
            return OUTPUT_MODE_UNSET;
        }
        Object v = options.get(OPTION_OUTPUT_MODE);
        return v != null ? v.toString() : OUTPUT_MODE_UNSET;
    }

    // =========================================================================
    // Shared Message Assembly
    // =========================================================================

    /**
     * Prefix prepended to a previous assistant turn when flattening the message
     * history into a single user-content string.
     *
     * <p>Vendors override this where their convention differs (e.g. Gemini uses
     * {@code "[Previous Response]\n"}).
     *
     * @return The assistant-turn prefix literal (including its trailing newline)
     */
    default String previousResponsePrefix() {
        return "[Previous Assistant Response]\n";
    }

    /**
     * Extract the non-system messages from a Spring AI message list, preserving order.
     *
     * @param messages The full message list (may contain system messages)
     * @return A new list containing only the non-system messages
     */
    default List<Message> extractNonSystemMessages(List<Message> messages) {
        List<Message> nonSystemMessages = new ArrayList<>();
        for (Message msg : messages) {
            if (!(msg instanceof SystemMessage)) {
                nonSystemMessages.add(msg);
            }
        }
        return nonSystemMessages;
    }

    /**
     * Flatten the non-system messages into a single user-content string.
     *
     * <p>User turns are appended verbatim; assistant turns are prefixed with
     * {@link #previousResponsePrefix()}. Turns are newline-joined.
     *
     * @param messages The message list (system messages are ignored)
     * @return The assembled user-content string
     */
    default String buildUserContent(List<Message> messages) {
        StringBuilder userContent = new StringBuilder();
        for (Message msg : extractNonSystemMessages(messages)) {
            if (msg instanceof UserMessage um) {
                if (userContent.length() > 0) userContent.append("\n");
                userContent.append(um.getText());
            } else if (msg instanceof AssistantMessage am) {
                if (userContent.length() > 0) userContent.append("\n");
                userContent.append(previousResponsePrefix()).append(am.getText());
            }
        }
        return userContent.toString();
    }

    /**
     * Replace the first system message with the formatted system prompt, dropping
     * any additional system messages. If the input contained no system message,
     * the formatted prompt is prepended.
     *
     * <p>No-op replacement occurs when {@code formattedSystemPrompt} is null/empty:
     * any existing system messages are simply dropped and nothing is prepended.
     *
     * @param messages              The full message list
     * @param formattedSystemPrompt The formatted system prompt (may be null/empty)
     * @return A new list with the system message replaced/prepended
     */
    default List<Message> replaceSystemMessage(List<Message> messages, String formattedSystemPrompt) {
        List<Message> messagesWithFormattedSystem = new ArrayList<>();
        boolean addedSystem = false;
        for (Message msg : messages) {
            if (msg instanceof SystemMessage) {
                if (!addedSystem && formattedSystemPrompt != null && !formattedSystemPrompt.isEmpty()) {
                    messagesWithFormattedSystem.add(new SystemMessage(formattedSystemPrompt));
                    addedSystem = true;
                }
            } else {
                messagesWithFormattedSystem.add(msg);
            }
        }
        // Add system prompt at beginning if not already added
        if (!addedSystem && formattedSystemPrompt != null && !formattedSystemPrompt.isEmpty()) {
            messagesWithFormattedSystem.add(0, new SystemMessage(formattedSystemPrompt));
        }
        return messagesWithFormattedSystem;
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
    // Shared Tool Callback Creation
    // =========================================================================

    /** Shared ObjectMapper for tool callback serialization. */
    static final tools.jackson.databind.ObjectMapper TOOL_CALLBACK_MAPPER = new tools.jackson.databind.ObjectMapper();

    /** Vendor hook to transform a tool's input JSON schema before it is attached
     *  to the Spring AI tool callback. Default: identity. Gemini overrides to
     *  upper-case JSON-schema type values. */
    default Map<String, Object> transformToolInputSchema(Map<String, Object> schema) {
        return schema;
    }

    /**
     * Create ToolCallbacks for schema only (no execution).
     *
     * <p>Shared across all handlers -- tool definitions are converted to Spring AI
     * callbacks with a dummy function that should never be called. Vendor-specific
     * handlers (e.g., Gemini) may override this to apply schema transformations.
     */
    default List<ToolCallback> createToolCallbacksForSchema(List<ToolDefinition> tools) {
        List<ToolCallback> callbacks = new ArrayList<>();
        if (tools == null) return callbacks;

        for (ToolDefinition tool : tools) {
            Function<Map<String, Object>, String> dummyFunction = args -> {
                LoggerFactory.getLogger(getClass()).warn("Tool {} was unexpectedly called!", tool.name());
                return "{\"error\": \"Tool execution not supported in provider mode\"}";
            };

            String inputSchemaJson = null;
            if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
                try {
                    inputSchemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(transformToolInputSchema(tool.inputSchema()));
                } catch (Exception e) {
                    LoggerFactory.getLogger(getClass()).warn("Failed to serialize inputSchema for {}: {}", tool.name(), e.getMessage());
                }
            }

            @SuppressWarnings("unchecked")
            var builder = FunctionToolCallback
                .builder(tool.name(), dummyFunction)
                .description(tool.description() != null ? tool.description() : "No description")
                .inputType((Class<Map<String, Object>>) (Class<?>) Map.class);

            if (inputSchemaJson != null) {
                builder.inputSchema(inputSchemaJson);
            }

            callbacks.add(builder.build());
        }

        return callbacks;
    }

    /**
     * Create a Spring AI ToolCallback from a ToolDefinition with an executor.
     *
     * <p>Shared across all handlers -- converts tool call arguments to JSON,
     * invokes the executor, and returns the result. Vendor-specific handlers
     * (e.g., Gemini) may override this to apply schema transformations.
     */
    default ToolCallback createToolCallback(ToolDefinition tool, ToolExecutorCallback toolExecutor) {
        Function<Map<String, Object>, String> toolFunction = args -> {
            try {
                String argsJson = args != null ? TOOL_CALLBACK_MAPPER.writeValueAsString(args) : "{}";
                return toolExecutor.execute(tool.name(), argsJson);
            } catch (Exception e) {
                LoggerFactory.getLogger(getClass()).error("Tool execution failed: {}", tool.name(), e);
                try {
                    return TOOL_CALLBACK_MAPPER.writeValueAsString(Map.of("error", "Tool execution failed: " + tool.name()));
                } catch (Exception ignored) {
                    return "{\"error\": \"tool execution failed\"}";
                }
            }
        };

        String inputSchemaJson = null;
        if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
            try {
                inputSchemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(transformToolInputSchema(tool.inputSchema()));
            } catch (Exception e) {
                LoggerFactory.getLogger(getClass()).warn("Failed to serialize inputSchema for {}: {}", tool.name(), e.getMessage());
            }
        }

        @SuppressWarnings("unchecked")
        var builder = FunctionToolCallback
            .builder(tool.name(), toolFunction)
            .description(tool.description() != null ? tool.description() : "No description")
            .inputType((Class<Map<String, Object>>) (Class<?>) Map.class);

        if (inputSchemaJson != null) {
            builder.inputSchema(inputSchemaJson);
        }

        return builder.build();
    }

    // =========================================================================
    // Usage Extraction
    // =========================================================================

    /**
     * Extract token usage metadata from a ChatResponse.
     *
     * <p>Default implementation shared across all handlers.
     */
    default UsageMeta extractUsage(ChatResponse response) {
        if (response == null || response.getMetadata() == null) {
            return null;
        }
        try {
            var usage = response.getMetadata().getUsage();
            if (usage == null) {
                return null;
            }
            long input = usage.getPromptTokens();
            long output = usage.getCompletionTokens();
            if (input == 0 && output == 0) {
                return null;
            }
            String model = response.getMetadata().getModel();
            return new UsageMeta(input, output, model);
        } catch (Exception e) {
            LoggerFactory.getLogger(getClass()).debug("Failed to extract usage metadata: {}", e.getMessage());
            return null;
        }
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
    final class OutputSchema {
        private final String name;
        private final Map<String, Object> schema;
        private final boolean simple;

        // Cached sanitized schema (computed lazily, immutable once set)
        private volatile Map<String, Object> cachedSanitized;

        public OutputSchema(String name, Map<String, Object> schema, boolean simple) {
            this.name = name;
            this.schema = schema;
            this.simple = simple;
        }

        public String name() { return name; }
        public Map<String, Object> schema() { return schema; }
        public boolean simple() { return simple; }

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
         * Keywords that are validation-only and not supported by LLM structured output APIs.
         */
        private static final Set<String> UNSUPPORTED_SCHEMA_KEYWORDS = Set.of(
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "pattern",
            "multipleOf"
        );

        /**
         * Sanitize schema by removing validation keywords unsupported by LLM APIs.
         *
         * LLM structured output APIs (Claude, OpenAI, Gemini) typically only support
         * the structural parts of JSON Schema, not validation constraints.
         *
         * @return New schema with unsupported validation keywords removed
         */
        public Map<String, Object> sanitize() {
            Map<String, Object> result = cachedSanitized;
            if (result == null) {
                result = sanitizeSchema(new LinkedHashMap<>(schema));
                cachedSanitized = result;
            }
            return result;
        }

        /**
         * Recursively sanitize a schema by removing unsupported keywords.
         */
        @SuppressWarnings("unchecked")
        private static Map<String, Object> sanitizeSchema(Map<String, Object> schema) {
            Map<String, Object> result = new LinkedHashMap<>(schema);

            // Remove unsupported keywords at this level
            for (String keyword : UNSUPPORTED_SCHEMA_KEYWORDS) {
                result.remove(keyword);
            }

            // Recursively process nested schemas
            Map<String, Object> properties = (Map<String, Object>) result.get("properties");
            if (properties != null) {
                Map<String, Object> sanitizedProperties = new LinkedHashMap<>();
                for (Map.Entry<String, Object> entry : properties.entrySet()) {
                    Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();
                    sanitizedProperties.put(entry.getKey(), sanitizeSchema(fieldSchema));
                }
                result.put("properties", sanitizedProperties);
            }

            // Process array items
            Map<String, Object> items = (Map<String, Object>) result.get("items");
            if (items != null) {
                result.put("items", sanitizeSchema(items));
            }

            // Process $defs (JSON Schema definitions)
            Map<String, Object> defs = (Map<String, Object>) result.get("$defs");
            if (defs != null) {
                Map<String, Object> sanitizedDefs = new LinkedHashMap<>();
                for (Map.Entry<String, Object> entry : defs.entrySet()) {
                    Map<String, Object> defSchema = (Map<String, Object>) entry.getValue();
                    sanitizedDefs.put(entry.getKey(), sanitizeSchema(defSchema));
                }
                result.put("$defs", sanitizedDefs);
            }

            // Process anyOf, oneOf, allOf
            for (String key : List.of("anyOf", "oneOf", "allOf")) {
                List<Map<String, Object>> variants = (List<Map<String, Object>>) result.get(key);
                if (variants != null) {
                    List<Map<String, Object>> sanitizedVariants = new ArrayList<>();
                    for (Map<String, Object> variant : variants) {
                        sanitizedVariants.add(sanitizeSchema(variant));
                    }
                    result.put(key, sanitizedVariants);
                }
            }

            return result;
        }

        /**
         * Make schema strict for OpenAI/Gemini (add additionalProperties: false, all required).
         *
         * @param addAllRequired Whether to add all properties to required array
         * @return New strict schema
         */
        public Map<String, Object> makeStrict(boolean addAllRequired) {
            // Sanitize first to remove unsupported validation keywords (minimum, maximum, etc.)
            Map<String, Object> sanitized = sanitizeSchema(new LinkedHashMap<>(schema));
            return makeSchemaStrict(sanitized, addAllRequired);
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
        List<ToolCall> toolCalls,
        UsageMeta usage
    ) {
        /**
         * Convenience constructor without usage metadata.
         */
        LlmResponse(String content, List<ToolCall> toolCalls) {
            this(content, toolCalls, null);
        }

        public boolean hasToolCalls() {
            return toolCalls != null && !toolCalls.isEmpty();
        }
    }

    /**
     * Token usage metadata from an LLM call.
     *
     * @param inputTokens  Number of input/prompt tokens
     * @param outputTokens Number of output/completion tokens
     * @param model        Model identifier (may be null if unavailable)
     */
    record UsageMeta(
        long inputTokens,
        long outputTokens,
        String model
    ) {
        public long totalTokens() {
            return inputTokens + outputTokens;
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
