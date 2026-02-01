package io.mcpmesh.spring;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Proxy implementation for LLM agents using mesh delegation.
 *
 * <p>Routes LLM requests to remote LLM provider agents discovered via the mesh.
 * Supports agentic loops with tool calling.
 *
 * <h2>Fluent Builder API</h2>
 * <pre>{@code
 * // Simple prompt
 * llm.request().user("Hello").generate();
 *
 * // With message history from database
 * List<Message> history = Message.fromMaps(redis.getHistory(sessionId));
 * llm.request()
 *    .system("You are helpful")
 *    .messages(history)
 *    .user(newMessage)
 *    .maxTokens(1000)
 *    .generate();
 * }</pre>
 *
 * <h2>Prompt Templates</h2>
 * <p>Supports FreeMarker templates for system prompts:
 * <ul>
 *   <li>{@code file://path/to/template.ftl} - File system template</li>
 *   <li>{@code classpath:prompts/template.ftl} - Classpath template</li>
 *   <li>Inline text with ${variable} syntax</li>
 * </ul>
 *
 * @see PromptTemplateRenderer
 */
public class MeshLlmAgentProxy implements MeshLlmAgent {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmAgentProxy.class);
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private final String functionId;
    private final List<ToolInfo> availableTools = new CopyOnWriteArrayList<>();
    private final AtomicReference<ProviderEndpoint> providerRef = new AtomicReference<>();

    // Configuration from @MeshLlm annotation
    private volatile String systemPromptTemplate = "";
    private volatile String contextParamName = "ctx";
    private volatile int defaultMaxIterations = 1;
    private volatile int defaultMaxTokens = 4096;
    private volatile double defaultTemperature = 0.7;

    private McpHttpClient mcpClient;
    private MeshDependencyInjector dependencyInjector;
    private PromptTemplateRenderer templateRenderer;

    // Thread-local context for per-invocation template rendering (from MeshToolWrapper)
    private final ThreadLocal<Map<String, Object>> invocationContext = new ThreadLocal<>();

    /**
     * Endpoint info for the LLM provider.
     */
    public record ProviderEndpoint(String endpoint, String functionName, String provider) {
        public boolean isAvailable() {
            return endpoint != null && !endpoint.isBlank();
        }
    }

    public MeshLlmAgentProxy(String functionId) {
        this.functionId = functionId;
        this.templateRenderer = new PromptTemplateRenderer();
    }

    // =========================================================================
    // Configuration (called by MeshEventProcessor)
    // =========================================================================

    /**
     * Configure the proxy with dependencies.
     */
    public void configure(McpHttpClient mcpClient, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, int maxIterations) {
        configure(mcpClient, dependencyInjector, systemPrompt, "ctx", maxIterations);
    }

    /**
     * Configure the proxy with dependencies and context parameter name.
     */
    public void configure(McpHttpClient mcpClient, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations) {
        this.mcpClient = mcpClient;
        this.dependencyInjector = dependencyInjector;
        this.systemPromptTemplate = systemPrompt != null ? systemPrompt : "";
        this.contextParamName = contextParamName != null ? contextParamName : "ctx";
        this.defaultMaxIterations = maxIterations > 0 ? maxIterations : 1;
    }

    public String getContextParamName() {
        return contextParamName;
    }

    public void setInvocationContext(Map<String, Object> context) {
        invocationContext.set(context);
    }

    private void clearInvocationContext() {
        invocationContext.remove();
    }

    public void updateProvider(String endpoint, String functionName, String provider) {
        log.info("LLM provider updated for {}: {} at {}", functionId, provider, endpoint);
        providerRef.set(new ProviderEndpoint(endpoint, functionName, provider));
    }

    @SuppressWarnings("unchecked")
    void updateTools(List<MeshEvent.LlmToolInfo> tools) {
        availableTools.clear();
        for (MeshEvent.LlmToolInfo tool : tools) {
            // Parse inputSchema from JSON string to Map
            Map<String, Object> inputSchema = null;
            String schemaStr = tool.getInputSchema();
            if (schemaStr != null && !schemaStr.isEmpty()) {
                try {
                    inputSchema = objectMapper.readValue(schemaStr, Map.class);
                } catch (JsonProcessingException e) {
                    log.warn("Failed to parse input schema for tool {}: {}", tool.getFunctionName(), e.getMessage());
                }
            }

            availableTools.add(new ToolInfo(
                tool.getFunctionName(),
                tool.getDescription(),
                tool.getCapability(),
                tool.getAgentId(),
                inputSchema
            ));
        }
        log.debug("Updated {} tools for LLM agent {}", availableTools.size(), functionId);
    }

    void markUnavailable() {
        providerRef.set(null);
    }

    // =========================================================================
    // MeshLlmAgent Interface Implementation
    // =========================================================================

    @Override
    public GenerateBuilder request() {
        return new GenerateBuilderImpl();
    }

    @Override
    public List<ToolInfo> getAvailableTools() {
        return new ArrayList<>(availableTools);
    }

    @Override
    public boolean isAvailable() {
        ProviderEndpoint provider = providerRef.get();
        return provider != null && provider.isAvailable();
    }

    @Override
    public String getProvider() {
        ProviderEndpoint provider = providerRef.get();
        return provider != null ? provider.provider() : null;
    }

    // =========================================================================
    // GenerateBuilder Implementation
    // =========================================================================

    private class GenerateBuilderImpl implements GenerateBuilder {

        private final List<Message> messages = new ArrayList<>();
        private final Map<String, Object> runtimeContext = new LinkedHashMap<>();
        private ContextMode contextMode = ContextMode.APPEND;

        // Override options (null = use defaults)
        private Integer maxTokens = null;
        private Double temperature = null;
        private Double topP = null;
        private List<String> stopSequences = null;
        private int maxIterations = defaultMaxIterations;

        // Metadata from last call
        private GenerationMeta lastMeta = null;

        // --- Messages ---

        @Override
        public GenerateBuilder system(String content) {
            messages.add(Message.system(content));
            return this;
        }

        @Override
        public GenerateBuilder user(String content) {
            messages.add(Message.user(content));
            return this;
        }

        @Override
        public GenerateBuilder assistant(String content) {
            messages.add(Message.assistant(content));
            return this;
        }

        @Override
        public GenerateBuilder message(String role, String content) {
            messages.add(new Message(role, content));
            return this;
        }

        @Override
        public GenerateBuilder message(Message message) {
            messages.add(message);
            return this;
        }

        @Override
        public GenerateBuilder messages(List<Message> messageList) {
            if (messageList != null) {
                messages.addAll(messageList);
            }
            return this;
        }

        // --- Options ---

        @Override
        public GenerateBuilder maxTokens(int tokens) {
            this.maxTokens = tokens;
            return this;
        }

        @Override
        public GenerateBuilder temperature(double temp) {
            this.temperature = temp;
            return this;
        }

        @Override
        public GenerateBuilder topP(double topP) {
            this.topP = topP;
            return this;
        }

        @Override
        public GenerateBuilder stop(String... sequences) {
            this.stopSequences = Arrays.asList(sequences);
            return this;
        }

        // --- Context ---

        @Override
        public GenerateBuilder context(Map<String, Object> context) {
            if (context != null) {
                this.runtimeContext.putAll(context);
            }
            return this;
        }

        @Override
        public GenerateBuilder context(String key, Object value) {
            this.runtimeContext.put(key, value);
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
            ProviderEndpoint provider = providerRef.get();
            if (provider == null || !provider.isAvailable()) {
                throw new IllegalStateException("LLM provider not available for: " + functionId);
            }
            if (mcpClient == null) {
                throw new IllegalStateException("MCP client not configured for LLM agent: " + functionId);
            }

            long startTime = System.currentTimeMillis();
            try {
                String result = executeAgenticLoop(provider);
                long latency = System.currentTimeMillis() - startTime;
                // Update metadata (tokens would come from response if provider returns them)
                this.lastMeta = new GenerationMeta(0, 0, 0, latency, maxIterations, provider.provider());
                return result;
            } finally {
                clearInvocationContext();
            }
        }

        @Override
        public <T> T generate(Class<T> responseType) {
            String response = generate();

            try {
                return objectMapper.readValue(response, responseType);
            } catch (JsonProcessingException e) {
                String jsonContent = extractJsonFromResponse(response);
                if (jsonContent != null) {
                    try {
                        return objectMapper.readValue(jsonContent, responseType);
                    } catch (JsonProcessingException e2) {
                        log.warn("Failed to parse extracted JSON: {}", e2.getMessage());
                    }
                }
                throw new RuntimeException("Failed to parse LLM response as " + responseType.getSimpleName(), e);
            }
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
            return lastMeta;
        }

        // --- Internal ---

        private String executeAgenticLoop(ProviderEndpoint provider) {
            // Build the messages list for the LLM
            List<Map<String, Object>> llmMessages = new ArrayList<>();

            // 1. Add rendered system prompt (from template) if no explicit system message
            boolean hasExplicitSystem = messages.stream().anyMatch(m -> "system".equals(m.role()));
            if (!hasExplicitSystem) {
                String renderedSystemPrompt = renderSystemPrompt();
                if (!renderedSystemPrompt.isBlank()) {
                    llmMessages.add(Map.of("role", "system", "content", renderedSystemPrompt));
                }
            }

            // 2. Convert builder messages to LLM format
            for (Message msg : messages) {
                llmMessages.add(Map.of("role", msg.role(), "content", msg.content()));
            }

            // 3. Build tool definitions
            List<Map<String, Object>> toolDefs = buildToolDefinitions();

            // 4. Execute agentic loop
            int iteration = 0;
            while (iteration < maxIterations) {
                iteration++;
                log.debug("Agentic loop iteration {}/{}", iteration, maxIterations);

                // Build request params
                Map<String, Object> params = new LinkedHashMap<>();
                params.put("messages", llmMessages);
                if (!toolDefs.isEmpty()) {
                    params.put("tools", toolDefs);
                }
                if (maxTokens != null) {
                    params.put("max_tokens", maxTokens);
                } else {
                    params.put("max_tokens", defaultMaxTokens);
                }
                if (temperature != null) {
                    params.put("temperature", temperature);
                } else {
                    params.put("temperature", defaultTemperature);
                }
                if (topP != null) {
                    params.put("top_p", topP);
                }
                if (stopSequences != null && !stopSequences.isEmpty()) {
                    params.put("stop", stopSequences);
                }

                // Call LLM provider
                Map<String, Object> response;
                try {
                    response = mcpClient.callTool(provider.endpoint(), provider.functionName(), params);
                } catch (Exception e) {
                    log.error("LLM call failed: {}", e.getMessage());
                    throw new RuntimeException("LLM call failed", e);
                }

                // Check for tool calls
                List<Map<String, Object>> toolCalls = extractToolCalls(response);

                if (toolCalls.isEmpty()) {
                    return extractContent(response);
                }

                // Add assistant message with tool calls
                llmMessages.add(Map.of(
                    "role", "assistant",
                    "content", extractContent(response),
                    "tool_calls", toolCalls
                ));

                // Execute tool calls and add results
                for (Map<String, Object> toolCall : toolCalls) {
                    String toolId = (String) toolCall.get("id");
                    String toolName = (String) toolCall.get("name");
                    @SuppressWarnings("unchecked")
                    Map<String, Object> toolArgs = (Map<String, Object>) toolCall.get("arguments");

                    log.debug("Executing tool: {} with args: {}", toolName, toolArgs);
                    String toolResult = executeToolCall(toolName, toolArgs);

                    llmMessages.add(Map.of(
                        "role", "tool",
                        "tool_call_id", toolId,
                        "content", toolResult
                    ));
                }
            }

            log.warn("Max iterations ({}) reached for LLM agent {}", maxIterations, functionId);
            return extractLastAssistantContent(llmMessages);
        }

        private String renderSystemPrompt() {
            if (systemPromptTemplate == null || systemPromptTemplate.isBlank()) {
                return "";
            }

            // Merge contexts based on mode
            Map<String, Object> effectiveContext = mergeContexts();

            // Render template if needed
            if (templateRenderer.isTemplate(systemPromptTemplate) ||
                systemPromptTemplate.contains("${") ||
                systemPromptTemplate.contains("<#")) {
                try {
                    String rendered = templateRenderer.render(systemPromptTemplate, effectiveContext);
                    log.debug("Rendered system prompt with {} context variables",
                        effectiveContext != null ? effectiveContext.size() : 0);
                    return rendered;
                } catch (Exception e) {
                    log.warn("Failed to render system prompt template: {}", e.getMessage());
                    return systemPromptTemplate;
                }
            }

            return systemPromptTemplate;
        }

        private Map<String, Object> mergeContexts() {
            Map<String, Object> autoContext = invocationContext.get();
            if (autoContext == null) {
                autoContext = Map.of();
            }

            if (runtimeContext.isEmpty()) {
                return autoContext;
            }

            return switch (contextMode) {
                case REPLACE -> runtimeContext;
                case PREPEND -> {
                    Map<String, Object> merged = new LinkedHashMap<>(runtimeContext);
                    merged.putAll(autoContext); // auto wins on conflicts
                    yield merged;
                }
                case APPEND -> {
                    Map<String, Object> merged = new LinkedHashMap<>(autoContext);
                    merged.putAll(runtimeContext); // runtime wins on conflicts
                    yield merged;
                }
            };
        }
    }

    // =========================================================================
    // Helper Methods
    // =========================================================================

    private List<Map<String, Object>> buildToolDefinitions() {
        List<Map<String, Object>> tools = new ArrayList<>();

        for (ToolInfo tool : availableTools) {
            Map<String, Object> functionDef = new LinkedHashMap<>();
            functionDef.put("name", tool.name());
            functionDef.put("description", tool.description() != null ? tool.description() : "");

            Map<String, Object> schema = tool.inputSchema();
            if (schema == null || schema.isEmpty()) {
                schema = Map.of("type", "object", "properties", Map.of());
            }
            functionDef.put("parameters", schema);

            tools.add(Map.of("type", "function", "function", functionDef));
        }

        return tools;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractToolCalls(Map<String, Object> response) {
        Object toolCalls = response.get("tool_calls");
        if (toolCalls instanceof List<?> list) {
            return (List<Map<String, Object>>) list;
        }
        return List.of();
    }

    private String extractContent(Map<String, Object> response) {
        Object content = response.get("content");
        if (content instanceof String s) {
            return parseNestedContent(s);
        }
        if (content instanceof List<?> list && !list.isEmpty()) {
            Object first = list.get(0);
            if (first instanceof Map<?, ?> block) {
                Object text = block.get("text");
                if (text != null) {
                    return parseNestedContent(text.toString());
                }
            }
        }
        return "";
    }

    /**
     * Parse nested content from LLM provider responses.
     *
     * <p>Some LLM providers wrap their responses in a JSON object like:
     * {@code {"content": "actual text...", "model": "...", "tool_calls": []}}
     *
     * <p>This method extracts the inner "content" field if present,
     * otherwise returns the original string.
     */
    @SuppressWarnings("unchecked")
    private String parseNestedContent(String text) {
        if (text == null || text.isBlank()) {
            return "";
        }

        // Check if text looks like a JSON object with a "content" field
        String trimmed = text.trim();
        if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
            try {
                Map<String, Object> parsed = objectMapper.readValue(trimmed, Map.class);
                // If it has a "content" field, extract it (this is the LLM's actual response)
                if (parsed.containsKey("content")) {
                    Object innerContent = parsed.get("content");
                    if (innerContent instanceof String s) {
                        log.debug("Extracted inner content from LLM provider wrapper");
                        return s;
                    }
                }
            } catch (JsonProcessingException e) {
                // Not valid JSON, return as-is
                log.trace("Text is not JSON, returning as-is: {}", e.getMessage());
            }
        }

        return text;
    }

    private String executeToolCall(String toolName, Map<String, Object> args) {
        ToolInfo toolInfo = availableTools.stream()
            .filter(t -> t.name().equals(toolName))
            .findFirst()
            .orElse(null);

        if (toolInfo == null) {
            log.warn("Tool not found: {}", toolName);
            return "{\"error\": \"Tool not found: " + toolName + "\"}";
        }

        try {
            var proxy = dependencyInjector.getToolProxy(toolInfo.capability());
            if (proxy == null || !proxy.isAvailable()) {
                log.warn("Tool proxy not available: {}", toolInfo.capability());
                return "{\"error\": \"Tool unavailable: " + toolInfo.capability() + "\"}";
            }

            Object result = proxy.call(args);
            return objectMapper.writeValueAsString(result);
        } catch (Exception e) {
            log.error("Tool call failed: {} - {}", toolName, e.getMessage());
            return "{\"error\": \"" + e.getMessage().replace("\"", "'") + "\"}";
        }
    }

    private String extractLastAssistantContent(List<Map<String, Object>> messages) {
        for (int i = messages.size() - 1; i >= 0; i--) {
            Map<String, Object> msg = messages.get(i);
            if ("assistant".equals(msg.get("role"))) {
                Object content = msg.get("content");
                if (content instanceof String s) {
                    return s;
                }
            }
        }
        return "";
    }

    private String extractJsonFromResponse(String response) {
        if (response == null) return null;

        // First, look for JSON inside markdown code blocks (```json ... ```)
        // This is the preferred location for structured output from LLMs
        int jsonBlockStart = response.indexOf("```json");
        if (jsonBlockStart >= 0) {
            int contentStart = response.indexOf('\n', jsonBlockStart);
            if (contentStart >= 0) {
                int blockEnd = response.indexOf("```", contentStart);
                if (blockEnd > contentStart) {
                    String jsonContent = response.substring(contentStart + 1, blockEnd).trim();
                    if (log.isDebugEnabled()) {
                        log.debug("Extracted JSON from markdown code block: {} chars", jsonContent.length());
                    }
                    return jsonContent;
                }
            }
        }

        // Also check for generic code blocks that might contain JSON
        int genericBlockStart = response.lastIndexOf("```\n{");
        if (genericBlockStart >= 0) {
            int contentStart = genericBlockStart + 4; // Skip "```\n"
            int blockEnd = response.indexOf("\n```", contentStart);
            if (blockEnd > contentStart) {
                String jsonContent = response.substring(contentStart, blockEnd).trim();
                if (log.isDebugEnabled()) {
                    log.debug("Extracted JSON from generic code block: {} chars", jsonContent.length());
                }
                return jsonContent;
            }
        }

        // Fallback: find the LAST complete JSON object (not first) since LLM responses
        // often have intermediate JSON (like function results) before final output
        int lastBrace = response.lastIndexOf('}');
        if (lastBrace >= 0) {
            // Find matching opening brace by counting nesting
            int depth = 0;
            for (int i = lastBrace; i >= 0; i--) {
                char c = response.charAt(i);
                if (c == '}') depth++;
                else if (c == '{') {
                    depth--;
                    if (depth == 0) {
                        String jsonContent = response.substring(i, lastBrace + 1);
                        if (log.isDebugEnabled()) {
                            log.debug("Extracted last JSON object from response: {} chars", jsonContent.length());
                        }
                        return jsonContent;
                    }
                }
            }
        }

        // Fallback for arrays
        int lastBracket = response.lastIndexOf(']');
        if (lastBracket >= 0) {
            int depth = 0;
            for (int i = lastBracket; i >= 0; i--) {
                char c = response.charAt(i);
                if (c == ']') depth++;
                else if (c == '[') {
                    depth--;
                    if (depth == 0) {
                        return response.substring(i, lastBracket + 1);
                    }
                }
            }
        }

        return null;
    }
}
