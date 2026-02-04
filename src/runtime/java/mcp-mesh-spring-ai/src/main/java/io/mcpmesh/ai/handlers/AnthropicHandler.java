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

import java.util.*;
import java.util.function.Function;

/**
 * LLM provider handler for Anthropic Claude models.
 *
 * <p>Handles Claude-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>System message handling (Claude prefers single system message)</li>
 *   <li>Structured output with HINT mode (prompt-based)</li>
 *   <li>DECISION GUIDE for tool vs. direct JSON response decisions</li>
 *   <li>Anti-XML tool calling instructions</li>
 * </ul>
 *
 * <h2>Structured Output Modes (TEXT + HINT only)</h2>
 * <ul>
 *   <li><b>text</b>: Plain text output for String return types (fastest)</li>
 *   <li><b>hint</b>: JSON schema in prompt with DECISION GUIDE (~95% reliable)</li>
 * </ul>
 *
 * <p>Native response_format (strict mode) is not used due to cross-runtime
 * incompatibilities when tools are present, and grammar compilation overhead.
 *
 * @see LlmProviderHandler
 */
public class AnthropicHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(AnthropicHandler.class);

    /** Base tool instructions for Claude */
    private static final String BASE_TOOL_INSTRUCTIONS = """


        TOOL CALLING INSTRUCTIONS:
        - Use the provided tools when you need to gather information or perform actions
        - Make ONE tool call at a time and wait for the result
        - NEVER use XML-style syntax like <invoke> or <function_calls> - use only the native tool calling format
        - After receiving tool results, incorporate them into your response
        - If a tool call fails, explain the error and try an alternative approach
        """;

    @Override
    public String getVendor() {
        return "anthropic";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"claude"};
    }

    // =========================================================================
    // Structured Output Methods
    // =========================================================================

    @Override
    public String determineOutputMode(OutputSchema outputSchema) {
        if (outputSchema == null) {
            return OUTPUT_MODE_TEXT;
        }
        // All schemas use HINT mode for Claude -- no STRICT mode
        return OUTPUT_MODE_HINT;
    }

    @Override
    public String formatSystemPrompt(
            String basePrompt,
            List<ToolDefinition> tools,
            OutputSchema outputSchema) {

        StringBuilder systemContent = new StringBuilder(basePrompt != null ? basePrompt : "");
        String outputMode = determineOutputMode(outputSchema);

        // Add tool calling instructions if tools available
        if (tools != null && !tools.isEmpty()) {
            systemContent.append(BASE_TOOL_INSTRUCTIONS);
        }

        // Add output format instructions based on mode
        if (OUTPUT_MODE_TEXT.equals(outputMode)) {
            // Text mode: No JSON instructions
            // Do nothing
        } else if (OUTPUT_MODE_HINT.equals(outputMode)) {
            // Hint mode: Add detailed JSON schema instructions with DECISION GUIDE
            if (outputSchema != null) {
                systemContent.append(buildHintModeInstructions(outputSchema, tools));
            }
        }

        return systemContent.toString();
    }

    /**
     * Build detailed JSON schema instructions for hint mode with optional DECISION GUIDE.
     *
     * @param outputSchema the output schema to build instructions for
     * @param tools the list of available tools (DECISION GUIDE added when non-empty)
     */
    @SuppressWarnings("unchecked")
    private String buildHintModeInstructions(OutputSchema outputSchema, List<ToolDefinition> tools) {
        // Sanitize schema to remove unsupported validation keywords (minimum, maximum, etc.)
        Map<String, Object> schema = outputSchema.sanitize();
        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        List<String> required = schema.get("required") != null ?
            (List<String>) schema.get("required") : List.of();

        if (properties == null || properties.isEmpty()) {
            return "\n\nRespond with valid JSON.";
        }

        // Build human-readable schema description
        StringBuilder fieldDescriptions = new StringBuilder();
        Map<String, String> exampleValues = new LinkedHashMap<>();

        for (Map.Entry<String, Object> entry : properties.entrySet()) {
            String fieldName = entry.getKey();
            Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();

            String fieldType = (String) fieldSchema.getOrDefault("type", "any");
            boolean isRequired = required.contains(fieldName);
            String reqMarker = isRequired ? " (required)" : " (optional)";
            String desc = (String) fieldSchema.get("description");
            String descText = desc != null ? " - " + desc : "";

            fieldDescriptions.append("  - ")
                .append(fieldName)
                .append(": ")
                .append(fieldType)
                .append(reqMarker)
                .append(descText)
                .append("\n");

            // Build example value
            exampleValues.put(fieldName, "<" + fieldType + ">");
        }

        // Build example JSON
        StringBuilder exampleJson = new StringBuilder("{\n");
        int i = 0;
        for (Map.Entry<String, String> entry : exampleValues.entrySet()) {
            exampleJson.append("  \"").append(entry.getKey()).append("\": \"").append(entry.getValue()).append("\"");
            if (i < exampleValues.size() - 1) {
                exampleJson.append(",");
            }
            exampleJson.append("\n");
            i++;
        }
        exampleJson.append("}");

        // Add DECISION GUIDE when tools are present
        String decisionGuide = "";
        if (tools != null && !tools.isEmpty()) {
            decisionGuide = """

            DECISION GUIDE:
            - If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
            - If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.
            - After calling a tool and receiving results, STOP calling tools and return your final JSON response.
            """;
        }

        return String.format("""

            %s
            RESPONSE FORMAT:
            You MUST respond with valid JSON matching this schema:
            {
            %s}

            Example format:
            %s

            CRITICAL: Your response must be ONLY the raw JSON object.
            - DO NOT wrap in markdown code fences (```json or ```)
            - DO NOT include any text before or after the JSON
            - Start directly with { and end with }""",
            decisionGuide, fieldDescriptions.toString(), exampleJson.toString());
    }

    // =========================================================================
    // Generation Methods
    // =========================================================================

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("AnthropicHandler: Processing {} messages", messages.size());

        List<Message> springMessages = convertMessages(messages);
        Prompt prompt = new Prompt(springMessages);
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getText();
        log.debug("AnthropicHandler: Generated response ({} chars)",
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

        log.debug("AnthropicHandler: Processing {} messages with {} tools, outputSchema={}, executeTools={}",
            messages.size(),
            tools != null ? tools.size() : 0,
            outputSchema != null ? outputSchema.name() : "none",
            toolExecutor != null);

        String outputMode = determineOutputMode(outputSchema);
        log.debug("AnthropicHandler: Using output mode: {}", outputMode);

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

        // Format system prompt with structured output instructions
        String formattedSystemPrompt = formatSystemPrompt(systemPrompt, tools, outputSchema);

        if (executeTools) {
            // Auto-execution mode: Use ChatClient which handles tool execution automatically
            return generateWithToolsAutoExecute(model, springMessages, tools, toolExecutor, formattedSystemPrompt);
        } else {
            // No-execution mode: Use model.call with internalToolExecutionEnabled(false)
            return generateWithToolsNoExecute(model, springMessages, tools, formattedSystemPrompt);
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
            String formattedSystemPrompt) {

        // Convert tools to Spring AI ToolCallback objects
        List<ToolCallback> toolCallbacks = new ArrayList<>();
        if (tools != null && !tools.isEmpty()) {
            for (ToolDefinition tool : tools) {
                ToolCallback callback = createToolCallback(tool, toolExecutor);
                toolCallbacks.add(callback);
            }
            log.debug("Created {} tool callbacks for ChatClient", toolCallbacks.size());
        }

        // Extract non-system messages for user content
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
                userContent.append("[Previous Assistant Response]\n").append(am.getText());
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

        // Add tools if present - Spring AI handles tool execution automatically
        if (!toolCallbacks.isEmpty()) {
            requestSpec.toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]));
        }

        // Execute the request
        String content = requestSpec.call().content();

        log.debug("AnthropicHandler: Generated response ({} chars)",
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
            String formattedSystemPrompt) {

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

        // Build chat options with tool execution DISABLED
        org.springframework.ai.model.tool.ToolCallingChatOptions chatOptions =
            org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                .toolCallbacks(toolCallbacks)
                .internalToolExecutionEnabled(false)  // Don't auto-execute tools!
                .build();

        // Create prompt with options
        org.springframework.ai.chat.prompt.Prompt prompt =
            new org.springframework.ai.chat.prompt.Prompt(messagesWithFormattedSystem, chatOptions);

        log.debug("Calling Claude with {} tools (execution disabled)", tools != null ? tools.size() : 0);

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

        log.debug("AnthropicHandler: Extracted content={} chars, toolCalls={}",
            content != null ? content.length() : 0,
            toolCalls.size());

        return new LlmResponse(content, toolCalls);
    }

    /**
     * Create ToolCallbacks for schema only (no execution).
     */
    private List<ToolCallback> createToolCallbacksForSchema(List<ToolDefinition> tools) {
        List<ToolCallback> callbacks = new ArrayList<>();
        if (tools == null) return callbacks;

        for (ToolDefinition tool : tools) {
            // Create a dummy function that should never be called
            Function<Map<String, Object>, String> dummyFunction = args -> {
                log.warn("Tool {} was unexpectedly called - this shouldn't happen!", tool.name());
                return "{\"error\": \"Tool execution not supported in provider mode\"}";
            };

            // Convert inputSchema Map to JSON string
            String inputSchemaJson = null;
            if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
                try {
                    inputSchemaJson = new tools.jackson.databind.ObjectMapper()
                        .writeValueAsString(tool.inputSchema());
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
     * Create a Spring AI ToolCallback from our ToolDefinition.
     *
     * <p>Claude requires explicit JSON schema for function parameters.
     * We pass the schema from ToolDefinition directly to avoid Spring AI
     * generating an empty schema from Map.class.
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

        // Convert inputSchema Map to JSON string for Claude
        String inputSchemaJson = null;
        if (tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
            try {
                inputSchemaJson = new tools.jackson.databind.ObjectMapper()
                    .writeValueAsString(tool.inputSchema());
                log.debug("Tool {} inputSchema: {}", tool.name(), inputSchemaJson);
            } catch (Exception e) {
                log.warn("Failed to serialize inputSchema for {}: {}", tool.name(), e.getMessage());
            }
        }

        @SuppressWarnings("unchecked")
        var builder = FunctionToolCallback
            .builder(tool.name(), toolFunction)
            .description(tool.description() != null ? tool.description() : "No description")
            .inputType((Class<Map<String, Object>>) (Class<?>) Map.class);

        // Pass the explicit JSON schema if available
        if (inputSchemaJson != null) {
            builder.inputSchema(inputSchemaJson);
        }

        return builder.build();
    }

    @Override
    public Map<String, Boolean> getCapabilities() {
        return Map.of(
            "native_tool_calling", true,
            "structured_output", false,  // Uses HINT mode (prompt-based), not native response_format
            "streaming", true,
            "vision", true,
            "json_mode", false,          // No native JSON mode used
            "prompt_caching", false      // Not implemented yet in Java
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
     */
    @SuppressWarnings("unchecked")
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        List<Message> result = new ArrayList<>();
        StringBuilder systemContent = new StringBuilder();

        // Build a map of tool_call_id -> tool_name from assistant messages
        Map<String, String> toolCallIdToName = new HashMap<>();
        for (Map<String, Object> msg : messages) {
            if ("assistant".equalsIgnoreCase((String) msg.get("role"))) {
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

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null) {
                continue;
            }

            switch (role.toLowerCase()) {
                case "system" -> {
                    if (content != null && !content.trim().isEmpty()) {
                        if (systemContent.length() > 0) {
                            systemContent.append("\n\n");
                        }
                        systemContent.append(content);
                    }
                }
                case "user" -> {
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
                case "assistant" -> {
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
                    String toolName = (String) msg.get("name");
                    if (toolName == null) {
                        toolName = toolCallIdToName.get(toolCallId);
                    }
                    if (toolName == null) {
                        toolName = "unknown_tool";
                        log.warn("Could not determine tool name for tool_call_id: {}", toolCallId);
                    }
                    String responseData = content != null ? content : "";
                    log.debug("Converted tool result: id={}, name={}, contentLength={}",
                        toolCallId, toolName, responseData.length());

                    // Create ToolResponseMessage with proper ToolResponse
                    ToolResponseMessage.ToolResponse toolResponse =
                        new ToolResponseMessage.ToolResponse(toolCallId, toolName, responseData);
                    result.add(ToolResponseMessage.builder()
                        .responses(List.of(toolResponse))
                        .build());
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
            }
        }

        if (systemContent.length() > 0) {
            result.add(0, new SystemMessage(systemContent.toString()));
        }

        return result;
    }
}
