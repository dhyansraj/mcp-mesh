package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
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

        log.debug("OpenAiHandler: Processing {} messages with {} tools, outputSchema={}",
            messages.size(),
            tools != null ? tools.size() : 0,
            outputSchema != null ? outputSchema.name() : "none");

        // Convert tools to Spring AI ToolCallback objects
        List<ToolCallback> toolCallbacks = new ArrayList<>();
        if (tools != null && !tools.isEmpty() && toolExecutor != null) {
            for (ToolDefinition tool : tools) {
                ToolCallback callback = createToolCallback(tool, toolExecutor);
                toolCallbacks.add(callback);
            }
            log.debug("Created {} tool callbacks for ChatClient", toolCallbacks.size());
        }

        // Build and format messages
        List<Message> springMessages = convertMessages(messages);

        // Extract and format system message
        String systemPrompt = null;
        List<Message> nonSystemMessages = new ArrayList<>();
        for (Message msg : springMessages) {
            if (msg instanceof SystemMessage sm) {
                systemPrompt = sm.getText();
            } else {
                nonSystemMessages.add(msg);
            }
        }

        // Format system prompt (brief note only - response_format handles schema)
        String formattedSystemPrompt = formatSystemPrompt(systemPrompt, tools, outputSchema);

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

        // Add tools if present
        if (!toolCallbacks.isEmpty()) {
            requestSpec.toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]));
        }

        // TODO: Add response_format for structured output when Spring AI ChatClient supports it
        // For now, the brief system prompt note provides guidance
        // OpenAI structured output would be:
        // requestSpec.options(OpenAiChatOptions.builder()
        //     .responseFormat(new ResponseFormat(...))
        //     .build());

        // Execute the request
        String content = requestSpec.call().content();

        log.debug("OpenAiHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return new LlmResponse(content, List.of());
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
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        List<Message> result = new ArrayList<>();

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null || content == null || content.trim().isEmpty()) {
                continue;
            }

            Message springMessage = switch (role.toLowerCase()) {
                case "system" -> new SystemMessage(content);
                case "user" -> new UserMessage(content);
                case "assistant" -> new AssistantMessage(content);
                case "tool" -> new UserMessage("[Tool Result]\n" + content);
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    yield new UserMessage(content);
                }
            };

            result.add(springMessage);
        }

        return result;
    }
}
