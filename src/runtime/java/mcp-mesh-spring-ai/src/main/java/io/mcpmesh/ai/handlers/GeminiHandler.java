package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.ToolResponseMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.ai.google.genai.GoogleGenAiChatOptions;

import java.util.*;
import java.util.LinkedHashMap;
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

    /** Base tool instructions for Gemini */
    private static final String BASE_TOOL_INSTRUCTIONS = """


        TOOL CALLING INSTRUCTIONS:
        - Use the provided tools when you need to gather information or perform actions
        - Make ONE tool call at a time and wait for the result
        - After receiving tool results, incorporate them into your response
        - If a tool call fails, explain the error and try an alternative approach
        """;

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
        // Gemini Java: HINT mode only -- Spring AI 2.0.0-M2 has a bug where
        // responseMimeType + responseSchema alongside tools causes tool args to become {}.
        // This is NOT a Gemini API issue; it's a Spring AI request construction bug.
        return outputSchema == null ? OUTPUT_MODE_TEXT : OUTPUT_MODE_HINT;
    }

    @Override
    public String formatSystemPrompt(
            String basePrompt,
            List<ToolDefinition> tools,
            OutputSchema outputSchema) {

        StringBuilder systemContent = new StringBuilder(basePrompt != null ? basePrompt : "");

        // Add tool calling instructions if tools available
        if (tools != null && !tools.isEmpty()) {
            systemContent.append(BASE_TOOL_INSTRUCTIONS);
        }

        // Add output format instructions
        if (outputSchema != null) {
            systemContent.append("\n\n");

            // Add DECISION GUIDE when tools are present (aligned with Python/TypeScript)
            if (tools != null && !tools.isEmpty()) {
                systemContent.append("DECISION GUIDE:\n")
                    .append("- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.\n")
                    .append("- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.\n")
                    .append("- After calling a tool and receiving results, STOP calling tools and return your final JSON response.\n\n");
            }

            systemContent.append("RESPONSE FORMAT (for your final response after any tool calls):\n")
                .append("Your final response must be ONLY valid JSON (no markdown, no code blocks) with this exact structure:\n")
                .append("{\n");

            // Sanitize schema to remove unsupported validation keywords (minimum, maximum, etc.)
            @SuppressWarnings("unchecked")
            Map<String, Object> properties = (Map<String, Object>) outputSchema.sanitize().get("properties");
            if (properties != null) {
                int i = 0;
                for (Map.Entry<String, Object> entry : properties.entrySet()) {
                    String propName = entry.getKey();
                    @SuppressWarnings("unchecked")
                    Map<String, Object> propSchema = (Map<String, Object>) entry.getValue();
                    String propType = (String) propSchema.get("type");

                    // Show example value based on type
                    String exampleValue;
                    if ("string".equals(propType)) {
                        exampleValue = "\"<your " + propName + " here>\"";
                    } else if ("number".equals(propType) || "integer".equals(propType)) {
                        exampleValue = "0";
                    } else if ("array".equals(propType)) {
                        exampleValue = "[\"item1\", \"item2\"]";
                    } else if ("boolean".equals(propType)) {
                        exampleValue = "true";
                    } else if ("object".equals(propType)) {
                        exampleValue = "{}";
                    } else {
                        exampleValue = "...";
                    }

                    systemContent.append("  \"").append(propName).append("\": ").append(exampleValue);
                    if (i < properties.size() - 1) {
                        systemContent.append(",");
                    }
                    systemContent.append("\n");
                    i++;
                }
            }

            systemContent.append("}\n\n")
                .append("Do NOT wrap the response in a type name key like {\"").append(outputSchema.name()).append("\": {...}}. Return the flat JSON object directly.\n")
                .append("Return ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks.");
        }

        return systemContent.toString();
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

        String content = response.getResult().getOutput().getText();
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
        String content = requestSpec.call().content();

        log.debug("GeminiHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return new LlmResponse(content, List.of());
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

        // Build Gemini-specific chat options with tool execution DISABLED and response_format
        GoogleGenAiChatOptions.Builder geminiOptionsBuilder = GoogleGenAiChatOptions.builder()
            .toolCallbacks(toolCallbacks)
            .internalToolExecutionEnabled(false);  // Don't auto-execute tools!

        // Don't use responseSchema - Spring AI has issues with Gemini responseSchema
        // Structured output is handled via prompt-based hints in formatSystemPrompt()
        log.debug("Using prompt-based JSON hints for structured output (not responseSchema)");

        GoogleGenAiChatOptions chatOptions = geminiOptionsBuilder.build();

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

        return new LlmResponse(content, toolCalls);
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
            String schemaJson = new tools.jackson.databind.ObjectMapper()
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
     */
    private List<ToolCallback> createToolCallbacksForSchema(List<ToolDefinition> tools) {
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
                    inputSchemaJson = new tools.jackson.databind.ObjectMapper()
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

        // Convert "type" to uppercase
        if (result.containsKey("type") && result.get("type") instanceof String type) {
            result.put("type", type.toUpperCase());
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

        return result;
    }

    /**
     * Create a Spring AI ToolCallback from our ToolDefinition.
     */
    private ToolCallback createToolCallback(ToolDefinition tool, ToolExecutorCallback toolExecutor) {
        Function<Map<String, Object>, String> toolFunction = args -> {
            try {
                String argsJson = args != null ? new tools.jackson.databind.ObjectMapper()
                    .writeValueAsString(args) : "{}";
                return toolExecutor.execute(tool.name(), argsJson);
            } catch (Exception e) {
                log.error("Tool execution failed: {} - {}", tool.name(), e.getMessage());
                return "{\"error\": \"" + e.getMessage() + "\"}";
            }
        };

        // Convert inputSchema with uppercase types for Gemini API compatibility
        String inputSchemaJson = null;
        if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
            try {
                Map<String, Object> convertedSchema = convertSchemaTypesToUpperCase(tool.inputSchema());
                inputSchemaJson = new tools.jackson.databind.ObjectMapper()
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
     *
     * <p>Properly handles multi-turn tool conversations:
     * <ul>
     *   <li>Assistant messages with tool_calls -> AssistantMessage with ToolCall list</li>
     *   <li>Tool result messages -> ToolResponseMessage with proper tool_call_id</li>
     * </ul>
     *
     * <p>Note: Gemini requires tool name in function_response, so we build a map
     * from tool_call_id to tool name from preceding assistant messages.
     */
    @SuppressWarnings("unchecked")
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        List<Message> result = new ArrayList<>();
        StringBuilder systemContent = new StringBuilder();

        // Build a map of tool_call_id -> tool_name from assistant messages
        // Gemini requires function_response.name to be non-empty
        Map<String, String> toolCallIdToName = new HashMap<>();
        for (Map<String, Object> msg : messages) {
            if ("assistant".equalsIgnoreCase((String) msg.get("role")) ||
                "model".equalsIgnoreCase((String) msg.get("role"))) {
                List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) msg.get("tool_calls");
                if (toolCalls != null) {
                    for (Map<String, Object> tc : toolCalls) {
                        String tcId = (String) tc.get("id");
                        Map<String, Object> function = (Map<String, Object>) tc.get("function");
                        if (tcId != null && function != null) {
                            String toolName = (String) function.get("name");
                            if (toolName != null) {
                                toolCallIdToName.put(tcId, toolName);
                            }
                        }
                    }
                }
            }
        }

        // Collect consecutive tool responses to bundle into a single ToolResponseMessage
        // Gemini requires all tool results from a turn to be in one message
        List<ToolResponseMessage.ToolResponse> pendingToolResponses = new ArrayList<>();

        // Helper to flush pending tool responses into result
        Runnable flushPendingToolResponses = () -> {
            if (!pendingToolResponses.isEmpty()) {
                log.debug("Bundling {} tool responses into single ToolResponseMessage", pendingToolResponses.size());
                result.add(ToolResponseMessage.builder()
                    .responses(new ArrayList<>(pendingToolResponses))
                    .build());
                pendingToolResponses.clear();
            }
        };

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null) {
                continue;
            }

            switch (role.toLowerCase()) {
                case "system" -> {
                    // Flush any pending tool responses before adding non-tool message
                    flushPendingToolResponses.run();
                    // Gemini uses system_instruction, collect all system messages
                    if (content != null && !content.trim().isEmpty()) {
                        if (systemContent.length() > 0) {
                            systemContent.append("\n\n");
                        }
                        systemContent.append(content);
                    }
                }
                case "user" -> {
                    // Flush any pending tool responses before adding non-tool message
                    flushPendingToolResponses.run();
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
                case "assistant", "model" -> {
                    // Flush any pending tool responses before adding non-tool message
                    flushPendingToolResponses.run();
                    // Check for tool_calls in assistant message
                    List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) msg.get("tool_calls");
                    if (toolCalls != null && !toolCalls.isEmpty()) {
                        // Convert to Spring AI ToolCall format
                        List<AssistantMessage.ToolCall> springToolCalls = new ArrayList<>();
                        for (Map<String, Object> tc : toolCalls) {
                            String tcId = (String) tc.get("id");
                            String tcType = (String) tc.getOrDefault("type", "function");
                            Map<String, Object> function = (Map<String, Object>) tc.get("function");
                            if (function != null) {
                                String tcName = (String) function.get("name");
                                String tcArgs = (String) function.get("arguments");
                                if (tcId != null && tcName != null) {
                                    springToolCalls.add(new AssistantMessage.ToolCall(
                                        tcId, tcType, tcName, tcArgs != null ? tcArgs : "{}"
                                    ));
                                }
                            }
                        }
                        log.debug("Converted assistant message with {} tool calls", springToolCalls.size());
                        result.add(AssistantMessage.builder()
                            .content(content != null ? content : "")
                            .toolCalls(springToolCalls)
                            .build());
                    } else if (content != null && !content.trim().isEmpty()) {
                        result.add(new AssistantMessage(content));
                    }
                }
                case "tool" -> {
                    // Tool result message - must have tool_call_id
                    String toolCallId = (String) msg.get("tool_call_id");
                    if (toolCallId == null) {
                        log.warn("Tool message missing tool_call_id, skipping");
                        continue;
                    }
                    // Get tool name from message or from our map
                    // Gemini requires function_response.name to be non-empty
                    String toolName = (String) msg.get("name");
                    if (toolName == null) {
                        toolName = toolCallIdToName.get(toolCallId);
                    }
                    if (toolName == null) {
                        toolName = "unknown_tool";
                        log.warn("Could not determine tool name for tool_call_id: {} - Gemini may reject this", toolCallId);
                    }
                    String responseData = content != null ? content : "";
                    log.debug("Converted tool result: id={}, name={}, contentLength={}",
                        toolCallId, toolName, responseData.length());

                    // Add to pending list - will be bundled when we hit a non-tool message or end
                    ToolResponseMessage.ToolResponse toolResponse =
                        new ToolResponseMessage.ToolResponse(toolCallId, toolName, responseData);
                    pendingToolResponses.add(toolResponse);
                }
                default -> {
                    // Flush any pending tool responses before adding non-tool message
                    flushPendingToolResponses.run();
                    log.warn("Unknown message role '{}', treating as user", role);
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
            }
        }

        // Flush any remaining pending tool responses at the end
        flushPendingToolResponses.run();

        // Insert system instruction at the beginning if present
        if (systemContent.length() > 0) {
            result.add(0, new SystemMessage(systemContent.toString()));
        }

        return result;
    }
}
