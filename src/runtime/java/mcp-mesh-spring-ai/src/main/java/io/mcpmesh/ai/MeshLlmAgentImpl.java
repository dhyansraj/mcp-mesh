package io.mcpmesh.ai;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.Selector;
import io.mcpmesh.ai.handlers.LlmProviderHandler;
import io.mcpmesh.ai.handlers.LlmProviderHandler.OutputSchema;
import io.mcpmesh.ai.handlers.LlmProviderHandler.ToolDefinition;
import io.mcpmesh.ai.handlers.LlmProviderHandlerRegistry;
import io.mcpmesh.types.MeshLlmAgent;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * Implementation of MeshLlmAgent that supports both direct and mesh delegation modes.
 *
 * <p>Direct mode: Uses Spring AI to call LLM providers directly (requires API keys).
 * <p>Mesh delegation mode: Routes calls to LLM provider agents via the mesh.
 *
 * <p>Features:
 * <ul>
 *   <li>Agentic loop with tool calling</li>
 *   <li>Structured output parsing (JSON to Java records)</li>
 *   <li>System prompt support</li>
 *   <li>Provider availability tracking</li>
 * </ul>
 *
 * @see MeshLlm
 * @see MeshLlmAgent
 */
public class MeshLlmAgentImpl implements MeshLlmAgent {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmAgentImpl.class);
    private static final MediaType JSON_MEDIA_TYPE = MediaType.get("application/json; charset=utf-8");

    private final ObjectMapper objectMapper;
    private final OkHttpClient httpClient;

    // Configuration
    private final String functionId;
    private final String directProvider;          // For direct mode (e.g., "claude")
    private final Selector providerSelector;      // For mesh delegation mode
    private final int maxIterations;
    private final String systemPrompt;
    private final int maxTokens;
    private final double temperature;

    // Runtime state
    private volatile String providerEndpoint;     // Resolved mesh provider endpoint
    private volatile String providerFunctionName; // Usually "llm_generate"
    private volatile boolean available;

    // Spring AI provider for direct mode (optional)
    private final SpringAiLlmProvider springAiProvider;

    // Available tools for agentic loop
    private final List<ToolInfo> availableTools = new ArrayList<>();

    // Tool executor for agentic loop
    private ToolExecutor toolExecutor;

    // Last generation metadata (for builder API)
    private volatile GenerationMeta lastMeta;

    /**
     * Create an LLM agent for direct mode (using Spring AI).
     *
     * @param functionId      Unique identifier for this agent
     * @param llmProvider     Spring AI LLM provider
     * @param provider        Provider name (e.g., "claude", "openai")
     * @param systemPrompt    System prompt
     * @param maxIterations   Max agentic loop iterations
     * @param maxTokens       Max tokens
     * @param temperature     Temperature
     * @param objectMapper    Jackson ObjectMapper
     */
    public MeshLlmAgentImpl(
            String functionId,
            SpringAiLlmProvider llmProvider,
            String provider,
            String systemPrompt,
            int maxIterations,
            int maxTokens,
            double temperature,
            ObjectMapper objectMapper) {
        this.functionId = functionId;
        this.springAiProvider = llmProvider;
        this.directProvider = provider;
        this.providerSelector = null;
        this.systemPrompt = systemPrompt;
        this.maxIterations = maxIterations;
        this.maxTokens = maxTokens;
        this.temperature = temperature;
        this.objectMapper = objectMapper;
        this.httpClient = createHttpClient();
        this.available = llmProvider != null && llmProvider.isProviderAvailable(provider);
    }

    /**
     * Create an LLM agent for mesh delegation mode.
     *
     * @param functionId       Unique identifier for this agent
     * @param providerSelector Selector for finding LLM provider in mesh
     * @param systemPrompt     System prompt
     * @param maxIterations    Max agentic loop iterations
     * @param maxTokens        Max tokens
     * @param temperature      Temperature
     * @param objectMapper     Jackson ObjectMapper
     */
    public MeshLlmAgentImpl(
            String functionId,
            Selector providerSelector,
            String systemPrompt,
            int maxIterations,
            int maxTokens,
            double temperature,
            ObjectMapper objectMapper) {
        this.functionId = functionId;
        this.springAiProvider = null;
        this.directProvider = null;
        this.providerSelector = providerSelector;
        this.systemPrompt = systemPrompt;
        this.maxIterations = maxIterations;
        this.maxTokens = maxTokens;
        this.temperature = temperature;
        this.objectMapper = objectMapper;
        this.httpClient = createHttpClient();
        this.available = false;  // Will be set when provider is discovered
    }

    /**
     * Legacy constructor for backward compatibility.
     */
    public MeshLlmAgentImpl(String functionId, SpringAiLlmProvider llmProvider,
                            String provider, String systemPrompt, int maxIterations) {
        this(functionId, llmProvider, provider, systemPrompt, maxIterations, 4096, 0.7, MeshObjectMappers.create());
    }

    private OkHttpClient createHttpClient() {
        return new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)  // LLM calls can be slow
            .writeTimeout(60, TimeUnit.SECONDS)
            .build();
    }

    /**
     * Update the mesh provider endpoint when provider becomes available.
     *
     * @param endpoint     The provider's HTTP endpoint
     * @param functionName The tool function name (usually "llm_generate")
     */
    public void setProviderEndpoint(String endpoint, String functionName) {
        this.providerEndpoint = endpoint;
        this.providerFunctionName = functionName;
        this.available = endpoint != null && !endpoint.isEmpty();
        log.info("LLM provider endpoint updated: {} -> {}", functionName, endpoint);
    }

    /**
     * Set the tool executor for agentic loop.
     */
    public void setToolExecutor(ToolExecutor executor) {
        this.toolExecutor = executor;
    }

    /**
     * Update the list of available tools for agentic loops.
     */
    public void updateTools(List<ToolInfo> tools) {
        this.availableTools.clear();
        if (tools != null) {
            this.availableTools.addAll(tools);
        }
        log.debug("Updated available tools: {} tools", availableTools.size());
    }

    /**
     * Set availability status.
     */
    public void setAvailable(boolean available) {
        this.available = available;
    }

    // =========================================================================
    // Fluent Builder Entry Point
    // =========================================================================

    @Override
    public GenerateBuilder request() {
        return new GenerateBuilderImpl();
    }

    // =========================================================================
    // Simple API (Backward Compatible - now delegates to builder)
    // =========================================================================

    @Override
    public String generate(String prompt) {
        return request().user(prompt).generate();
    }

    @Override
    public <T> T generate(String prompt, Class<T> responseType) {
        return request().user(prompt).generate(responseType);
    }

    @Override
    public CompletableFuture<String> generateAsync(String prompt) {
        return request().user(prompt).generateAsync();
    }

    @Override
    public <T> CompletableFuture<T> generateAsync(String prompt, Class<T> responseType) {
        return request().user(prompt).generateAsync(responseType);
    }

    /**
     * Internal generation with full messages list.
     */
    @SuppressWarnings("unchecked")
    private <T> T generateInternal(List<Map<String, Object>> messagesList,
                                   Integer runtimeMaxTokens,
                                   Double runtimeTemperature,
                                   Class<T> responseType) {
        if (!available) {
            throw new IllegalStateException("LLM agent not available: " + functionId);
        }

        long startTime = System.currentTimeMillis();
        int iterations = 0;

        try {
            // Run agentic loop with the provided messages
            int effectiveMaxTokens = runtimeMaxTokens != null ? runtimeMaxTokens : this.maxTokens;
            double effectiveTemperature = runtimeTemperature != null ? runtimeTemperature : this.temperature;

            // Generate output schema for structured output (non-String types)
            OutputSchema outputSchema = null;
            if (responseType != String.class && responseType != Void.class) {
                Map<String, Object> schema = generateJsonSchema(responseType);
                outputSchema = OutputSchema.fromSchema(responseType.getSimpleName(), schema);
                log.debug("Generated output schema for {}: simple={}", responseType.getSimpleName(), outputSchema.simple());
            }

            String response = runAgenticLoop(messagesList, effectiveMaxTokens, effectiveTemperature, outputSchema);
            iterations = 1; // TODO: Track actual iterations from agentic loop

            // Store metadata
            long latencyMs = System.currentTimeMillis() - startTime;
            this.lastMeta = new GenerationMeta(0, 0, 0, latencyMs, iterations, getProvider());

            // Parse response to target type
            if (responseType == String.class) {
                return (T) response;
            } else {
                return parseStructuredOutput(response, responseType);
            }
        } catch (Exception e) {
            log.error("LLM generation failed: {}", e.getMessage(), e);
            throw new RuntimeException("LLM generation failed: " + e.getMessage(), e);
        }
    }

    @Override
    public List<ToolInfo> getAvailableTools() {
        return new ArrayList<>(availableTools);
    }

    @Override
    public boolean isAvailable() {
        return available;
    }

    @Override
    public String getProvider() {
        if (directProvider != null) {
            return "direct:" + directProvider;
        } else if (providerEndpoint != null) {
            return "mesh:" + providerEndpoint;
        } else {
            return "unavailable";
        }
    }

    /**
     * Build the messages array for the LLM request.
     */
    private List<Map<String, Object>> buildMessages(String userPrompt) {
        List<Map<String, Object>> messages = new ArrayList<>();

        // Add system prompt if configured
        String resolvedSystemPrompt = resolveSystemPrompt(systemPrompt);
        if (resolvedSystemPrompt != null && !resolvedSystemPrompt.isEmpty()) {
            messages.add(Map.of("role", "system", "content", resolvedSystemPrompt));
        }

        // Add user prompt
        messages.add(Map.of("role", "user", "content", userPrompt));

        return messages;
    }

    /**
     * Resolve system prompt - could be literal string or template path.
     */
    private String resolveSystemPrompt(String prompt) {
        if (prompt == null || prompt.isEmpty()) {
            return null;
        }

        // TODO: Implement Freemarker template loading
        // For now, treat as literal string unless it starts with classpath: or file:
        if (prompt.startsWith("classpath:") || prompt.startsWith("file:")) {
            log.warn("Template loading not yet implemented: {}", prompt);
            return "You are a helpful assistant.";
        }
        return prompt;
    }

    /**
     * Run the agentic loop - call LLM, execute tool calls, repeat.
     */
    private String runAgenticLoop(List<Map<String, Object>> messages,
                                  int effectiveMaxTokens,
                                  double effectiveTemperature,
                                  OutputSchema outputSchema) throws Exception {
        List<Map<String, Object>> conversationMessages = new ArrayList<>(messages);
        int iterations = 0;

        while (iterations < maxIterations) {
            iterations++;
            log.debug("Agentic loop iteration {}/{}", iterations, maxIterations);

            // Call LLM with runtime parameters and output schema
            Map<String, Object> response = callLlm(conversationMessages, effectiveMaxTokens, effectiveTemperature, outputSchema);

            String content = (String) response.get("content");
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) response.get("tool_calls");

            // If no tool calls, we're done
            if (toolCalls == null || toolCalls.isEmpty()) {
                log.debug("LLM returned final response (no tool calls)");
                return content != null ? content : "";
            }

            // Execute tool calls
            log.debug("LLM requested {} tool call(s)", toolCalls.size());

            // Add assistant message with tool calls
            Map<String, Object> assistantMessage = new LinkedHashMap<>();
            assistantMessage.put("role", "assistant");
            assistantMessage.put("content", content != null ? content : "");
            assistantMessage.put("tool_calls", toolCalls);
            conversationMessages.add(assistantMessage);

            // Execute each tool call and add results
            for (Map<String, Object> toolCall : toolCalls) {
                String toolCallId = (String) toolCall.get("id");
                @SuppressWarnings("unchecked")
                Map<String, Object> function = (Map<String, Object>) toolCall.get("function");
                String toolName = (String) function.get("name");
                String argsJson = (String) function.get("arguments");

                log.debug("Executing tool: {} with args: {}", toolName, argsJson);

                try {
                    String toolResult = executeToolCall(toolName, argsJson);

                    // Add tool result message
                    conversationMessages.add(Map.of(
                        "role", "tool",
                        "tool_call_id", toolCallId,
                        "content", toolResult
                    ));
                } catch (Exception e) {
                    log.error("Tool call failed: {} - {}", toolName, e.getMessage());
                    conversationMessages.add(Map.of(
                        "role", "tool",
                        "tool_call_id", toolCallId,
                        "content", "Error: " + e.getMessage()
                    ));
                }
            }
        }

        log.warn("Agentic loop reached max iterations ({})", maxIterations);
        throw new RuntimeException("Agentic loop exceeded max iterations");
    }

    /**
     * Call the LLM (either direct or via mesh delegation).
     */
    private Map<String, Object> callLlm(List<Map<String, Object>> messages,
                                        int effectiveMaxTokens,
                                        double effectiveTemperature,
                                        OutputSchema outputSchema) throws Exception {
        if (directProvider != null && springAiProvider != null) {
            return callLlmDirect(messages, outputSchema);
        } else {
            return callLlmViaMesh(messages, effectiveMaxTokens, effectiveTemperature, outputSchema);
        }
    }

    /**
     * Call LLM directly using Spring AI with native tool support.
     *
     * <p>Uses Spring AI 2.0 ChatClient with FunctionToolCallback for
     * native tool calling. Spring AI handles the agentic loop internally.
     *
     * @param messages     Conversation messages
     * @param outputSchema Output schema for structured output (null for text)
     */
    private Map<String, Object> callLlmDirect(List<Map<String, Object>> messages, OutputSchema outputSchema) {
        // Convert our ToolInfo to handler's ToolDefinition
        List<ToolDefinition> toolDefs = new ArrayList<>();
        for (ToolInfo tool : availableTools) {
            toolDefs.add(new ToolDefinition(
                tool.name(),
                tool.description(),
                tool.inputSchema()
            ));
        }

        // Create tool executor callback that delegates to our tool executor
        LlmProviderHandler.ToolExecutorCallback executorCallback = null;
        if (toolExecutor != null && !availableTools.isEmpty()) {
            executorCallback = (toolName, argsJson) -> {
                ToolInfo tool = availableTools.stream()
                    .filter(t -> t.name().equals(toolName))
                    .findFirst()
                    .orElseThrow(() -> new RuntimeException("Tool not found: " + toolName));

                @SuppressWarnings("unchecked")
                Map<String, Object> args = argsJson != null && !argsJson.isEmpty() ?
                    objectMapper.readValue(argsJson, Map.class) : Map.of();

                Object result = toolExecutor.execute(toolName, tool.agentId(), args);
                return result != null ? objectMapper.writeValueAsString(result) : "";
            };
        }

        log.debug("Calling LLM directly with {} tools, outputSchema={}",
            toolDefs.size(), outputSchema != null ? outputSchema.name() : "none");

        // Get vendor-specific handler
        LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler(directProvider);

        // Get the ChatModel
        var model = springAiProvider.getModelForProvider(directProvider);

        // Use handler's generateWithTools with output schema
        LlmProviderHandler.LlmResponse llmResponse = handler.generateWithTools(
            model,
            messages,
            toolDefs,
            executorCallback,
            outputSchema,
            Map.of()
        );

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("content", llmResponse.content());

        // Convert tool calls to our format
        List<Map<String, Object>> toolCallMaps = new ArrayList<>();
        if (llmResponse.hasToolCalls()) {
            for (var tc : llmResponse.toolCalls()) {
                Map<String, Object> tcMap = new LinkedHashMap<>();
                tcMap.put("id", tc.id());
                tcMap.put("function", Map.of(
                    "name", tc.name(),
                    "arguments", tc.arguments()
                ));
                toolCallMaps.add(tcMap);
            }
        }
        result.put("tool_calls", toolCallMaps);

        return result;
    }

    /**
     * Call LLM via mesh delegation.
     *
     * @param messages            Conversation messages
     * @param effectiveMaxTokens  Max tokens
     * @param effectiveTemperature Temperature
     * @param outputSchema        Output schema for structured output (null for text)
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> callLlmViaMesh(List<Map<String, Object>> messages,
                                               int effectiveMaxTokens,
                                               double effectiveTemperature,
                                               OutputSchema outputSchema) throws Exception {
        if (providerEndpoint == null) {
            throw new IllegalStateException("No mesh LLM provider available");
        }

        // Build request
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("messages", messages);

        // Add tools if available (for agentic loop)
        if (!availableTools.isEmpty()) {
            request.put("tools", formatToolsForLlm());
        }

        // Add output schema for structured output
        if (outputSchema != null) {
            Map<String, Object> outputSchemaData = new LinkedHashMap<>();
            outputSchemaData.put("name", outputSchema.name());
            outputSchemaData.put("schema", outputSchema.schema());
            outputSchemaData.put("simple", outputSchema.simple());
            request.put("output_schema", outputSchemaData);
            log.debug("Including output_schema for {} in mesh request", outputSchema.name());
        }

        request.put("max_tokens", effectiveMaxTokens);
        request.put("temperature", effectiveTemperature);

        // Call mesh provider
        String url = providerEndpoint.endsWith("/") ?
            providerEndpoint + "mcp" : providerEndpoint + "/mcp";

        Map<String, Object> mcpRequest = Map.of(
            "jsonrpc", "2.0",
            "id", System.currentTimeMillis(),
            "method", "tools/call",
            "params", Map.of(
                "name", providerFunctionName != null ? providerFunctionName : "llm_generate",
                "arguments", request
            )
        );

        String requestBody = objectMapper.writeValueAsString(mcpRequest);
        log.debug("Calling mesh LLM provider at {}", url);

        Request httpRequest = new Request.Builder()
            .url(url)
            .post(RequestBody.create(requestBody, JSON_MEDIA_TYPE))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream")
            .build();

        try (Response response = httpClient.newCall(httpRequest).execute()) {
            if (!response.isSuccessful()) {
                throw new RuntimeException("LLM provider returned HTTP " + response.code());
            }

            ResponseBody body = response.body();
            if (body == null) {
                throw new RuntimeException("Empty response from LLM provider");
            }

            String responseBody = body.string();
            log.debug("LLM provider response length: {} chars", responseBody.length());

            // Parse response
            return parseLlmResponse(responseBody);
        }
    }

    /**
     * Parse LLM response from MCP format.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> parseLlmResponse(String responseBody) throws Exception {
        // Handle SSE format
        String jsonContent = responseBody;
        if (responseBody.startsWith("event:") || responseBody.contains("\ndata: ")) {
            jsonContent = extractJsonFromSse(responseBody);
        }

        JsonNode responseNode = objectMapper.readTree(jsonContent);

        if (responseNode.has("error")) {
            String errorMsg = responseNode.get("error").has("message") ?
                responseNode.get("error").get("message").asText() : "Unknown error";
            throw new RuntimeException("LLM provider error: " + errorMsg);
        }

        if (!responseNode.has("result")) {
            throw new RuntimeException("Invalid response: missing result");
        }

        JsonNode result = responseNode.get("result");

        // Extract content from MCP format
        String textContent = null;
        if (result.has("content") && result.get("content").isArray()) {
            JsonNode content = result.get("content");
            if (content.size() > 0 && content.get(0).has("text")) {
                textContent = content.get(0).get("text").asText();
            }
        }

        // Parse the text content as JSON (it contains {content, model, tool_calls})
        if (textContent != null) {
            try {
                return objectMapper.readValue(textContent, Map.class);
            } catch (JacksonException e) {
                // Not JSON, return as plain text
                Map<String, Object> plainResult = new LinkedHashMap<>();
                plainResult.put("content", textContent);
                plainResult.put("tool_calls", List.of());
                return plainResult;
            }
        }

        throw new RuntimeException("Could not extract content from LLM response");
    }

    /**
     * Extract JSON from SSE format.
     */
    private String extractJsonFromSse(String sseContent) {
        StringBuilder jsonBuilder = new StringBuilder();
        for (String line : sseContent.split("\n")) {
            if (line.startsWith("data: ")) {
                jsonBuilder.append(line.substring(6));
            } else if (line.startsWith("data:")) {
                jsonBuilder.append(line.substring(5));
            }
        }
        String json = jsonBuilder.toString().trim();
        return json.isEmpty() ? sseContent : json;
    }

    /**
     * Format available tools for LLM (OpenAI function calling format).
     */
    private List<Map<String, Object>> formatToolsForLlm() {
        List<Map<String, Object>> tools = new ArrayList<>();

        for (ToolInfo tool : availableTools) {
            Map<String, Object> toolDef = new LinkedHashMap<>();
            toolDef.put("type", "function");

            Map<String, Object> function = new LinkedHashMap<>();
            function.put("name", tool.name());
            function.put("description", tool.description());
            function.put("parameters", tool.inputSchema() != null ? tool.inputSchema() : Map.of("type", "object"));

            toolDef.put("function", function);
            tools.add(toolDef);
        }

        return tools;
    }

    /**
     * Execute a tool call during the agentic loop.
     */
    @SuppressWarnings("unchecked")
    private String executeToolCall(String toolName, String argsJson) throws Exception {
        // Find the tool
        ToolInfo tool = availableTools.stream()
            .filter(t -> t.name().equals(toolName))
            .findFirst()
            .orElseThrow(() -> new RuntimeException("Tool not found: " + toolName));

        // Use tool executor if available
        if (toolExecutor != null) {
            Map<String, Object> args = argsJson != null && !argsJson.isEmpty() ?
                objectMapper.readValue(argsJson, Map.class) : Map.of();
            Object result = toolExecutor.execute(toolName, tool.agentId(), args);
            return result != null ? objectMapper.writeValueAsString(result) : "";
        }

        // Fallback: not implemented
        log.warn("Tool execution not available: {} (would call agent {})", toolName, tool.agentId());
        return "{\"error\": \"Tool execution not configured\"}";
    }

    /**
     * Parse structured output from LLM response.
     */
    private <T> T parseStructuredOutput(String response, Class<T> responseType) {
        try {
            return objectMapper.readValue(response, responseType);
        } catch (JacksonException e) {
            log.warn("Failed to parse structured output directly, trying to extract JSON");

            // Try to extract JSON from the response
            String json = extractJsonFromText(response);
            if (json != null) {
                try {
                    return objectMapper.readValue(json, responseType);
                } catch (JacksonException e2) {
                    throw new RuntimeException("Failed to parse LLM response as " + responseType.getSimpleName(), e2);
                }
            }

            throw new RuntimeException("Failed to parse LLM response as " + responseType.getSimpleName(), e);
        }
    }

    /**
     * Try to extract JSON from text that may contain other content.
     */
    private String extractJsonFromText(String text) {
        // Look for JSON object
        int start = text.indexOf('{');
        int end = text.lastIndexOf('}');
        if (start >= 0 && end > start) {
            return text.substring(start, end + 1);
        }
        return null;
    }

    // =========================================================================
    // JSON Schema Generation
    // =========================================================================

    /**
     * Generate JSON schema from a Java class.
     *
     * <p>Supports records, POJOs, and common types like String, primitives,
     * List, Map, etc. Used for structured output in LLM calls.
     */
    private Map<String, Object> generateJsonSchema(Class<?> clazz) {
        return generateJsonSchemaInternal(clazz, new HashSet<>());
    }

    /**
     * Internal schema generation with cycle detection.
     */
    private Map<String, Object> generateJsonSchemaInternal(Class<?> clazz, Set<Class<?>> visited) {
        Map<String, Object> schema = new LinkedHashMap<>();

        // Handle primitives and wrappers
        if (clazz == String.class || clazz == CharSequence.class) {
            schema.put("type", "string");
            return schema;
        }
        if (clazz == Integer.class || clazz == int.class ||
            clazz == Long.class || clazz == long.class ||
            clazz == Short.class || clazz == short.class ||
            clazz == Byte.class || clazz == byte.class) {
            schema.put("type", "integer");
            return schema;
        }
        if (clazz == Double.class || clazz == double.class ||
            clazz == Float.class || clazz == float.class ||
            clazz == Number.class) {
            schema.put("type", "number");
            return schema;
        }
        if (clazz == Boolean.class || clazz == boolean.class) {
            schema.put("type", "boolean");
            return schema;
        }

        // Handle arrays
        if (clazz.isArray()) {
            schema.put("type", "array");
            schema.put("items", generateJsonSchemaInternal(clazz.getComponentType(), visited));
            return schema;
        }

        // Handle enums
        if (clazz.isEnum()) {
            schema.put("type", "string");
            Object[] constants = clazz.getEnumConstants();
            List<String> values = new ArrayList<>();
            for (Object c : constants) {
                values.add(c.toString());
            }
            schema.put("enum", values);
            return schema;
        }

        // Handle Map
        if (Map.class.isAssignableFrom(clazz)) {
            schema.put("type", "object");
            schema.put("additionalProperties", true);
            return schema;
        }

        // Handle List/Collection (generic handling would need type info)
        if (List.class.isAssignableFrom(clazz) || Collection.class.isAssignableFrom(clazz)) {
            schema.put("type", "array");
            schema.put("items", Map.of("type", "object")); // Default to object items
            return schema;
        }

        // Cycle detection for complex types
        if (visited.contains(clazz)) {
            schema.put("type", "object");
            schema.put("description", "Recursive reference to " + clazz.getSimpleName());
            return schema;
        }
        visited.add(clazz);

        // Handle records and POJOs
        schema.put("type", "object");
        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        // For records, use record components
        if (clazz.isRecord()) {
            for (var component : clazz.getRecordComponents()) {
                String name = component.getName();
                Class<?> type = component.getType();
                Type genericType = component.getGenericType();

                Map<String, Object> fieldSchema = generateFieldSchema(type, genericType, visited);
                properties.put(name, fieldSchema);
                required.add(name); // All record components are required
            }
        } else {
            // For POJOs, use declared fields
            for (Field field : clazz.getDeclaredFields()) {
                // Skip static fields
                if (Modifier.isStatic(field.getModifiers())) {
                    continue;
                }
                // Skip transient fields
                if (Modifier.isTransient(field.getModifiers())) {
                    continue;
                }

                String name = field.getName();
                Class<?> type = field.getType();
                Type genericType = field.getGenericType();

                Map<String, Object> fieldSchema = generateFieldSchema(type, genericType, visited);
                properties.put(name, fieldSchema);

                // Consider primitive fields and non-null annotated fields as required
                if (type.isPrimitive()) {
                    required.add(name);
                }
            }
        }

        if (!properties.isEmpty()) {
            schema.put("properties", properties);
        }
        if (!required.isEmpty()) {
            schema.put("required", required);
        }

        visited.remove(clazz);
        return schema;
    }

    /**
     * Generate schema for a field, handling generic types.
     */
    private Map<String, Object> generateFieldSchema(Class<?> type, Type genericType, Set<Class<?>> visited) {
        // Handle List<T>
        if (List.class.isAssignableFrom(type) && genericType instanceof ParameterizedType) {
            ParameterizedType paramType = (ParameterizedType) genericType;
            Type[] typeArgs = paramType.getActualTypeArguments();
            if (typeArgs.length > 0) {
                Map<String, Object> schema = new LinkedHashMap<>();
                schema.put("type", "array");
                if (typeArgs[0] instanceof Class) {
                    schema.put("items", generateJsonSchemaInternal((Class<?>) typeArgs[0], visited));
                } else {
                    schema.put("items", Map.of("type", "object"));
                }
                return schema;
            }
        }

        // Handle Map<K, V>
        if (Map.class.isAssignableFrom(type) && genericType instanceof ParameterizedType) {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("additionalProperties", true);
            return schema;
        }

        // Handle Optional<T>
        if (Optional.class.isAssignableFrom(type) && genericType instanceof ParameterizedType) {
            ParameterizedType paramType = (ParameterizedType) genericType;
            Type[] typeArgs = paramType.getActualTypeArguments();
            if (typeArgs.length > 0 && typeArgs[0] instanceof Class) {
                return generateJsonSchemaInternal((Class<?>) typeArgs[0], visited);
            }
        }

        return generateJsonSchemaInternal(type, visited);
    }

    // =========================================================================
    // GenerateBuilder Implementation
    // =========================================================================

    /**
     * Fluent builder for constructing LLM generation requests.
     */
    private class GenerateBuilderImpl implements GenerateBuilder {

        private final List<Message> messages = new ArrayList<>();
        private final Map<String, Object> runtimeContext = new LinkedHashMap<>();
        private ContextMode contextMode = ContextMode.APPEND;
        private Integer runtimeMaxTokens = null;
        private Double runtimeTemperature = null;
        private Double runtimeTopP = null;
        private List<String> stopSequences = null;
        private GenerationMeta meta = null;

        // --- Messages ---

        @Override
        public GenerateBuilder system(String content) {
            if (content != null && !content.isEmpty()) {
                messages.add(Message.system(content));
            }
            return this;
        }

        @Override
        public GenerateBuilder user(String content) {
            if (content != null && !content.isEmpty()) {
                messages.add(Message.user(content));
            }
            return this;
        }

        @Override
        public GenerateBuilder assistant(String content) {
            if (content != null && !content.isEmpty()) {
                messages.add(Message.assistant(content));
            }
            return this;
        }

        @Override
        public GenerateBuilder message(String role, String content) {
            if (role != null && content != null) {
                messages.add(new Message(role, content));
            }
            return this;
        }

        @Override
        public GenerateBuilder message(Message message) {
            if (message != null) {
                messages.add(message);
            }
            return this;
        }

        @Override
        public GenerateBuilder messages(List<Message> messageList) {
            if (messageList != null) {
                messages.addAll(messageList);
            }
            return this;
        }

        // --- Generation Options ---

        @Override
        public GenerateBuilder maxTokens(int tokens) {
            this.runtimeMaxTokens = tokens;
            return this;
        }

        @Override
        public GenerateBuilder temperature(double temperature) {
            this.runtimeTemperature = temperature;
            return this;
        }

        @Override
        public GenerateBuilder topP(double topP) {
            this.runtimeTopP = topP;
            return this;
        }

        @Override
        public GenerateBuilder stop(String... sequences) {
            this.stopSequences = sequences != null ? Arrays.asList(sequences) : null;
            return this;
        }

        // --- Template Context ---

        @Override
        public GenerateBuilder context(Map<String, Object> context) {
            if (context != null) {
                this.runtimeContext.putAll(context);
            }
            return this;
        }

        @Override
        public GenerateBuilder context(String key, Object value) {
            if (key != null) {
                this.runtimeContext.put(key, value);
            }
            return this;
        }

        @Override
        public GenerateBuilder contextMode(ContextMode mode) {
            this.contextMode = mode != null ? mode : ContextMode.APPEND;
            return this;
        }

        // --- Execute ---

        @Override
        public String generate() {
            return generateInternal(buildMessagesForRequest(),
                    runtimeMaxTokens, runtimeTemperature, String.class);
        }

        @Override
        public <T> T generate(Class<T> responseType) {
            return generateInternal(buildMessagesForRequest(),
                    runtimeMaxTokens, runtimeTemperature, responseType);
        }

        @Override
        public CompletableFuture<String> generateAsync() {
            return CompletableFuture.supplyAsync(this::generate);
        }

        @Override
        public <T> CompletableFuture<T> generateAsync(Class<T> responseType) {
            return CompletableFuture.supplyAsync(() -> generate(responseType));
        }

        @Override
        public GenerationMeta lastMeta() {
            return MeshLlmAgentImpl.this.lastMeta;
        }

        /**
         * Build the messages list for the LLM request.
         */
        private List<Map<String, Object>> buildMessagesForRequest() {
            List<Map<String, Object>> result = new ArrayList<>();

            // Add default system prompt if no system message was provided and we have one configured
            boolean hasSystemMessage = messages.stream()
                    .anyMatch(m -> "system".equals(m.role()));

            if (!hasSystemMessage && systemPrompt != null && !systemPrompt.isEmpty()) {
                String resolvedPrompt = resolveSystemPrompt(systemPrompt);
                if (resolvedPrompt != null && !resolvedPrompt.isEmpty()) {
                    result.add(Map.of("role", "system", "content", resolvedPrompt));
                }
            }

            // Add all messages from the builder
            for (Message msg : messages) {
                result.add(Map.of("role", msg.role(), "content", msg.content()));
            }

            return result;
        }
    }

    /**
     * Interface for executing tools during agentic loop.
     */
    public interface ToolExecutor {
        /**
         * Execute a tool call.
         *
         * @param toolName Tool function name
         * @param agentId  Agent ID that owns the tool
         * @param args     Tool arguments
         * @return Tool result
         */
        Object execute(String toolName, String agentId, Map<String, Object> args) throws Exception;
    }
}
