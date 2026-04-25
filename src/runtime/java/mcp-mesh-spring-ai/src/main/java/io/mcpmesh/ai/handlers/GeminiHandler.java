package io.mcpmesh.ai.handlers;

import io.mcpmesh.core.MeshCoreBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.ai.google.genai.GoogleGenAiChatOptions;
import org.springframework.ai.vertexai.gemini.VertexAiGeminiChatModel;
import org.springframework.ai.vertexai.gemini.VertexAiGeminiChatOptions;

import java.util.*;
import java.util.function.Function;

/**
 * LLM provider handler for Google Gemini models.
 *
 * <p>Handles Gemini-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>Large context window support</li>
 *   <li>System instruction handling</li>
 *   <li>Structured output via prompt-based hints (Spring AI limitation)</li>
 *   <li>Multimodal capabilities</li>
 * </ul>
 *
 * <h2>Structured Output</h2>
 * <p>Gemini Java uses prompt-based hints (HINT mode) for structured output.
 * Spring AI 2.0.0-M2 has a request construction bug where responseMimeType + responseSchema
 * alongside tools causes tool arguments to become empty objects ({}).
 * Python and TypeScript runtimes use native response_format (STRICT mode) instead.
 *
 * @see LlmProviderHandler
 */
public class GeminiHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(GeminiHandler.class);
    private static final tools.jackson.databind.ObjectMapper MAPPER = new tools.jackson.databind.ObjectMapper();

    @Override
    public String getVendor() {
        return "gemini";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"google"};
    }

    // =========================================================================
    // Structured Output Methods
    // =========================================================================

    @Override
    public String determineOutputMode(OutputSchema outputSchema) {
        // Gemini Java: HINT mode only -- the Gemini API REJECTS the combination of
        // function calling (tools) + responseMimeType="application/json" with the
        // explicit error: "Function calling with a response mime type: 'application/json'
        // is unsupported". Verified against Spring AI 2.0.0-M4 + google-genai SDK 1.44.0.
        //
        // HINT mode achieves structured output by including the schema in the system
        // prompt instead of via the API parameter, which IS compatible with tools.
        //
        // M2 silently returned empty tool args {} for the same invalid combo; M4
        // surfaces it as a 400. The workaround is unchanged either way -- this is a
        // permanent Gemini API constraint, not a Spring AI bug to be patched.
        return outputSchema == null ? OUTPUT_MODE_TEXT : OUTPUT_MODE_HINT;
    }

    @Override
    public String formatSystemPrompt(
            String basePrompt,
            List<ToolDefinition> tools,
            OutputSchema outputSchema) {

        String outputMode = determineOutputMode(outputSchema);
        boolean hasTools = tools != null && !tools.isEmpty();

        // Delegate to Rust core
        String schemaJson = null;
        String schemaName = null;
        if (outputSchema != null) {
            schemaName = outputSchema.name();
            try {
                schemaJson = MAPPER.writeValueAsString(outputSchema.schema());
            } catch (Exception e) {
                log.warn("Failed to serialize schema for Rust core: {}", e.getMessage());
            }
        }

        boolean hasMediaParams = false;
        if (tools != null) {
            for (ToolDefinition tool : tools) {
                if (tool.inputSchema() != null) {
                    try {
                        String toolSchemaJson = MAPPER.writeValueAsString(tool.inputSchema());
                        try {
                            if (MeshCoreBridge.detectMediaParams(toolSchemaJson)) {
                                hasMediaParams = true;
                                break;
                            }
                        } catch (UnsatisfiedLinkError e) {
                            // Native library unavailable (e.g., CI) — safe default
                        }
                    } catch (Exception e) {
                        log.warn("Failed to serialize tool schema for media params detection: {}", e.getMessage());
                    }
                }
            }
        }

        return MeshCoreBridge.formatSystemPrompt(
            "gemini", basePrompt, hasTools, hasMediaParams, schemaJson, schemaName, outputMode);
    }

    // =========================================================================
    // Generation Methods
    // =========================================================================

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("GeminiHandler: Processing {} messages", messages.size());

        List<Message> springMessages = convertMessages(messages);
        Prompt prompt = new Prompt(springMessages);
        ChatResponse response = model.call(prompt);

        String content = response.getResult() != null && response.getResult().getOutput() != null
            ? response.getResult().getOutput().getText() : null;
        log.debug("GeminiHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return content;
    }

    @Override
    public LlmResponse generateWithTools(
            ChatModel model,
            List<Map<String, Object>> messages,
            List<ToolDefinition> tools,
            ToolExecutorCallback toolExecutor,
            OutputSchema outputSchema,
            Map<String, Object> options) {

        log.debug("GeminiHandler: Processing {} messages with {} tools, outputSchema={}, executeTools={}",
            messages.size(),
            tools != null ? tools.size() : 0,
            outputSchema != null ? outputSchema.name() : "none",
            toolExecutor != null);

        // If toolExecutor is null, use no-execution mode (return tool_calls without executing)
        boolean executeTools = toolExecutor != null;

        // Build and format messages
        List<Message> springMessages = convertMessages(messages);

        // Extract system message
        String systemPrompt = null;
        for (Message msg : springMessages) {
            if (msg instanceof SystemMessage sm) {
                systemPrompt = sm.getText();
                break;
            }
        }

        // Format system prompt (brief note only - response_format handles schema)
        String formattedSystemPrompt = formatSystemPrompt(systemPrompt, tools, outputSchema);

        if (executeTools) {
            // Auto-execution mode: Use ChatClient which handles tool execution automatically
            return generateWithToolsAutoExecute(model, springMessages, tools, toolExecutor, formattedSystemPrompt, outputSchema);
        } else {
            // No-execution mode: Use model.call with internalToolExecutionEnabled(false)
            return generateWithToolsNoExecute(model, springMessages, tools, formattedSystemPrompt, outputSchema);
        }
    }

    /**
     * Generate with tools and auto-execute them via ChatClient.
     */
    private LlmResponse generateWithToolsAutoExecute(
            ChatModel model,
            List<Message> springMessages,
            List<ToolDefinition> tools,
            ToolExecutorCallback toolExecutor,
            String formattedSystemPrompt,
            OutputSchema outputSchema) {

        // Convert tools to Spring AI ToolCallback objects
        List<ToolCallback> toolCallbacks = new ArrayList<>();
        if (tools != null && !tools.isEmpty()) {
            for (ToolDefinition tool : tools) {
                ToolCallback callback = createToolCallback(tool, toolExecutor);
                toolCallbacks.add(callback);
            }
            log.debug("Created {} tool callbacks for ChatClient", toolCallbacks.size());
        }

        // Extract non-system messages
        List<Message> nonSystemMessages = new ArrayList<>();
        for (Message msg : springMessages) {
            if (!(msg instanceof SystemMessage)) {
                nonSystemMessages.add(msg);
            }
        }

        // Build user content from remaining messages
        StringBuilder userContent = new StringBuilder();
        for (Message msg : nonSystemMessages) {
            if (msg instanceof UserMessage um) {
                if (userContent.length() > 0) userContent.append("\n");
                userContent.append(um.getText());
            } else if (msg instanceof AssistantMessage am) {
                if (userContent.length() > 0) userContent.append("\n");
                userContent.append("[Previous Response]\n").append(am.getText());
            }
        }

        // Use ChatClient with tools
        ChatClient chatClient = ChatClient.create(model);
        ChatClient.ChatClientRequestSpec requestSpec = chatClient.prompt();

        // Add formatted system prompt
        if (formattedSystemPrompt != null && !formattedSystemPrompt.isEmpty()) {
            requestSpec.system(formattedSystemPrompt);
        }

        // Add user content
        requestSpec.user(userContent.toString());

        // Add tools if present
        if (!toolCallbacks.isEmpty()) {
            requestSpec.toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]));
        }

        // Don't use applyResponseFormat - Spring AI has issues with Gemini responseSchema
        // Structured output is handled via prompt-based hints in formatSystemPrompt()

        // Execute the request
        ChatResponse chatResponse = requestSpec.call().chatResponse();
        String content = chatResponse.getResult() != null && chatResponse.getResult().getOutput() != null
            ? chatResponse.getResult().getOutput().getText() : null;

        log.debug("GeminiHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return new LlmResponse(content, List.of(), extractUsage(chatResponse));
    }

    /**
     * Generate with tools but WITHOUT executing them.
     *
     * <p>Uses model.call() with internalToolExecutionEnabled(false) to get
     * tool_calls back without auto-execution. This is used for mesh delegation
     * where the consumer (not provider) executes tools.
     */
    private LlmResponse generateWithToolsNoExecute(
            ChatModel model,
            List<Message> springMessages,
            List<ToolDefinition> tools,
            String formattedSystemPrompt,
            OutputSchema outputSchema) {

        // Replace system message with formatted one
        List<Message> messagesWithFormattedSystem = new ArrayList<>();
        boolean addedSystem = false;
        for (Message msg : springMessages) {
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

        // Create tool callbacks for schema only (no execution)
        List<ToolCallback> toolCallbacks = createToolCallbacksForSchema(tools);

        // Build Gemini-specific chat options with tool execution DISABLED.
        // The concrete options class must match the underlying ChatModel: Vertex's
        // chat model does an explicit checkcast to VertexAiGeminiChatOptions and
        // throws ClassCastException if given GoogleGenAiChatOptions (and vice versa).
        // Don't use responseSchema - Spring AI has issues with Gemini responseSchema
        // Structured output is handled via prompt-based hints in formatSystemPrompt()
        log.debug("Using prompt-based JSON hints for structured output (not responseSchema)");

        ChatOptions chatOptions = buildToolNoExecuteOptions(model, toolCallbacks);

        // Create prompt with options
        org.springframework.ai.chat.prompt.Prompt prompt =
            new org.springframework.ai.chat.prompt.Prompt(messagesWithFormattedSystem, chatOptions);

        log.debug("Calling Gemini with {} tools (execution disabled)", tools != null ? tools.size() : 0);

        // Call model
        org.springframework.ai.chat.model.ChatResponse response = model.call(prompt);

        // Extract content and tool calls from ALL Generations
        String content = null;
        List<ToolCall> toolCalls = new ArrayList<>();

        for (org.springframework.ai.chat.model.Generation gen : response.getResults()) {
            AssistantMessage output = gen.getOutput();
            if (output == null) continue;

            // Capture text content from first generation that has it
            if (content == null && output.getText() != null && !output.getText().isEmpty()) {
                content = output.getText();
            }

            // Extract tool calls from any generation that has them
            if (output.hasToolCalls()) {
                for (AssistantMessage.ToolCall tc : output.getToolCalls()) {
                    log.debug("Found tool call: id={}, name={}, args={}",
                        tc.id(), tc.name(), tc.arguments());
                    toolCalls.add(new ToolCall(tc.id(), tc.name(), tc.arguments()));
                }
            }
        }

        log.debug("GeminiHandler: Extracted content={} chars, toolCalls={}",
            content != null ? content.length() : 0,
            toolCalls.size());

        return new LlmResponse(content, toolCalls, extractUsage(response));
    }

    // Reflection-based lookup of Vertex AI chat model class. The
    // spring-ai-vertex-ai-gemini dependency is declared <optional>true</optional>
    // in mcp-mesh-spring-ai/pom.xml, so consumers using only AI Studio
    // (spring-ai-starter-model-google-genai) won't have these classes on their
    // runtime classpath. Resolving via Class.forName lets us safely detect
    // availability without an `instanceof` check that would trigger a
    // NoClassDefFoundError on consumer classpaths missing the dep.
    //
    // The compile-time imports of VertexAiGeminiChatModel/VertexAiGeminiChatOptions
    // are intentional and benign: imports are erased to fully-qualified bytecode
    // references, and the JVM only resolves a referenced class when a method
    // *body* mentioning it is first invoked. By isolating Vertex API calls into
    // buildVertexOptions(), the class load is deferred until we've already
    // verified the class is present (VERTEX_OPTIONS_CLASS != null).
    private static final Class<?> VERTEX_CHAT_MODEL_CLASS;
    private static final Class<?> VERTEX_OPTIONS_CLASS;
    static {
        Class<?> modelClass = null;
        Class<?> optionsClass = null;
        try {
            modelClass = Class.forName("org.springframework.ai.vertexai.gemini.VertexAiGeminiChatModel");
            optionsClass = Class.forName("org.springframework.ai.vertexai.gemini.VertexAiGeminiChatOptions");
        } catch (ClassNotFoundException e) {
            // Vertex AI starter not on classpath -- fine, AI Studio path will be used.
            // Logged at debug level so we don't spam stdout for normal AI-Studio-only deployments.
            log.debug("spring-ai-vertex-ai-gemini not on classpath; vertex_ai routing disabled");
        }
        VERTEX_CHAT_MODEL_CLASS = modelClass;
        VERTEX_OPTIONS_CLASS = optionsClass;
    }

    /**
     * Build provider-specific {@link ChatOptions} for the no-tool-execution path.
     *
     * <p>Mesh delegation routes both {@code gemini/...} (Google AI Studio) and
     * {@code vertex_ai/...} model strings through this {@code GeminiHandler}, but
     * the underlying {@link ChatModel} differs:
     * <ul>
     *   <li>{@code GoogleGenAiChatModel} accepts {@link GoogleGenAiChatOptions}</li>
     *   <li>{@code VertexAiGeminiChatModel} accepts {@code VertexAiGeminiChatOptions}</li>
     * </ul>
     * Each chat model does an explicit checkcast on the options it receives, so
     * passing the wrong type throws {@link ClassCastException} at request time.
     * Branch on the chat model type to pick the matching options class.
     *
     * <p>The Vertex branch is guarded by {@link #VERTEX_CHAT_MODEL_CLASS} being
     * non-null, which is only true when {@code spring-ai-vertex-ai-gemini} is on
     * the consumer's classpath. AI-Studio-only consumers will skip the branch
     * and never trigger a class load of the Vertex types.
     *
     * <p>Package-private for testability.
     */
    ChatOptions buildToolNoExecuteOptions(ChatModel chatModel, List<ToolCallback> toolCallbacks) {
        if (VERTEX_CHAT_MODEL_CLASS != null && VERTEX_CHAT_MODEL_CLASS.isInstance(chatModel)) {
            return buildVertexOptions(toolCallbacks);
        }
        return GoogleGenAiChatOptions.builder()
            .toolCallbacks(toolCallbacks)
            .internalToolExecutionEnabled(false)
            .build();
    }

    /**
     * Isolated method that touches the Vertex options class.
     *
     * <p>Only called when {@link #VERTEX_CHAT_MODEL_CLASS} != null (verified at
     * the call site in {@link #buildToolNoExecuteOptions}), so the JVM's lazy
     * class resolution of {@code VertexAiGeminiChatOptions} when this method
     * body is first executed is guaranteed to succeed -- the class IS on the
     * classpath by the time we get here.
     */
    private ChatOptions buildVertexOptions(List<ToolCallback> toolCallbacks) {
        return VertexAiGeminiChatOptions.builder()
            .toolCallbacks(toolCallbacks)
            .internalToolExecutionEnabled(false)
            .build();
    }

    /**
     * Apply response format for structured output.
     *
     * <p>DISABLED: Spring AI 2.0.0-M2 has a bug where setting responseMimeType +
     * responseSchema alongside tools causes tool arguments to become empty objects ({}).
     * This is NOT a Gemini API issue -- the same calls work via LiteLLM and Vercel SDK.
     * Structured output is handled via prompt-based hints in formatSystemPrompt() instead.
     *
     * <p>This method is preserved for future use when Spring AI fixes the bug.
     * See: Spring AI PR #4977 for related work.
     */
    @SuppressWarnings("unused")
    private void applyResponseFormat(ChatClient.ChatClientRequestSpec requestSpec, OutputSchema outputSchema) {
        try {
            // Make schema strict (add additionalProperties: false, all properties required)
            Map<String, Object> strictSchema = outputSchema.makeStrict(true);

            // Convert schema to JSON string for Gemini
            String schemaJson = MAPPER
                .writeValueAsString(strictSchema);

            GoogleGenAiChatOptions geminiOptions = GoogleGenAiChatOptions.builder()
                .responseMimeType("application/json")
                .responseSchema(schemaJson)
                .build();

            requestSpec.options(geminiOptions);
            log.debug("Applied Gemini response format with schema: {}", outputSchema.name());
        } catch (Exception e) {
            log.warn("Failed to apply response format for {}: {}", outputSchema.name(), e.getMessage());
        }
    }

    /**
     * Create ToolCallbacks for schema only (no execution).
     *
     * <p>Overrides the default to apply Gemini-specific uppercase type conversion.
     */
    @Override
    public List<ToolCallback> createToolCallbacksForSchema(List<ToolDefinition> tools) {
        List<ToolCallback> callbacks = new ArrayList<>();
        if (tools == null) return callbacks;

        for (ToolDefinition tool : tools) {
            // Create a dummy function that should never be called
            java.util.function.Function<Map<String, Object>, String> dummyFunction = args -> {
                log.warn("Tool {} was unexpectedly called - this shouldn't happen!", tool.name());
                return "{\"error\": \"Tool execution not supported in provider mode\"}";
            };

            // Convert inputSchema Map to JSON string with uppercase types for Gemini
            String inputSchemaJson = null;
            if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
                try {
                    Map<String, Object> convertedSchema = convertSchemaTypesToUpperCase(tool.inputSchema());
                    inputSchemaJson = MAPPER
                        .writeValueAsString(convertedSchema);
                    log.debug("Converted tool schema for {}: {}", tool.name(), inputSchemaJson);
                } catch (Exception e) {
                    log.warn("Failed to serialize inputSchema for {}: {}", tool.name(), e.getMessage());
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
     * Convert JSON Schema type values to uppercase for Gemini API compatibility.
     * Google GenAI SDK expects uppercase types (STRING, OBJECT, etc.) while
     * standard JSON Schema uses lowercase (string, object, etc.).
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> convertSchemaTypesToUpperCase(Map<String, Object> schema) {
        if (schema == null) return null;
        Map<String, Object> result = new LinkedHashMap<>(schema);

        // Convert "type" to uppercase (string form or array form)
        if (result.containsKey("type")) {
            Object typeVal = result.get("type");
            if (typeVal instanceof String type) {
                result.put("type", type.toUpperCase());
            } else if (typeVal instanceof List) {
                @SuppressWarnings("unchecked")
                List<Object> types = (List<Object>) typeVal;
                List<Object> uppercased = new ArrayList<>();
                for (Object t : types) {
                    uppercased.add(t instanceof String ? ((String) t).toUpperCase() : t);
                }
                result.put("type", uppercased);
            }
        }

        // Recurse into "properties"
        if (result.containsKey("properties") && result.get("properties") instanceof Map) {
            Map<String, Object> properties = (Map<String, Object>) result.get("properties");
            Map<String, Object> convertedProperties = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : properties.entrySet()) {
                if (entry.getValue() instanceof Map) {
                    convertedProperties.put(entry.getKey(),
                        convertSchemaTypesToUpperCase((Map<String, Object>) entry.getValue()));
                } else {
                    convertedProperties.put(entry.getKey(), entry.getValue());
                }
            }
            result.put("properties", convertedProperties);
        }

        // Recurse into "items" (for array types)
        if (result.containsKey("items") && result.get("items") instanceof Map) {
            result.put("items", convertSchemaTypesToUpperCase((Map<String, Object>) result.get("items")));
        }

        // Recurse into "$defs"
        if (result.containsKey("$defs") && result.get("$defs") instanceof Map) {
            Map<String, Object> defs = (Map<String, Object>) result.get("$defs");
            Map<String, Object> convertedDefs = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : defs.entrySet()) {
                if (entry.getValue() instanceof Map) {
                    convertedDefs.put(entry.getKey(),
                        convertSchemaTypesToUpperCase((Map<String, Object>) entry.getValue()));
                } else {
                    convertedDefs.put(entry.getKey(), entry.getValue());
                }
            }
            result.put("$defs", convertedDefs);
        }

        // Recurse into "anyOf", "oneOf", "allOf"
        for (String keyword : List.of("anyOf", "oneOf", "allOf")) {
            if (result.containsKey(keyword) && result.get(keyword) instanceof List) {
                List<Object> variants = (List<Object>) result.get(keyword);
                List<Object> convertedVariants = new ArrayList<>();
                for (Object variant : variants) {
                    if (variant instanceof Map) {
                        convertedVariants.add(convertSchemaTypesToUpperCase((Map<String, Object>) variant));
                    } else {
                        convertedVariants.add(variant);
                    }
                }
                result.put(keyword, convertedVariants);
            }
        }

        return result;
    }

    /**
     * Create a Spring AI ToolCallback from our ToolDefinition.
     *
     * <p>Overrides the default to apply Gemini-specific uppercase type conversion.
     */
    @Override
    public ToolCallback createToolCallback(ToolDefinition tool, ToolExecutorCallback toolExecutor) {
        Function<Map<String, Object>, String> toolFunction = args -> {
            try {
                String argsJson = args != null ? MAPPER
                    .writeValueAsString(args) : "{}";
                return toolExecutor.execute(tool.name(), argsJson);
            } catch (Exception e) {
                log.error("Tool execution failed: {}", tool.name(), e);
                try {
                    return TOOL_CALLBACK_MAPPER.writeValueAsString(Map.of("error", "Tool execution failed: " + tool.name()));
                } catch (Exception ignored) {
                    return "{\"error\": \"tool execution failed\"}";
                }
            }
        };

        // Convert inputSchema with uppercase types for Gemini API compatibility
        String inputSchemaJson = null;
        if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
            try {
                Map<String, Object> convertedSchema = convertSchemaTypesToUpperCase(tool.inputSchema());
                inputSchemaJson = MAPPER
                    .writeValueAsString(convertedSchema);
            } catch (Exception e) {
                log.warn("Failed to serialize inputSchema for {}: {}", tool.name(), e.getMessage());
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

    @Override
    public Map<String, Boolean> getCapabilities() {
        return Map.of(
            "native_tool_calling", true,
            "structured_output", true,   // Via prompt hints (not native response_format due to Spring AI bug)
            "streaming", true,
            "vision", true,
            "json_mode", false,          // No native JSON mode (Spring AI bug prevents it)
            "large_context", true
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     * Delegates to shared {@link MessageConverter} with Gemini-specific bundling.
     *
     * <p>Gemini requires:
     * <ul>
     *   <li>"model" as an alias for "assistant" role</li>
     *   <li>Consecutive tool responses bundled into a single ToolResponseMessage</li>
     * </ul>
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        return MessageConverter.convertMessagesWithBundledToolResponses(messages).messages();
    }
}
