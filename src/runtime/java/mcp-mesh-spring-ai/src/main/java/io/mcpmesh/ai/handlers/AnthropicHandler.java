package io.mcpmesh.ai.handlers;

import io.mcpmesh.core.MeshCoreBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.anthropic.AnthropicChatOptions;
import org.springframework.ai.anthropic.api.AnthropicApi.ChatCompletionRequest.OutputFormat;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.tool.ToolCallback;

import java.util.*;

/**
 * LLM provider handler for Anthropic Claude models.
 *
 * <p>Handles Claude-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>System message handling (Claude prefers single system message)</li>
 *   <li>Native structured output via {@code output_format} (response_format)</li>
 *   <li>DECISION GUIDE for tool vs. direct JSON response decisions</li>
 *   <li>Anti-XML tool calling instructions</li>
 * </ul>
 *
 * <h2>Structured Output Strategy</h2>
 * <p>Uses a dual strategy for reliable structured output:
 * <ol>
 *   <li><b>Native enforcement</b>: {@code output_format} with {@code json_schema} type
 *       via {@link AnthropicChatOptions} — guarantees schema compliance (100% reliable)</li>
 *   <li><b>Prompt hint</b>: Brief note in system prompt for context —
 *       the native enforcement does the heavy lifting</li>
 * </ol>
 *
 * <p>This matches the Python SDK's approach where {@code response_format} handles
 * enforcement and prompt instructions are minimal.
 *
 * @see LlmProviderHandler
 */
