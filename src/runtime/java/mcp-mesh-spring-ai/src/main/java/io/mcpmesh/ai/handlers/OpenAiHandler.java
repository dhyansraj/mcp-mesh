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
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.ResponseFormat;
import org.springframework.ai.openai.api.ResponseFormat.Type;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;

import java.util.*;
import java.util.function.Function;

/**
 * LLM provider handler for OpenAI GPT models.
 *
 * <p>Handles OpenAI-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>Structured output via response_format parameter</li>
 *   <li>Native function calling</li>
 *   <li>Strict JSON schema enforcement</li>
 * </ul>
 *
 * <h2>Structured Output</h2>
 * <p>OpenAI uses response_format parameter for guaranteed JSON schema compliance.
 * This is the KEY difference from Claude (which uses prompt hints for simple schemas).
 * All properties must be in the required array for OpenAI strict mode.
 *
 * @see LlmProviderHandler
 */
public class OpenAiHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(OpenAiHandler.class);

    /** Base tool instructions for OpenAI */
    private static final String BASE_TOOL_INSTRUCTIONS = """


        TOOL CALLING INSTRUCTIONS:
        - Use the provided tools when you need to gather information or perform actions
        - Make ONE tool call at a time and wait for the result
        - After receiving tool results, incorporate them into your response
        - If a tool call fails, explain the error and try an alternative approach
        """;

    @Override
    public String getVendor() {
        return "openai";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"gpt"};
    }

    // =========================================================================
    // Structured Output Methods
    // =========================================================================

    @Override
    public String determineOutputMode(OutputSchema outputSchema) {
        // OpenAI always uses strict mode (response_format) for structured output
        return outputSchema == null ? OUTPUT_MODE_TEXT : OUTPUT_MODE_STRICT;
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

        // OpenAI: NO detailed JSON schema in prompt - response_format handles it
        // Just add a brief note for context
        if (outputSchema != null) {
            systemContent.append("\n\nYour final response will be structured as JSON matching the ")
                .append(outputSchema.name())
                .append(" format.");
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

        log.debug("OpenAiHandler: Processing {} messages", messages.size());

        List<Message> springMessages = convertMessages(messages);
        Prompt prompt = new Prompt(springMessages);
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getText();
        log.debug("OpenAiHandler: Generated response ({} chars)",
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

        log.debug("OpenAiHandler: Processing {} messages with {} tools, outputSchema={}, executeTools={}",
            messages.size(),
            tools != null ? tools.size() : 0,
            outputSchema != null ? outputSchema.name() : "none",
            toolExecutor != null);

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

        // If toolExecutor is null, use no-execution mode (return tool_calls without executing)
        boolean executeTools = toolExecutor != null;

        if (executeTools) {
            // Auto-execution mode: Use ChatClient which handles tool execution automatically
            return generateWithToolsAutoExecute(model, springMessages, tools, toolExecutor, formattedSystemPrompt, outputSchema, messages);
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
            OutputSchema outputSchema,
            List<Map<String, Object>> originalMessages) {

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

        // Apply response_format immediately when outputSchema is present (like Python)
        if (outputSchema != null) {
            try {
                // Make schema strict (add additionalProperties: false, all properties required)
                Map<String, Object> strictSchema = outputSchema.makeStrict(true);

                ResponseFormat responseFormat = ResponseFormat.builder()
                    .type(Type.JSON_SCHEMA)
                    .jsonSchema(ResponseFormat.JsonSchema.builder()
                        .name(outputSchema.name())
                        .schema(strictSchema)
                        .strict(true)
                        .build())
                    .build();

                OpenAiChatOptions chatOptions = OpenAiChatOptions.builder()
                    .responseFormat(responseFormat)
                    .build();

                requestSpec.options(chatOptions);
                log.debug("Applied OpenAI response_format with schema: {}", outputSchema.name());
            } catch (Exception e) {
                log.warn("Failed to apply response_format for {}: {}", outputSchema.name(), e.getMessage());
            }
        }

        // Execute the request
        String content = requestSpec.call().content();

        log.debug("OpenAiHandler: Generated response ({} chars)",
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

        // Build prompt with chat options
        Prompt prompt;

        // Apply response_format immediately when outputSchema is present (like Python)
        if (outputSchema != null) {
            try {
                // Make schema strict (add additionalProperties: false, all properties required)
                Map<String, Object> strictSchema = outputSchema.makeStrict(true);

                ResponseFormat responseFormat = ResponseFormat.builder()
                    .type(Type.JSON_SCHEMA)
                    .jsonSchema(ResponseFormat.JsonSchema.builder()
                        .name(outputSchema.name())
                        .schema(strictSchema)
                        .strict(true)
                        .build())
                    .build();

                // Use OpenAiChatOptions which supports both tools and response_format
                OpenAiChatOptions chatOptions = OpenAiChatOptions.builder()
                    .toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]))
                    .internalToolExecutionEnabled(false)
                    .responseFormat(responseFormat)
                    .build();

                prompt = new Prompt(messagesWithFormattedSystem, chatOptions);
                log.debug("Applied OpenAI response_format with schema: {}", outputSchema.name());
            } catch (Exception e) {
                log.warn("Failed to apply response_format for {}: {}, falling back to basic options",
                    outputSchema.name(), e.getMessage());
                // Fallback to basic options without response_format
                org.springframework.ai.model.tool.ToolCallingChatOptions chatOptions =
                    org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                        .toolCallbacks(toolCallbacks)
                        .internalToolExecutionEnabled(false)
                        .build();
                prompt = new Prompt(messagesWithFormattedSystem, chatOptions);
            }
        } else {
            // No structured output needed
            org.springframework.ai.model.tool.ToolCallingChatOptions chatOptions =
                org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                    .toolCallbacks(toolCallbacks)
                    .internalToolExecutionEnabled(false)
                    .build();
            prompt = new Prompt(messagesWithFormattedSystem, chatOptions);
        }

        log.debug("Calling OpenAI with {} tools (execution disabled)", tools != null ? tools.size() : 0);

        // Single call - handles both tool calling AND structured output
        ChatResponse response = model.call(prompt);

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

        log.debug("OpenAiHandler: Extracted content={} chars, toolCalls={}",
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
     * <p>OpenAI requires explicit JSON schema for function parameters.
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

        // Convert inputSchema Map to JSON string for OpenAI
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
            "structured_output", true,
            "streaming", true,
            "vision", true,
            "json_mode", true
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

            Message springMessage = switch (role.toLowerCase()) {
                case "system" -> {
                    if (content == null || content.trim().isEmpty()) {
                        yield null;
                    }
                    yield new SystemMessage(content);
                }
                case "user" -> {
                    if (content == null || content.trim().isEmpty()) {
                        yield null;
                    }
                    yield new UserMessage(content);
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
                        yield AssistantMessage.builder()
                            .content(content != null ? content : "")
                            .toolCalls(springToolCalls)
                            .build();
                    }
                    if (content == null || content.trim().isEmpty()) {
                        yield null;
                    }
                    yield new AssistantMessage(content);
                }
                case "tool" -> {
                    // Tool result message - must have tool_call_id
                    String toolCallId = (String) msg.get("tool_call_id");
                    if (toolCallId == null) {
                        log.warn("Tool message missing tool_call_id, skipping");
                        yield null;
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
                    yield ToolResponseMessage.builder()
                        .responses(List.of(toolResponse))
                        .build();
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    if (content == null || content.trim().isEmpty()) {
                        yield null;
                    }
                    yield new UserMessage(content);
                }
            };

            if (springMessage != null) {
                result.add(springMessage);
            }
        }

        return result;
    }
}
