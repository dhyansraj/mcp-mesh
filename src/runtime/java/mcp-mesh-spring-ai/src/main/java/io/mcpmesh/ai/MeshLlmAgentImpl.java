package io.mcpmesh.ai;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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
        this(functionId, llmProvider, provider, systemPrompt, maxIterations, 4096, 0.7, new ObjectMapper());
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

            String response = runAgenticLoop(messagesList, effectiveMaxTokens, effectiveTemperature);
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
                                  double effectiveTemperature) throws Exception {
        List<Map<String, Object>> conversationMessages = new ArrayList<>(messages);
        int iterations = 0;

        while (iterations < maxIterations) {
            iterations++;
            log.debug("Agentic loop iteration {}/{}", iterations, maxIterations);

            // Call LLM with runtime parameters
            Map<String, Object> response = callLlm(conversationMessages, effectiveMaxTokens, effectiveTemperature);

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
                                        double effectiveTemperature) throws Exception {
        if (directProvider != null && springAiProvider != null) {
            return callLlmDirect(messages);
        } else {
            return callLlmViaMesh(messages, effectiveMaxTokens, effectiveTemperature);
        }
    }

    /**
     * Call LLM directly using Spring AI.
     */
    private Map<String, Object> callLlmDirect(List<Map<String, Object>> messages) {
        // Extract system and user prompts
        String systemPromptText = "";
        StringBuilder userPromptBuilder = new StringBuilder();

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");
            if ("system".equals(role)) {
                systemPromptText = content;
            } else if ("user".equals(role)) {
                if (userPromptBuilder.length() > 0) {
                    userPromptBuilder.append("\n");
                }
                userPromptBuilder.append(content);
            }
        }

        String response = springAiProvider.generate(directProvider, systemPromptText, userPromptBuilder.toString());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("content", response);
        result.put("tool_calls", List.of());  // Direct mode doesn't support tool calls yet
        return result;
    }

    /**
     * Call LLM via mesh delegation.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> callLlmViaMesh(List<Map<String, Object>> messages,
                                               int effectiveMaxTokens,
                                               double effectiveTemperature) throws Exception {
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
            } catch (JsonProcessingException e) {
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
        } catch (JsonProcessingException e) {
            log.warn("Failed to parse structured output directly, trying to extract JSON");

            // Try to extract JSON from the response
            String json = extractJsonFromText(response);
            if (json != null) {
                try {
                    return objectMapper.readValue(json, responseType);
                } catch (JsonProcessingException e2) {
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
