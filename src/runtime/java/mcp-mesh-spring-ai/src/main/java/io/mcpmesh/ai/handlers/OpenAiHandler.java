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
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.ResponseFormat;
import org.springframework.ai.openai.api.ResponseFormat.Type;
import org.springframework.ai.tool.ToolCallback;

import java.util.*;

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

        String outputMode = determineOutputMode(outputSchema);
        boolean hasTools = tools != null && !tools.isEmpty();

        // Delegate to Rust core
        String schemaJson = null;
        String schemaName = null;
        if (outputSchema != null) {
            schemaName = outputSchema.name();
            try {
                schemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(outputSchema.schema());
            } catch (Exception e) {
                log.warn("Failed to serialize schema for Rust core: {}", e.getMessage());
            }
        }

        String result = MeshCoreBridge.formatSystemPrompt(
            "openai", basePrompt, hasTools, false, schemaJson, schemaName, outputMode);
        if (result != null) {
            return result;
        }

        // Fallback: Java implementation
        StringBuilder systemContent = new StringBuilder(basePrompt != null ? basePrompt : "");

        if (hasTools) {
            systemContent.append(BASE_TOOL_INSTRUCTIONS);
        }

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
     * Delegates to shared {@link MessageConverter}.
     *
     * <p>Note: OpenAI's original implementation passed system messages through individually
     * (no accumulation). The shared converter accumulates them, which is functionally
     * equivalent since the downstream code extracts the system message anyway.
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        return MessageConverter.convertMessages(messages).messages();
    }
}
