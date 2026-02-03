package io.mcpmesh.spring;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import io.mcpmesh.types.MeshToolCallException;
import io.mcpmesh.types.MeshToolUnavailableException;
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
    private McpMeshToolProxyFactory proxyFactory;
    private ToolInvoker toolInvoker;
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
        log.info("Created MeshLlmAgentProxy for {} (proxy@{})", functionId, System.identityHashCode(this));
    }

    // =========================================================================
    // Configuration (called by MeshEventProcessor)
    // =========================================================================

    /**
     * Configure the proxy with dependencies.
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, int maxIterations) {
        configure(mcpClient, proxyFactory, toolInvoker, dependencyInjector, systemPrompt, "ctx", maxIterations);
    }

    /**
     * Configure the proxy with dependencies and context parameter name.
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations) {
        this.mcpClient = mcpClient;
        this.proxyFactory = proxyFactory;
        this.toolInvoker = toolInvoker;
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
        log.info("LLM provider updated for {} (proxy@{}): {} at {}",
            functionId, System.identityHashCode(this), provider, endpoint);
        providerRef.set(new ProviderEndpoint(endpoint, functionName, provider));
    }

    @SuppressWarnings("unchecked")
    void updateTools(List<MeshEvent.LlmToolInfo> tools) {
        availableTools.clear();
        for (MeshEvent.LlmToolInfo tool : tools) {
            log.debug("Received tool: name={}, desc='{}', cap={}, agentId={}, endpoint={}",
                tool.getFunctionName(),
                tool.getDescription(),
                tool.getCapability(),
                tool.getAgentId(),
                tool.getEndpoint());

            // Parse inputSchema from JSON string to Map
            Map<String, Object> inputSchema = null;
            String schemaStr = tool.getInputSchema();
            if (schemaStr != null && !schemaStr.isEmpty()) {
                try {
                    inputSchema = objectMapper.readValue(schemaStr, Map.class);
                } catch (JacksonException e) {
                    log.warn("Failed to parse input schema for tool {}: {}", tool.getFunctionName(), e.getMessage());
                }
            }

            // For LLM-discovered tools, we don't know the return type from mesh events
            // Default to null (will use Object.class in getReturnTypeOrDefault())
            // Future: Rust core could send return_type in LlmToolInfo
            // Set available=true for tools discovered from mesh
            boolean hasEndpoint = tool.getEndpoint() != null && !tool.getEndpoint().isBlank();
            availableTools.add(new ToolInfo(
                tool.getFunctionName(),
                tool.getDescription(),
                tool.getCapability(),
                tool.getAgentId(),
                tool.getEndpoint(),
                null,  // returnType - unknown for mesh-discovered tools
                inputSchema,
                hasEndpoint  // available - true if endpoint is valid
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
        boolean available = provider != null && provider.isAvailable();
        log.debug("isAvailable() for {}: provider={}, endpoint={}, result={}",
            functionId,
            provider != null ? provider.provider() : "null",
            provider != null ? provider.endpoint() : "null",
            available);
        return available;
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

        // Response type for auto-generating JSON schema instructions
        private Class<?> responseType = null;

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
            // Set response type so executeAgenticLoop can generate JSON schema instructions
            this.responseType = responseType;

            String response = generate();

            try {
                return objectMapper.readValue(response, responseType);
            } catch (JacksonException e) {
                String jsonContent = extractJsonFromResponse(response);
                if (jsonContent != null) {
                    try {
                        return objectMapper.readValue(jsonContent, responseType);
                    } catch (JacksonException e2) {
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
                // Note: JSON schema is passed via model_params.output_schema, not injected in prompt
                // This allows LLM provider handlers to use vendor-specific structured output mechanisms
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
            log.info("Built {} tool definitions for LLM (availableTools={})",
                toolDefs.size(), availableTools.size());

            // 4. Execute agentic loop
            int iteration = 0;
            while (iteration < maxIterations) {
                iteration++;
                log.debug("Agentic loop iteration {}/{}", iteration, maxIterations);

                // Build model_params (LLM provider configuration)
                Map<String, Object> modelParams = new LinkedHashMap<>();
                modelParams.put("max_tokens", maxTokens != null ? maxTokens : defaultMaxTokens);
                modelParams.put("temperature", temperature != null ? temperature : defaultTemperature);
                if (topP != null) {
                    modelParams.put("top_p", topP);
                }
                if (stopSequences != null && !stopSequences.isEmpty()) {
                    modelParams.put("stop", stopSequences);
                }
                // Pass output_schema for structured output (provider handles vendor-specific conversion)
                if (responseType != null && responseType != String.class) {
                    Map<String, Object> outputSchema = buildJsonSchema(responseType);
                    if (outputSchema != null) {
                        modelParams.put("output_schema", outputSchema);
                        modelParams.put("output_type_name", responseType.getSimpleName());
                        log.debug("Added output_schema for structured output: {}", responseType.getSimpleName());
                    }
                }

                // Build request wrapper (matches Python/TypeScript SDK format)
                Map<String, Object> request = new LinkedHashMap<>();
                request.put("messages", llmMessages);
                if (!toolDefs.isEmpty()) {
                    request.put("tools", toolDefs);
                }
                request.put("model_params", modelParams);

                // Final params with request wrapper
                Map<String, Object> params = Map.of("request", request);

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
                    String toolName;
                    Map<String, Object> toolArgs;

                    // Handle OpenAI-style format where name/arguments are nested in "function"
                    @SuppressWarnings("unchecked")
                    Map<String, Object> function = (Map<String, Object>) toolCall.get("function");
                    if (function != null) {
                        toolName = (String) function.get("name");
                        // Arguments come as a JSON string in OpenAI format
                        Object argsObj = function.get("arguments");
                        toolArgs = parseToolArguments(argsObj);
                    } else {
                        // Fallback to flat format (Anthropic native format)
                        toolName = (String) toolCall.get("name");
                        Object argsObj = toolCall.get("arguments");
                        toolArgs = parseToolArguments(argsObj);
                    }

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
                log.debug("renderSystemPrompt: template is null or blank");
                return "";
            }

            log.info("renderSystemPrompt: template='{}' (isTemplate={})",
                systemPromptTemplate.length() > 50 ? systemPromptTemplate.substring(0, 50) + "..." : systemPromptTemplate,
                templateRenderer.isTemplate(systemPromptTemplate));

            // Merge contexts based on mode, then add tools
            Map<String, Object> effectiveContext = new LinkedHashMap<>(mergeContexts());

            // Always add tools to context - templates can use <#if tools?has_content>
            // to conditionally render tool lists or "no tools" messages
            // Convert ToolInfo records to Maps for FreeMarker compatibility
            // (FreeMarker doesn't understand record accessors like name())
            List<Map<String, Object>> toolMaps = new ArrayList<>();
            for (ToolInfo tool : availableTools) {
                Map<String, Object> toolMap = new LinkedHashMap<>();
                toolMap.put("name", tool.name());
                toolMap.put("description", tool.description());
                toolMap.put("capability", tool.capability());
                toolMaps.add(toolMap);
            }
            effectiveContext.put("tools", toolMaps);
            log.info("renderSystemPrompt: context has {} vars, tools={}", effectiveContext.size(), availableTools.size());

            // Render template if needed
            if (templateRenderer.isTemplate(systemPromptTemplate) ||
                systemPromptTemplate.contains("${") ||
                systemPromptTemplate.contains("<#")) {
                try {
                    String rendered = templateRenderer.render(systemPromptTemplate, effectiveContext);
                    log.info("renderSystemPrompt: SUCCESS - rendered {} chars", rendered.length());
                    return rendered;
                } catch (Exception e) {
                    log.error("renderSystemPrompt: FAILED to render template: {}", e.getMessage(), e);
                    return systemPromptTemplate;
                }
            }

            log.info("renderSystemPrompt: template doesn't need rendering, returning as-is");
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

        /**
         * Build JSON schema from the response type class.
         *
         * <p>This generates a JSON Schema object that can be passed to LLM providers
         * via model_params.output_schema. The provider handler converts this to
         * vendor-specific structured output format (e.g., response_format for OpenAI/Gemini).
         *
         * <p>Uses reflection to inspect record components or class fields.
         *
         * @param type the response type class
         * @return JSON schema as a Map, or null if schema cannot be built
         */
        private Map<String, Object> buildJsonSchema(Class<?> type) {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");

            Map<String, Object> properties = new LinkedHashMap<>();
            List<String> required = new ArrayList<>();

            // Handle records - use getGenericType() to preserve parameterized types
            if (type.isRecord()) {
                var components = type.getRecordComponents();
                for (var comp : components) {
                    properties.put(comp.getName(), getJsonSchemaType(comp.getGenericType()));
                    required.add(comp.getName());
                }
            } else {
                // Handle regular classes - use declared fields with generic types
                var fields = type.getDeclaredFields();
                for (var field : fields) {
                    if (java.lang.reflect.Modifier.isStatic(field.getModifiers())) continue;
                    properties.put(field.getName(), getJsonSchemaType(field.getGenericType()));
                    required.add(field.getName());
                }
            }

            schema.put("properties", properties);
            schema.put("required", required);
            return schema;
        }

        /**
         * Get JSON schema type for a given Java type.
         *
         * <p>Handles both raw classes and parameterized types (e.g., List&lt;String&gt;).
         * For collections, extracts the element type from the generic parameter.
         *
         * @param type the Java type (Class or ParameterizedType)
         * @return JSON schema type object
         */
        private Map<String, Object> getJsonSchemaType(java.lang.reflect.Type type) {
            Map<String, Object> schemaType = new LinkedHashMap<>();

            // Handle parameterized types (e.g., List<String>, Map<String, Object>)
            if (type instanceof java.lang.reflect.ParameterizedType pt) {
                Class<?> rawType = (Class<?>) pt.getRawType();

                if (java.util.Collection.class.isAssignableFrom(rawType)) {
                    schemaType.put("type", "array");
                    // Get the element type from the generic parameter
                    java.lang.reflect.Type[] typeArgs = pt.getActualTypeArguments();
                    if (typeArgs.length > 0) {
                        schemaType.put("items", getJsonSchemaType(typeArgs[0]));
                    } else {
                        schemaType.put("items", Map.of("type", "object"));
                    }
                    return schemaType;
                } else if (java.util.Map.class.isAssignableFrom(rawType)) {
                    schemaType.put("type", "object");
                    return schemaType;
                }
                // Fall through to handle rawType as a regular class
                type = rawType;
            }

            // Handle raw class types
            if (type instanceof Class<?> clazz) {
                if (clazz == String.class) {
                    schemaType.put("type", "string");
                } else if (clazz == int.class || clazz == Integer.class ||
                           clazz == long.class || clazz == Long.class) {
                    schemaType.put("type", "integer");
                } else if (clazz == double.class || clazz == Double.class ||
                           clazz == float.class || clazz == Float.class) {
                    schemaType.put("type", "number");
                } else if (clazz == boolean.class || clazz == Boolean.class) {
                    schemaType.put("type", "boolean");
                } else if (clazz.isArray()) {
                    schemaType.put("type", "array");
                    Class<?> componentType = clazz.getComponentType();
                    schemaType.put("items", getJsonSchemaType(componentType));
                } else if (java.util.Collection.class.isAssignableFrom(clazz)) {
                    // Raw collection without type parameter - default to object
                    schemaType.put("type", "array");
                    schemaType.put("items", Map.of("type", "object"));
                } else if (java.util.Map.class.isAssignableFrom(clazz)) {
                    schemaType.put("type", "object");
                } else {
                    schemaType.put("type", "object");
                }
            } else {
                // Unknown type - default to object
                schemaType.put("type", "object");
            }

            return schemaType;
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

            // Generate description from tool name and schema if not provided
            String description = tool.description();
            if (description == null || description.isEmpty()) {
                description = generateToolDescription(tool);
            }
            functionDef.put("description", description);

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
        // First check top-level tool_calls
        Object toolCalls = response.get("tool_calls");
        if (toolCalls instanceof List<?> list && !list.isEmpty()) {
            return (List<Map<String, Object>>) list;
        }

        // Check for nested JSON in content[0].text (MCP response format)
        // Response format: {"content":[{"type":"text","text":"{\"content\":\"...\",\"tool_calls\":[...]}"}]}
        Object content = response.get("content");
        if (content instanceof List<?> contentList && !contentList.isEmpty()) {
            Object first = contentList.get(0);
            if (first instanceof Map<?, ?> block) {
                Object text = block.get("text");
                if (text instanceof String textStr && textStr.trim().startsWith("{")) {
                    try {
                        Map<String, Object> parsed = objectMapper.readValue(textStr, Map.class);
                        Object nestedToolCalls = parsed.get("tool_calls");
                        if (nestedToolCalls instanceof List<?> nestedList && !nestedList.isEmpty()) {
                            log.debug("Extracted {} tool calls from nested JSON", nestedList.size());
                            return (List<Map<String, Object>>) nestedList;
                        }
                    } catch (JacksonException e) {
                        log.trace("Failed to parse nested JSON for tool_calls: {}", e.getMessage());
                    }
                }
            }
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
     * Parse tool arguments from various formats.
     *
     * <p>Handles:
     * <ul>
     *   <li>JSON string (OpenAI format): {@code "{\"city\":\"Boston\"}"}</li>
     *   <li>Already-parsed Map (Anthropic native format)</li>
     *   <li>Null or empty values</li>
     * </ul>
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> parseToolArguments(Object argsObj) {
        if (argsObj == null) {
            return Map.of();
        }
        if (argsObj instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        if (argsObj instanceof String argsStr) {
            if (argsStr.isBlank() || argsStr.equals("{}")) {
                return Map.of();
            }
            try {
                return objectMapper.readValue(argsStr, Map.class);
            } catch (JacksonException e) {
                log.warn("Failed to parse tool arguments JSON: {}", e.getMessage());
                return Map.of();
            }
        }
        log.warn("Unexpected tool arguments type: {}", argsObj.getClass().getName());
        return Map.of();
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
            } catch (JacksonException e) {
                // Not valid JSON, return as-is
                log.trace("Text is not JSON, returning as-is: {}", e.getMessage());
            }
        }

        return text;
    }

    /**
     * Execute a tool call and return the result as a JSON string.
     *
     * <p>Error Handling Strategy (for LLM agentic loops):
     * <ul>
     *   <li>Errors are returned as JSON strings, not thrown as exceptions</li>
     *   <li>This allows the LLM to see errors and potentially self-correct</li>
     *   <li>Error format: {@code {"error": {"type": "...", "tool": "...", "message": "..."}}}</li>
     * </ul>
     *
     * <p>This differs from {@link McpMeshToolProxy} which throws exceptions,
     * because in an agentic loop the LLM benefits from seeing error details.
     *
     * @param toolName The tool function name to call
     * @param args     The arguments to pass to the tool
     * @return JSON string result, or JSON error object if the call failed
     */
    private String executeToolCall(String toolName, Map<String, Object> args) {
        ToolInfo toolInfo = availableTools.stream()
            .filter(t -> t.name().equals(toolName))
            .findFirst()
            .orElse(null);

        if (toolInfo == null) {
            log.warn("Tool not found: {}", toolName);
            return buildErrorResponse("tool_not_found", toolName, "Tool not found in available tools list");
        }

        // Check availability using ToolInfo's isAvailable() which checks both
        // the available flag and endpoint validity
        if (!toolInfo.isAvailable()) {
            log.warn("Tool not available: {} (available={}, endpoint={})",
                toolName, toolInfo.available(), toolInfo.endpoint());
            return buildErrorResponse("tool_unavailable", toolName,
                "Tool is not currently available. It may have gone offline or been unregistered.");
        }

        try {
            // Use ToolInvoker for unified invocation (supports both local and remote)
            // Local invocation is used when the tool is on the same agent (self-dependency)
            boolean isLocal = toolInvoker != null && toolInvoker.isSelfDependency(toolInfo);
            log.debug("Calling tool {} {} (returnType={}, agentId={})",
                toolName,
                isLocal ? "locally" : "at endpoint " + toolInfo.endpoint(),
                toolInfo.getReturnTypeOrDefault(),
                toolInfo.agentId());

            Object result;
            if (toolInvoker != null) {
                // Use ToolInvoker for smart local/remote invocation
                result = toolInvoker.invoke(toolInfo, args);
            } else {
                // Fallback to direct proxy invocation (if toolInvoker not configured)
                McpMeshTool<?> proxy = proxyFactory.getOrCreateProxy(
                    toolInfo.endpoint(), toolName, toolInfo.getReturnTypeOrDefault());
                result = proxy.call(args);
            }

            // Handle various result types - return as JSON string for LLM
            if (result == null) {
                return "{}";
            } else if (result instanceof String s) {
                // Already a string - might be JSON or plain text
                return s;
            } else {
                // Serialize complex objects to JSON
                return objectMapper.writeValueAsString(result);
            }
        } catch (MeshToolUnavailableException e) {
            // Tool/agent became unavailable (went offline, unregistered, etc.)
            // Mark the tool as unavailable so subsequent calls in this agentic loop
            // can see it's unavailable without attempting another call
            markToolUnavailable(toolName);
            log.warn("Tool unavailable: {} - {}", toolName, e.getMessage());
            return buildErrorResponse("tool_unavailable", toolName,
                "The tool is currently unavailable. It may have gone offline or been unregistered.");
        } catch (MeshToolCallException e) {
            // Tool call failed (network error, remote error, serialization error)
            log.error("Tool call failed: {} - {}", toolName, e.getMessage());
            return buildErrorResponse("tool_call_failed", toolName, e.getMessage());
        } catch (Exception e) {
            // Unexpected error
            log.error("Unexpected error calling tool: {} - {}", toolName, e.getMessage(), e);
            return buildErrorResponse("unexpected_error", toolName, e.getMessage());
        }
    }

    /**
     * Build a structured JSON error response for the LLM.
     *
     * <p>The structured format helps the LLM understand:
     * <ul>
     *   <li>What type of error occurred (for potential retry logic)</li>
     *   <li>Which tool was being called</li>
     *   <li>A human-readable message describing the problem</li>
     * </ul>
     *
     * @param errorType Short error type identifier (e.g., "tool_not_found", "tool_unavailable")
     * @param toolName  The tool that was being called
     * @param message   Human-readable error description
     * @return JSON error string
     */
    private String buildErrorResponse(String errorType, String toolName, String message) {
        // Escape quotes in message to ensure valid JSON
        String safeMessage = message != null ? message.replace("\"", "'").replace("\\", "\\\\") : "Unknown error";
        return String.format(
            "{\"error\":{\"type\":\"%s\",\"tool\":\"%s\",\"message\":\"%s\"}}",
            errorType, toolName, safeMessage
        );
    }

    /**
     * Mark a tool as unavailable in the available tools list.
     *
     * <p>This is called when a tool call fails with {@link MeshToolUnavailableException},
     * indicating the tool/agent has gone offline or been unregistered. Marking it
     * unavailable allows subsequent calls in the same agentic loop to see the tool
     * is unavailable via {@link ToolInfo#isAvailable()} without attempting another call.
     *
     * @param toolName The name of the tool to mark as unavailable
     */
    private void markToolUnavailable(String toolName) {
        for (int i = 0; i < availableTools.size(); i++) {
            ToolInfo tool = availableTools.get(i);
            if (tool.name().equals(toolName)) {
                // Replace with an unavailable copy
                availableTools.set(i, tool.markUnavailable());
                log.debug("Marked tool as unavailable: {}", toolName);
                return;
            }
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

    /**
     * Generate a fallback description for a tool when none is provided.
     *
     * <p>Creates a human-readable description from the tool name and its input schema.
     * The description format is: "{capability} tool: {name} (params: p1, p2, ...)"
     */
    private String generateToolDescription(ToolInfo tool) {
        StringBuilder sb = new StringBuilder();
        sb.append(tool.capability()).append(" tool: ").append(tool.name());

        Map<String, Object> schema = tool.inputSchema();
        if (schema != null && schema.containsKey("properties")) {
            @SuppressWarnings("unchecked")
            Map<String, Object> props = (Map<String, Object>) schema.get("properties");
            if (props != null && !props.isEmpty()) {
                sb.append(" (params: ");
                sb.append(String.join(", ", props.keySet()));
                sb.append(")");
            }
        }

        return sb.toString();
    }
}
