package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
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
        return formatSystemPromptViaCore(basePrompt, tools, outputSchema);
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
        // Plain-text generation: apply consumer-supplied model_params
        // (max_tokens/temperature/top_p/vendor-matched model) when present so the
        // no-tools/no-schema path honors them like the tools path does.
        Prompt prompt;
        if (LlmProviderHandler.hasAnyModelParam(options)) {
            OpenAiChatOptions.Builder optionsBuilder = OpenAiChatOptions.builder();
            applyModelParams(optionsBuilder, options);
            prompt = new Prompt(springMessages, optionsBuilder.build());
        } else {
            prompt = new Prompt(springMessages);
        }
        ChatResponse response = model.call(prompt);

        String content = response.getResult() != null && response.getResult().getOutput() != null
            ? response.getResult().getOutput().getText() : null;
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

        // Effective output mode: honor a consumer-supplied output_mode override
        // (model_params.output_mode → options), else per-vendor auto-selection.
        String outputMode = determineOutputMode(outputSchema, LlmProviderHandler.outputModeOverride(options));

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

        // Format system prompt with structured output instructions (effective mode).
        String formattedSystemPrompt = formatSystemPromptViaCore(systemPrompt, tools, outputSchema, outputMode);

        // OpenAI applies native response_format only for STRICT mode; hint/text
        // rely on prompt instructions (no response_format), so suppress the
        // schema for the enforcement path in those modes.
        OutputSchema enforcedSchema = OUTPUT_MODE_STRICT.equals(outputMode) ? outputSchema : null;

        // If toolExecutor is null, use no-execution mode (return tool_calls without executing)
        boolean executeTools = toolExecutor != null;

        if (executeTools) {
            // Auto-execution mode: Use ChatClient which handles tool execution automatically
            return generateWithToolsAutoExecute(model, springMessages, tools, toolExecutor, formattedSystemPrompt, enforcedSchema, messages, options);
        } else {
            // No-execution mode: Use model.call with internalToolExecutionEnabled(false)
            return generateWithToolsNoExecute(model, springMessages, tools, formattedSystemPrompt, enforcedSchema, options);
        }
    }

    /**
     * Apply the consumer-supplied {@code model_params} (max_tokens, temperature,
     * top_p, and a vendor-matched model override) onto an OpenAI options builder.
     * Absent keys are left untouched so Spring AI's own defaults apply. The
     * {@code model} override is honored only when its declared vendor matches
     * {@code openai}/{@code gpt}; on mismatch a warning is logged and the
     * provider's default model is kept.
     */
    private void applyModelParams(OpenAiChatOptions.Builder builder, Map<String, Object> options) {
        Integer maxTokens = LlmProviderHandler.maxTokensOption(options);
        if (maxTokens != null) {
            builder.maxTokens(maxTokens);
        }
        Double temperature = LlmProviderHandler.temperatureOption(options);
        if (temperature != null) {
            builder.temperature(temperature);
        }
        Double topP = LlmProviderHandler.topPOption(options);
        if (topP != null) {
            builder.topP(topP);
        }
        String modelOverride = LlmProviderHandler.resolveModelOverride(options, getVendor(), getAliases());
        if (modelOverride != null) {
            builder.model(modelOverride);
            log.debug("OpenAiHandler: applied model override '{}'", modelOverride);
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
            List<Map<String, Object>> originalMessages,
            Map<String, Object> options) {

        // Convert tools to Spring AI ToolCallback objects
        List<ToolCallback> toolCallbacks = new ArrayList<>();
        if (tools != null && !tools.isEmpty()) {
            for (ToolDefinition tool : tools) {
                ToolCallback callback = createToolCallback(tool, toolExecutor);
                toolCallbacks.add(callback);
            }
            log.debug("Created {} tool callbacks for ChatClient", toolCallbacks.size());
        }

        // Build user content from non-system messages
        String userContent = buildUserContent(springMessages);

        // Use ChatClient with tools
        ChatClient chatClient = ChatClient.create(model);
        ChatClient.ChatClientRequestSpec requestSpec = chatClient.prompt();

        // Add formatted system prompt
        if (formattedSystemPrompt != null && !formattedSystemPrompt.isEmpty()) {
            requestSpec.system(formattedSystemPrompt);
        }

        // Add user content
        requestSpec.user(userContent);

        // Add tools if present - Spring AI handles tool execution automatically
        if (!toolCallbacks.isEmpty()) {
            requestSpec.toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]));
        }

        // Apply response_format immediately when outputSchema is present (like Python),
        // plus any consumer-supplied model_params (max_tokens/temperature/top_p/model).
        // Build options whenever EITHER a schema OR model_params are present so the
        // numeric/model overrides reach the wire even without a schema.
        boolean hasModelParams = LlmProviderHandler.hasAnyModelParam(options);
        if (outputSchema != null || hasModelParams) {
            try {
                OpenAiChatOptions.Builder optionsBuilder = OpenAiChatOptions.builder();
                if (outputSchema != null) {
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
                    optionsBuilder.responseFormat(responseFormat);
                }
                applyModelParams(optionsBuilder, options);

                requestSpec.options(optionsBuilder.build());
                if (outputSchema != null) {
                    log.debug("Applied OpenAI response_format with schema: {}", outputSchema.name());
                }
            } catch (Exception e) {
                log.warn("Failed to apply OpenAI options (schema={}): {}",
                    outputSchema != null ? outputSchema.name() : "none", e.getMessage());
            }
        }

        // Execute the request
        ChatResponse chatResponse = requestSpec.call().chatResponse();
        String content = chatResponse.getResult() != null && chatResponse.getResult().getOutput() != null
            ? chatResponse.getResult().getOutput().getText() : null;

        log.debug("OpenAiHandler: Generated response ({} chars)",
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
            OutputSchema outputSchema,
            Map<String, Object> options) {

        // Replace system message with formatted one
        List<Message> messagesWithFormattedSystem = replaceSystemMessage(springMessages, formattedSystemPrompt);

        // Create tool callbacks for schema only (no execution)
        List<ToolCallback> toolCallbacks = createToolCallbacksForSchema(tools);

        // Build prompt with chat options
        Prompt prompt;

        // Apply response_format immediately when outputSchema is present (like Python),
        // plus any consumer-supplied model_params (max_tokens/temperature/top_p/model).
        // Always build OpenAiChatOptions (not the generic ToolCallingChatOptions) so
        // model_params apply even without a schema.
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
                OpenAiChatOptions.Builder optionsBuilder = OpenAiChatOptions.builder()
                    .toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]))
                    .internalToolExecutionEnabled(false)
                    .responseFormat(responseFormat);
                applyModelParams(optionsBuilder, options);

                prompt = new Prompt(messagesWithFormattedSystem, optionsBuilder.build());
                log.debug("Applied OpenAI response_format with schema: {}", outputSchema.name());
            } catch (Exception e) {
                log.warn("Failed to apply response_format for {}: {}, falling back to basic options",
                    outputSchema.name(), e.getMessage());
                // Fallback to OpenAiChatOptions without response_format (still apply model_params)
                OpenAiChatOptions.Builder optionsBuilder = OpenAiChatOptions.builder()
                    .toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]))
                    .internalToolExecutionEnabled(false);
                applyModelParams(optionsBuilder, options);
                prompt = new Prompt(messagesWithFormattedSystem, optionsBuilder.build());
            }
        } else {
            // No structured output needed — still apply model_params via OpenAiChatOptions.
            OpenAiChatOptions.Builder optionsBuilder = OpenAiChatOptions.builder()
                .toolCallbacks(toolCallbacks.toArray(new ToolCallback[0]))
                .internalToolExecutionEnabled(false);
            applyModelParams(optionsBuilder, options);
            prompt = new Prompt(messagesWithFormattedSystem, optionsBuilder.build());
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

        return new LlmResponse(content, toolCalls, extractUsage(response));
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