public class AnthropicHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(AnthropicHandler.class);

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
        return OUTPUT_MODE_STRICT;
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

        boolean hasMediaParams = false;
        if (tools != null) {
            for (ToolDefinition tool : tools) {
                if (tool.inputSchema() != null) {
                    try {
                        String toolSchemaJson = TOOL_CALLBACK_MAPPER.writeValueAsString(tool.inputSchema());
                        try {
                            if (MeshCoreBridge.detectMediaParams(toolSchemaJson)) {
                                hasMediaParams = true;
                                break;
                            }
                        } catch (UnsatisfiedLinkError e) {
                            // Native library unavailable (e.g., CI) — safe default
                        }
                    } catch (Exception ignored) {}
                }
            }
        }

        return MeshCoreBridge.formatSystemPrompt(
            "anthropic", basePrompt, hasTools, hasMediaParams, schemaJson, schemaName, outputMode);
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

        // Apply native output_format when outputSchema is present
        if (outputSchema != null) {
            try {
                Map<String, Object> sanitizedSchema = outputSchema.sanitize();
                OutputFormat outputFormat = new OutputFormat("json_schema", sanitizedSchema);

                AnthropicChatOptions chatOptions = AnthropicChatOptions.builder()
                    .outputFormat(outputFormat)
                    .build();

                requestSpec.options(chatOptions);
                log.debug("Applied Anthropic output_format with schema: {}", outputSchema.name());
            } catch (Exception e) {
                log.warn("Failed to apply output_format for {}: {}", outputSchema.name(), e.getMessage());
            }
        }

        // Execute the request — if outputFormat was applied and the API rejects it,
        // retry with HINT-mode instructions instead of native output_format
        ChatResponse chatResponse;
        try {
            chatResponse = requestSpec.call().chatResponse();
        } catch (Exception e) {
            if (outputSchema != null) {
                log.warn("ChatClient call failed with output_format ({}), retrying with HINT mode: {}",
                    outputSchema.name(), e.getMessage());

                // Rebuild request without output_format, using HINT-mode system prompt
                String hintSystemPrompt = formatSystemPromptForHintFallback(formattedSystemPrompt, outputSchema, tools);

                ChatClient.ChatClientRequestSpec retrySpec = chatClient.prompt();
                if (hintSystemPrompt != null && !hintSystemPrompt.isEmpty()) {
                    retrySpec.system(hintSystemPrompt);
                }
                retrySpec.user(userContent.toString());
                if (!toolCallbacks.isEmpty()) {
                    retrySpec.toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]));
                }
                // No output_format applied — rely on HINT instructions
                chatResponse = retrySpec.call().chatResponse();
            } else {
                throw e;
            }
        }

        String content = chatResponse.getResult() != null ? chatResponse.getResult().getOutput().getText() : null;
        log.debug("AnthropicHandler: Generated response ({} chars)",
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

        // Build prompt with chat options
        org.springframework.ai.chat.prompt.Prompt prompt;

        // Apply native output_format when outputSchema is present
        if (outputSchema != null) {
            try {
                Map<String, Object> sanitizedSchema = outputSchema.sanitize();
                OutputFormat outputFormat = new OutputFormat("json_schema", sanitizedSchema);

                AnthropicChatOptions chatOptions = AnthropicChatOptions.builder()
                    .toolCallbacks(toolCallbacks)
                    .internalToolExecutionEnabled(false)
                    .outputFormat(outputFormat)
                    .build();

                prompt = new org.springframework.ai.chat.prompt.Prompt(messagesWithFormattedSystem, chatOptions);
                log.debug("Applied Anthropic output_format with schema: {}", outputSchema.name());
            } catch (Exception e) {
                log.warn("Failed to apply output_format for {}: {}, falling back to basic options",
                    outputSchema.name(), e.getMessage());
                org.springframework.ai.model.tool.ToolCallingChatOptions chatOptions =
                    org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                        .toolCallbacks(toolCallbacks)
                        .internalToolExecutionEnabled(false)
                        .build();
                prompt = new org.springframework.ai.chat.prompt.Prompt(messagesWithFormattedSystem, chatOptions);
            }
        } else {
            // No structured output needed
            org.springframework.ai.model.tool.ToolCallingChatOptions chatOptions =
                org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                    .toolCallbacks(toolCallbacks)
                    .internalToolExecutionEnabled(false)
                    .build();
            prompt = new org.springframework.ai.chat.prompt.Prompt(messagesWithFormattedSystem, chatOptions);
        }

        log.debug("Calling Claude with {} tools (execution disabled)", tools != null ? tools.size() : 0);

        // Call model — if outputFormat was applied and the API rejects it,
        // retry with HINT-mode instructions instead of native output_format
        org.springframework.ai.chat.model.ChatResponse response;
        try {
            response = model.call(prompt);
        } catch (Exception e) {
            if (outputSchema != null) {
                log.warn("model.call failed with output_format ({}), retrying with HINT mode: {}",
                    outputSchema.name(), e.getMessage());

                // Rebuild with HINT-mode detailed instructions
                String hintSystemPrompt = formatSystemPromptForHintFallback(formattedSystemPrompt, outputSchema, tools);

                // Rebuild messages with hint system prompt
                List<Message> hintMessages = new ArrayList<>();
                hintMessages.add(new SystemMessage(hintSystemPrompt));
                for (Message msg : messagesWithFormattedSystem) {
                    if (!(msg instanceof SystemMessage)) {
                        hintMessages.add(msg);
                    }
                }

                // Rebuild prompt without outputFormat
                org.springframework.ai.model.tool.ToolCallingChatOptions hintOptions =
                    org.springframework.ai.model.tool.ToolCallingChatOptions.builder()
                        .toolCallbacks(toolCallbacks)
                        .internalToolExecutionEnabled(false)
                        .build();
                prompt = new org.springframework.ai.chat.prompt.Prompt(hintMessages, hintOptions);

                response = model.call(prompt);
            } else {
                throw e;
            }
        }

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

        return new LlmResponse(content, toolCalls, extractUsage(response));
    }

    /**
     * Extract token usage metadata from a ChatResponse.
     */
    private UsageMeta extractUsage(ChatResponse response) {
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
            return new UsageMeta((int) input, (int) output, model);
        } catch (Exception e) {
            log.debug("Failed to extract usage metadata: {}", e.getMessage());
            return null;
        }
    }

    /**
     * Build a fallback system prompt that replaces STRICT-mode native enforcement
     * with detailed HINT-mode JSON schema instructions. Used when the API rejects
     * the native output_format and we need to retry with prompt-based enforcement.
     */
    private String formatSystemPromptForHintFallback(String currentSystemPrompt, OutputSchema outputSchema, List<ToolDefinition> tools) {
        return currentSystemPrompt + "\n\n" + buildHintModeInstructions(outputSchema, tools);
    }

    @Override
    public Map<String, Boolean> getCapabilities() {
        return Map.of(
            "native_tool_calling", true,
            "structured_output", true,   // Native output_format with json_schema
            "streaming", true,
            "vision", true,
            "json_mode", true,           // Via output_format json_schema
            "prompt_caching", false      // Not implemented yet in Java
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     * Delegates to shared {@link MessageConverter}.
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        return MessageConverter.convertMessages(messages).messages();
    }
}
