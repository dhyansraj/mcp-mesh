package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.google.genai.GoogleGenAiChatOptions;

import java.util.*;

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

    @Override
    public String getVendor() {
        return "gemini";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"google"};
    }

    /**
     * Vendor aliases accepted specifically for {@code model_params.model} override
     * resolution. Superset of {@link #getAliases()}: mesh delegation routes both
     * Google AI Studio ({@code gemini/...}) and Vertex AI ({@code vertex_ai/...})
     * model strings through this single {@code GeminiHandler}, so a
     * {@code vertex_ai/}-qualified override is same-provider and must be accepted
     * on the google-genai options builder. Kept separate from the public
     * {@link #getAliases()} (which other surfaces assert returns exactly
     * {@code ["google"]}) so widening override-matching doesn't change that
     * contract. A genuinely cross-vendor override (e.g. {@code openai/...}) is
     * still rejected by {@link LlmProviderHandler#resolveModelOverride}.
     */
    private static final String[] MODEL_OVERRIDE_ALIASES = {"google", "vertex_ai", "vertex"};

    /** Gemini uses a shorter previous-turn prefix than the Anthropic/OpenAI default. */
    @Override
    public String previousResponsePrefix() {
        return "[Previous Response]\n";
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

        log.debug("GeminiHandler: Processing {} messages", messages.size());

        List<Message> springMessages = convertMessages(messages);
        // Plain-text generation: always build a vendor-correct Gemini options object
        // so the effective model (declared model, or a vendor-matched per-call
        // override) is set on the request — without it the request falls through to
        // Spring AI's default Gemini model. Consumer-supplied model_params
        // (max_tokens→maxOutputTokens/temperature/top_p) are applied here too.
        ChatOptions paramOptions = buildModelParamOptions(options).build();
        Prompt prompt = new Prompt(springMessages, paramOptions);
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

        // Effective output mode: honor a consumer-supplied output_mode override
        // (model_params.output_mode → options), else per-vendor auto-selection
        // (HINT for any schema). Gemini Java has no native structured-output path
        // (responseSchema + tools is rejected by the API), so STRICT is not
        // supportable here — fall back to HINT with a warning rather than fail.
        String requestedMode = determineOutputMode(outputSchema, LlmProviderHandler.outputModeOverride(options));
        String outputMode = requestedMode;
        if (OUTPUT_MODE_STRICT.equals(requestedMode)) {
            log.warn("GeminiHandler: output_mode='strict' requested but Gemini Java cannot enforce "
                + "native structured output alongside tools; falling back to HINT (prompt-based).");
            outputMode = OUTPUT_MODE_HINT;
        }

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

        // Format system prompt with the effective mode. TEXT mode suppresses the
        // schema so no JSON instructions are injected.
        OutputSchema promptSchema = OUTPUT_MODE_TEXT.equals(outputMode) ? null : outputSchema;
        String formattedSystemPrompt = formatSystemPromptViaCore(systemPrompt, tools, promptSchema, outputMode);

        if (executeTools) {
            // Auto-execution mode: Use ChatClient which handles tool execution automatically
            return generateWithToolsAutoExecute(model, springMessages, tools, toolExecutor, formattedSystemPrompt, outputSchema, options);
        } else {
            // No-execution mode: raw model.call() returns tool_calls without executing them
            return generateWithToolsNoExecute(model, springMessages, tools, formattedSystemPrompt, outputSchema, options);
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

        // Add tools if present
        if (!toolCallbacks.isEmpty()) {
            requestSpec.tools(toolCallbacks.toArray(new ToolCallback[0]));
        }

        // Don't use applyResponseFormat - Spring AI has issues with Gemini responseSchema
        // Structured output is handled via prompt-based hints in formatSystemPrompt()

        // Always attach a Gemini options object so the effective model (declared
        // model or a vendor-matched per-call override) is set on EVERY request,
        // plus any consumer-supplied model_params (max_tokens/temperature/top_p).
        requestSpec.options(buildModelParamOptions(options));

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
     * <p>Calls the raw {@link ChatModel#call(Prompt)} which, in Spring AI GA,
     * returns the model's {@code tool_calls} WITHOUT auto-execution — tool
     * execution now lives in a ChatClient-level advisor that is deliberately
     * absent on this raw path. Tool callbacks are attached to the options only
     * to advertise the tool schemas to the model. This is used for mesh
     * delegation where the consumer (not provider) executes tools.
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

        // Build Gemini chat options. Tools are attached to advertise their schema;
        // the raw model.call() below does not execute them in Spring AI GA.
        // Don't use responseSchema - Spring AI has issues with Gemini responseSchema
        // Structured output is handled via prompt-based hints in formatSystemPrompt()
        log.debug("Using prompt-based JSON hints for structured output (not responseSchema)");

        ChatOptions chatOptions = buildToolNoExecuteOptions(model, toolCallbacks, options);

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

    /**
     * Build {@link GoogleGenAiChatOptions} for the no-tool-execution path.
     *
     * <p>Spring AI GA consolidated Google support onto the single google-genai SDK
     * ({@link org.springframework.ai.google.genai.GoogleGenAiChatModel}); the Vertex
     * backend is reached through the same SDK via project/location backend config
     * ({@code spring.ai.google.genai.*}), so a single options type serves both
     * Google AI Studio and Vertex-backed routing. Tools are attached to advertise
     * their schema only — the raw {@code model.call()} does not execute them.
     *
     * <p>Package-private for testability.
     */
    ChatOptions buildToolNoExecuteOptions(ChatModel chatModel, List<ToolCallback> toolCallbacks) {
        return buildToolNoExecuteOptions(chatModel, toolCallbacks, null);
    }

    /**
     * Build {@link GoogleGenAiChatOptions} for the no-tool-execution path,
     * applying any consumer-supplied {@code model_params}
     * (max_tokens→maxOutputTokens, temperature, top_p, vendor-matched model).
     */
    ChatOptions buildToolNoExecuteOptions(ChatModel chatModel, List<ToolCallback> toolCallbacks,
                                          Map<String, Object> options) {
        GoogleGenAiChatOptions.Builder builder = GoogleGenAiChatOptions.builder()
            .toolCallbacks(toolCallbacks);
        applyGoogleGenAiModelParams(builder, options);
        return builder.build();
    }

    /**
     * Build a {@link GoogleGenAiChatOptions} builder carrying the effective model
     * (declared model or a vendor-matched per-call override) and any
     * consumer-supplied {@code model_params} (no tool callbacks) for the
     * auto-execute (ChatClient) path, where tools are attached via the request
     * spec rather than the options object.
     *
     * <p>Returns a builder so it can be passed directly to the GA ChatClient
     * {@code .options(ChatOptions.Builder)} overload, or {@code .build()}ed for
     * the raw {@code Prompt} path. The effective model is set on EVERY request —
     * without it the request falls through to Spring AI's default Gemini model.
     */
    private GoogleGenAiChatOptions.Builder buildModelParamOptions(Map<String, Object> options) {
        GoogleGenAiChatOptions.Builder builder = GoogleGenAiChatOptions.builder();
        applyGoogleGenAiModelParams(builder, options);
        return builder;
    }

    /**
     * Apply {@code model_params} to a Google AI Studio (GenAI) options builder.
     * Gemini maps {@code max_tokens} → {@code maxOutputTokens}. The {@code model}
     * override is honored only when its declared vendor matches
     * {@code gemini}/{@code google}.
     */
    private void applyGoogleGenAiModelParams(GoogleGenAiChatOptions.Builder builder, Map<String, Object> options) {
        Integer maxTokens = LlmProviderHandler.maxTokensOption(options);
        if (maxTokens != null) {
            builder.maxOutputTokens(maxTokens);
        }
        Double temperature = LlmProviderHandler.temperatureOption(options);
        if (temperature != null) {
            builder.temperature(temperature);
        }
        Double topP = LlmProviderHandler.topPOption(options);
        if (topP != null) {
            builder.topP(topP);
        }
        // Set the effective model on EVERY request: a vendor-matched per-call
        // override wins, else the provider's declared model. Without this the
        // request falls through to Spring AI's default Gemini model.
        String eff = LlmProviderHandler.effectiveModel(options, getVendor(), MODEL_OVERRIDE_ALIASES);
        if (eff != null) {
            builder.model(eff);
            log.debug("GeminiHandler: applied model '{}'", eff);
        }
    }

    /**
     * Apply Gemini-specific uppercase type conversion to a tool's input schema
     * before it is serialized and attached to the Spring AI tool callback.
     */
    @Override
    public Map<String, Object> transformToolInputSchema(Map<String, Object> schema) {
        return convertSchemaTypesToUpperCase(schema);
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
