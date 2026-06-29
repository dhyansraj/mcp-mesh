package io.mcpmesh.spring;

import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import io.mcpmesh.MeshLlmDefaults;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.spring.media.MediaFetchResult;
import io.mcpmesh.spring.media.MediaResolver;
import io.mcpmesh.spring.media.MediaStore;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import io.mcpmesh.types.MeshToolCallException;
import io.mcpmesh.types.MeshToolUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Flow;
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
    private static final ObjectMapper objectMapper = MeshObjectMappers.create();

    /**
     * Lenient mapper used ONLY for deserializing structured-output responses into a
     * user-supplied response model (the {@code generate(Class)} path).
     *
     * <p>Under {@code output_mode=hint}, the provider embeds the response schema in the
     * prompt but does not enforce it natively, so the LLM may emit loosely-shaped JSON —
     * most commonly a scalar where the schema declares a list (e.g. {@code "insights": "x"}
     * instead of {@code ["x"]}). {@link DeserializationFeature#ACCEPT_SINGLE_VALUE_AS_ARRAY}
     * coerces that single-value-as-array drift. This is a no-op for well-shaped (strict)
     * output and is intentionally scoped to response-model parsing only — it must NOT be
     * applied to the wire/tool-callback mappers above.
     */
    private static final ObjectMapper responseModelMapper = JsonMapper.builder()
        .enable(DeserializationFeature.ACCEPT_SINGLE_VALUE_AS_ARRAY)
        .build();

    private final String functionId;
    private final List<ToolInfo> availableTools = new CopyOnWriteArrayList<>();
    private final AtomicReference<ProviderEndpoint> providerRef = new AtomicReference<>();

    // Configuration from @MeshLlm annotation
    private volatile String systemPromptTemplate = "";
    private volatile String contextParamName = "ctx";
    private volatile int defaultMaxIterations = MeshLlmDefaults.MAX_ITERATIONS;
    private volatile int defaultMaxTokens = MeshLlmDefaults.MAX_TOKENS_UNSET;
    private volatile double defaultTemperature = MeshLlmDefaults.TEMPERATURE_UNSET;
    private volatile boolean parallelToolCalls = false;
    private volatile String defaultOutputMode = MeshLlmDefaults.OUTPUT_MODE_UNSET;
    private volatile String defaultModel = "";

    private McpHttpClient mcpClient;
    private McpMeshToolProxyFactory proxyFactory;
    private ToolInvoker toolInvoker;
    private MeshDependencyInjector dependencyInjector;
    private PromptTemplateRenderer templateRenderer;
    private MediaStore mediaStore;

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
        this.defaultMaxIterations = maxIterations > 0 ? maxIterations : MeshLlmDefaults.MAX_ITERATIONS;
    }

    /**
     * Configure the proxy with dependencies and parallel tool calls option.
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations,
                          boolean parallelToolCalls) {
        configure(mcpClient, proxyFactory, toolInvoker, dependencyInjector, systemPrompt, contextParamName, maxIterations);
        this.parallelToolCalls = parallelToolCalls;
        if (parallelToolCalls) {
            log.info("parallel tool calls enabled — tools will execute concurrently for {}", functionId);
        }
    }

    /**
     * Configure the proxy with dependencies, parallel tool calls option, and
     * {@code @MeshLlm} annotation defaults for {@code maxTokens} / {@code temperature}.
     *
     * <p>Wires the annotation values through to the wire {@code model_params} so a
     * user writing {@code @MeshLlm(maxTokens=2000, temperature=0.3)} actually sees
     * those values on the wire. When {@code maxTokens}/{@code temperature} are left
     * unset (sentinels {@code -1} / {@code NaN}), neither key is injected and the
     * provider's own default applies.
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations,
                          boolean parallelToolCalls, int maxTokens, double temperature) {
        configure(mcpClient, proxyFactory, toolInvoker, dependencyInjector, systemPrompt, contextParamName, maxIterations, parallelToolCalls);
        this.defaultMaxTokens = maxTokens;
        this.defaultTemperature = temperature;
        log.info("@MeshLlm defaults for {}: maxTokens={}, temperature={}", functionId, maxTokens, temperature);
    }

    /**
     * Configure the proxy with dependencies, parallel tool calls option,
     * {@code maxTokens}/{@code temperature} defaults, and the {@code @MeshLlm}
     * {@code outputMode}.
     *
     * <p>Wires the annotation's {@code outputMode} through to the wire
     * {@code model_params.output_mode} so the provider honors the consumer's
     * requested structured-output mode. When {@code outputMode} is left unset
     * ({@link MeshLlmDefaults#OUTPUT_MODE_UNSET}), no {@code output_mode} key is
     * injected and the provider auto-selects per vendor/schema (zero regression).
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations,
                          boolean parallelToolCalls, int maxTokens, double temperature,
                          String outputMode) {
        configure(mcpClient, proxyFactory, toolInvoker, dependencyInjector, systemPrompt, contextParamName, maxIterations, parallelToolCalls, maxTokens, temperature);
        this.defaultOutputMode = outputMode != null ? outputMode : MeshLlmDefaults.OUTPUT_MODE_UNSET;
        if (!this.defaultOutputMode.isEmpty()) {
            log.info("@MeshLlm outputMode for {}: {}", functionId, this.defaultOutputMode);
        }
    }

    /**
     * Configure the proxy with dependencies, parallel tool calls option,
     * {@code maxTokens}/{@code temperature} defaults, the {@code @MeshLlm}
     * {@code outputMode}, and the optional {@code @MeshLlm} {@code model}
     * per-tool override.
     *
     * <p>Wires the annotation's {@code model} through to the wire
     * {@code model_params.model} so the consumer can request a specific model per
     * tool. The provider honors it when the override's vendor matches its own,
     * else falls back to the provider's default model (vendor-checked, mirroring
     * Python). When {@code model} is left unset (empty/blank), no {@code model}
     * key is injected and the provider uses its own declared model. A per-call
     * {@code modelParams(Map.of("model", ...))} override takes precedence over
     * this annotation value.
     */
    public void configure(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                          ToolInvoker toolInvoker, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, String contextParamName, int maxIterations,
                          boolean parallelToolCalls, int maxTokens, double temperature,
                          String outputMode, String model) {
        configure(mcpClient, proxyFactory, toolInvoker, dependencyInjector, systemPrompt, contextParamName, maxIterations, parallelToolCalls, maxTokens, temperature, outputMode);
        this.defaultModel = (model != null && !model.isBlank()) ? model : "";
        if (!this.defaultModel.isEmpty()) {
            log.info("@MeshLlm model override for {}: {}", functionId, this.defaultModel);
        }
    }

    /**
     * Set the MediaStore for resolving media URIs in multimodal requests.
     *
     * @param mediaStore The MediaStore bean (may be null if not configured)
     */
    public void setMediaStore(MediaStore mediaStore) {
        this.mediaStore = mediaStore;
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

    /**
     * Issue #1164 MED-4: capture the caller thread's per-request context and
     * restore it inside an async task running on a pool thread.
     *
     * <p>{@code CompletableFuture.supplyAsync(this::generate)} previously ran
     * with empty ThreadLocals on the pool thread: the invocation context
     * ({@code ${ctx.*}} template variables set by {@link MeshToolWrapper} on
     * the servlet thread) read null, and {@link TraceContext} was empty — so
     * outbound calls carried neither trace headers nor propagated headers
     * (X-Mesh-Job-Id, X-Mesh-Timeout, allowlisted auth).
     *
     * <p>The returned supplier layers {@link TraceContext#wrapSupplier} (trace
     * info + propagated headers, with restore-previous semantics) and a
     * capture/restore of this proxy's {@code invocationContext} ThreadLocal,
     * with a finally that clears it so pool threads aren't polluted.
     */
    private <T> java.util.function.Supplier<T> withCallerContext(java.util.function.Supplier<T> inner) {
        Map<String, Object> capturedCtx = invocationContext.get();
        java.util.function.Supplier<T> traced = TraceContext.wrapSupplier(inner);
        return () -> {
            Map<String, Object> previous = invocationContext.get();
            if (capturedCtx != null) {
                invocationContext.set(capturedCtx);
            }
            try {
                return traced.get();
            } finally {
                if (previous != null) {
                    invocationContext.set(previous);
                } else {
                    invocationContext.remove();
                }
            }
        };
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

    /**
     * Stream chunks from the resolved mesh-delegated streaming provider.
     *
     * <p>Delegates to the builder path
     * ({@code request().messages(messages).streamGenerate()}) so the
     * model_params merge, system-prompt rendering, tool definitions, and
     * transport routing are consolidated into a single code path shared with
     * {@link GenerateBuilder#streamGenerate()}.
     *
     * @param messages Conversation messages to send
     * @return A {@link Flow.Publisher} of text chunks
     * @throws IllegalStateException if no mesh provider is currently resolved
     */
    @Override
    public Flow.Publisher<String> stream(List<Message> messages) {
        return request().messages(messages).streamGenerate();
    }

    // =========================================================================
    // GenerateBuilder Implementation
    // =========================================================================

    private class GenerateBuilderImpl implements GenerateBuilder {

        private final List<Message> messages = new ArrayList<>();
        private final Map<String, Object> runtimeContext = new LinkedHashMap<>();
        private final List<String> mediaUris = new ArrayList<>();
        private ContextMode contextMode = ContextMode.APPEND;

        // Override options (null = use defaults)
        private Integer maxTokens = null;
        private Double temperature = null;
        private Double topP = null;
        private List<String> stopSequences = null;
        private int maxIterations = defaultMaxIterations;

        // Issue #1019: escape-hatch for vendor-specific model_params kwargs
        // (e.g., thinking_config, output_config, reasoning_effort) not exposed
        // by the typed builder. Merged into the wire model_params BEFORE typed
        // setters so typed values win on collision.
        private Map<String, Object> userModelParams = null;

        // Response type for auto-generating JSON schema instructions
        private Class<?> responseType = null;

        // Metadata from last call
        private GenerationMeta lastMeta = null;

        // Accumulated LLM token usage across agentic-loop iterations (issue #1227).
        // Read by generate() to populate lastMeta and published to the consumer
        // span via TraceContext.setLlmMetadata.
        private long accumulatedInputTokens = 0;
        private long accumulatedOutputTokens = 0;
        private String effectiveModel = null;

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

        // --- Media ---

        @Override
        public GenerateBuilder media(String... uris) {
            if (uris != null) {
                mediaUris.addAll(Arrays.asList(uris));
            }
            return this;
        }

        @Override
        public GenerateBuilder media(List<String> uris) {
            if (uris != null) {
                mediaUris.addAll(uris);
            }
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

        @Override
        public GenerateBuilder modelParams(Map<String, Object> params) {
            this.userModelParams = params;
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
                // Update metadata with the token usage accumulated across the
                // agentic loop (issue #1227). effectiveModel falls back to the
                // provider name when the response carried no model field.
                int in = (int) accumulatedInputTokens;
                int out = (int) accumulatedOutputTokens;
                String model = effectiveModel != null ? effectiveModel : provider.provider();
                this.lastMeta = new GenerationMeta(in, out, in + out, latency, maxIterations, model);
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
                return responseModelMapper.readValue(response, responseType);
            } catch (JacksonException e) {
                String jsonContent = extractJsonFromResponse(response);
                if (jsonContent != null) {
                    try {
                        return responseModelMapper.readValue(jsonContent, responseType);
                    } catch (JacksonException e2) {
                        log.warn("Failed to parse extracted JSON: {}", e2.getMessage());
                    }
                }
                throw new RuntimeException("Failed to parse LLM response as " + responseType.getSimpleName(), e);
            }
        }

        @Override
        public CompletableFuture<String> generateAsync() {
            // Issue #1164 MED-4: propagate caller-thread context (trace +
            // propagated headers + invocation context) onto the pool thread.
            return CompletableFuture.supplyAsync(withCallerContext(this::generate));
        }

        @Override
        public <T> CompletableFuture<T> generateAsync(Class<T> responseType) {
            return CompletableFuture.supplyAsync(withCallerContext(() -> generate(responseType)));
        }

        @Override
        public GenerationMeta lastMeta() {
            return lastMeta;
        }

        @Override
        public Flow.Publisher<String> streamGenerate() {
            try {
                ProviderEndpoint provider = providerRef.get();
                if (provider == null || !provider.isAvailable()) {
                    throw new IllegalStateException(
                        "MeshLlmAgent.streamGenerate(): LLM provider not available for " + functionId
                            + ". Ensure the @MeshLlm providerSelector resolves a streaming @mesh.llm_provider "
                            + "(must include the 'ai.mcpmesh.stream' tag)."
                    );
                }
                if (mcpClient == null) {
                    throw new IllegalStateException(
                        "MeshLlmAgent.streamGenerate(): MCP client not configured for LLM agent " + functionId);
                }

                // Build llmMessages mirroring executeAgenticLoop:
                // 1. Prepend rendered system prompt template if no explicit system message.
                // Use LinkedHashMap instead of Map.of() because Message.content() can be null
                // for tool/assistant messages that only carry tool_calls (Map.of throws NPE on null).
                List<Map<String, Object>> llmMessages = new ArrayList<>();
                boolean hasExplicitSystem = messages.stream()
                    .anyMatch(m -> "system".equals(m.role()));
                if (!hasExplicitSystem) {
                    String renderedSystemPrompt = renderSystemPrompt();
                    if (!renderedSystemPrompt.isBlank()) {
                        Map<String, Object> systemEntry = new LinkedHashMap<>(2);
                        systemEntry.put("role", "system");
                        systemEntry.put("content", renderedSystemPrompt);
                        llmMessages.add(systemEntry);
                    }
                }

                // 2. Convert builder messages to LLM format
                for (Message msg : messages) {
                    Map<String, Object> entry = new LinkedHashMap<>(2);
                    entry.put("role", msg.role());
                    entry.put("content", msg.content());
                    llmMessages.add(entry);
                }

                // 2.5. Resolve media URIs and attach to last user message
                if (!mediaUris.isEmpty()) {
                    attachMediaToLastUserMessage(llmMessages, provider);
                }

                // 3. Build merged model_params (same guard semantics as executeAgenticLoop:
                // userModelParams merged FIRST, typed setters take precedence on collision,
                // annotation defaults apply only when neither source supplied the key).
                Map<String, Object> modelParams = buildMergedModelParams();

                // 4. Tool definitions (provider executes them server-side in its loop)
                List<Map<String, Object>> toolDefs = buildToolDefinitions();

                // 5. Build request wrapper
                Map<String, Object> request = new LinkedHashMap<>();
                request.put("messages", llmMessages);
                if (!toolDefs.isEmpty()) {
                    request.put("tools", toolDefs);
                }
                request.put("model_params", modelParams);

                Map<String, Object> params = Map.of("request", request);

                log.debug("streamGenerate(mesh): routing to {}/{} (messages={}, tools={})",
                    provider.endpoint(), provider.functionName(),
                    llmMessages.size(), toolDefs.size());

                return mcpClient.streamTool(provider.endpoint(), provider.functionName(), params, null);
            } finally {
                // Clear the ThreadLocal invocationContext on return so it does not
                // leak across pooled-thread reuse (Spring/Tomcat). The ThreadLocal
                // is only read synchronously during Publisher construction
                // (renderSystemPrompt above); subscriber callbacks run on the
                // streaming I/O thread, so clearing here on the originating
                // thread is the correct place. Mirrors the buffered generate()
                // path which already wraps in try/finally.
                clearInvocationContext();
            }
        }

        // --- Internal ---

        /**
         * Build the wire {@code model_params} map applying the same merge
         * semantics used by both the buffered {@link #executeAgenticLoop} and
         * the streaming {@link #streamGenerate} paths:
         * <ol>
         *   <li>{@code userModelParams} (escape-hatch) is merged FIRST so
         *       typed setters can override on collision.</li>
         *   <li>Typed setters ({@link #maxTokens}, {@link #temperature}, etc.)
         *       win on collision with {@code modelParams}.</li>
         *   <li>Annotation defaults ({@code defaultMaxTokens},
         *       {@code defaultTemperature}, {@code parallel_tool_calls})
         *       apply only when {@code modelParams} did not supply the key.
         *       For {@code parallel_tool_calls} specifically: the annotation
         *       value is written only when {@code parallelToolCalls=true} AND
         *       {@code modelParams} did not already provide the key, so a
         *       caller can explicitly disable parallel-tool-calls for a single
         *       call via {@code .modelParams(Map.of("parallel_tool_calls", false))}
         *       even when the annotation enabled it.</li>
         * </ol>
         *
         * <p>Note: {@code output_schema} (structured-output) is not added here
         * because it's specific to the buffered {@code generate(Class)} path —
         * streaming does not currently parse structured output.
         */
        private Map<String, Object> buildMergedModelParams() {
            Map<String, Object> modelParams = new LinkedHashMap<>();
            if (userModelParams != null && !userModelParams.isEmpty()) {
                modelParams.putAll(userModelParams);
            }
            if (maxTokens != null) {
                modelParams.put("max_tokens", maxTokens);
            } else if (!modelParams.containsKey("max_tokens") && defaultMaxTokens >= 0) {
                modelParams.put("max_tokens", defaultMaxTokens);
            }
            if (temperature != null && !Double.isNaN(temperature)) {
                modelParams.put("temperature", temperature);
            } else if (!modelParams.containsKey("temperature") && !Double.isNaN(defaultTemperature)) {
                modelParams.put("temperature", defaultTemperature);
            }
            if (topP != null) {
                modelParams.put("top_p", topP);
            }
            if (stopSequences != null && !stopSequences.isEmpty()) {
                modelParams.put("stop", stopSequences);
            }
            if (parallelToolCalls && !modelParams.containsKey("parallel_tool_calls")) {
                modelParams.put("parallel_tool_calls", true);
            }
            // output_mode (issue #1112): inject the annotation's resolved mode only
            // when explicitly set (non-UNSET) AND the escape-hatch modelParams did
            // not already supply it. Unset → key omitted → provider auto-selects
            // per vendor/schema (zero regression).
            if (defaultOutputMode != null && !defaultOutputMode.isEmpty()
                    && !modelParams.containsKey("output_mode")) {
                modelParams.put("output_mode", defaultOutputMode);
            }
            // model (@MeshLlm(model=...)): inject the annotation's per-tool model
            // override only when set AND the escape-hatch modelParams did not
            // already supply a "model" (a per-call .modelParams(Map.of("model", ...))
            // wins). Unset → key omitted → provider uses its own declared model.
            if (defaultModel != null && !defaultModel.isEmpty()
                    && !modelParams.containsKey("model")) {
                modelParams.put("model", defaultModel);
            }
            return modelParams;
        }

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

            // 2. Convert builder messages to LLM format.
            // LinkedHashMap instead of Map.of: Message.content() can be null for
            // assistant turns that only carried tool_calls (Map.of throws NPE on
            // null values) — mirrors streamGenerate (issue #1164 MED-3).
            for (Message msg : messages) {
                Map<String, Object> entry = new LinkedHashMap<>(2);
                entry.put("role", msg.role());
                entry.put("content", msg.content());
                llmMessages.add(entry);
            }

            // 2.5. Resolve media URIs and attach to the last user message
            if (!mediaUris.isEmpty()) {
                attachMediaToLastUserMessage(llmMessages, provider);
            }

            // 3. Build tool definitions
            List<Map<String, Object>> toolDefs = buildToolDefinitions();
            log.info("Built {} tool definitions for LLM (availableTools={})",
                toolDefs.size(), availableTools.size());

            // 4. Execute agentic loop. Reset per-call accumulators so a reused
            // builder doesn't carry stale token totals (issue #1227).
            accumulatedInputTokens = 0;
            accumulatedOutputTokens = 0;
            effectiveModel = null;
            try {
            int iteration = 0;
            while (iteration < maxIterations) {
                iteration++;
                log.debug("Agentic loop iteration {}/{}", iteration, maxIterations);

                // Build model_params via the shared merge helper. Shared with
                // streamGenerate() so both paths apply identical escape-hatch
                // / typed-setter / annotation-default precedence (issue #1019).
                Map<String, Object> modelParams = buildMergedModelParams();
                // Pass output_schema for structured output (provider handles vendor-specific conversion).
                // Buffered-path only — streaming does not currently parse structured output.
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

                // Accumulate LLM token usage from this iteration's response
                // (issue #1227). Null/missing-safe: a response without
                // _mesh_usage contributes nothing.
                accumulateUsage(response);

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

                log.info("LLM requested {} tool calls", toolCalls.size());

                if (parallelToolCalls && toolCalls.size() > 1) {
                    // Parallel execution via CompletableFuture.
                    // Issue #1164 MED-4: wrap each task with TraceContext so
                    // parallel tool calls carry trace headers AND propagated
                    // headers (X-Mesh-Job-Id, X-Mesh-Timeout, allowlisted auth)
                    // on outbound calls — matching the sequential branch, which
                    // runs on the caller thread and inherits them implicitly.
                    log.info("Executing {} tool calls in parallel", toolCalls.size());
                    List<CompletableFuture<Map<String, Object>>> futures = new ArrayList<>();

                    for (Map<String, Object> toolCall : toolCalls) {
                        ParsedToolCall parsed = parseToolCall(toolCall);
                        futures.add(CompletableFuture.supplyAsync(
                            TraceContext.wrapSupplier(() -> buildToolResultMessage(parsed))));
                    }

                    // Wait for all tools to complete and add results
                    CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
                    for (CompletableFuture<Map<String, Object>> future : futures) {
                        llmMessages.add(future.join());
                    }
                } else {
                    // Sequential execution (default)
                    for (Map<String, Object> toolCall : toolCalls) {
                        ParsedToolCall parsed = parseToolCall(toolCall);
                        llmMessages.add(buildToolResultMessage(parsed));
                    }
                }
            }

            log.warn("Max iterations ({}) reached for LLM agent {}", maxIterations, functionId);
            return extractLastAssistantContent(llmMessages);
            } finally {
                // Publish accumulated token usage to the per-thread sink so
                // ExecutionTracer.endSpan can stamp the CONSUMER span (parity
                // with Python's set_llm_metadata → end_execution). Only emit
                // when usage was actually reported, avoiding zero-spam for
                // providers/tools that report none.
                if (accumulatedInputTokens > 0 || accumulatedOutputTokens > 0) {
                    String providerName = provider.provider() != null ? provider.provider() : "";
                    TraceContext.setLlmMetadata(providerName, effectiveModel,
                        accumulatedInputTokens, accumulatedOutputTokens);
                } else {
                    // No usage reported: clear the per-thread sink so stale
                    // llm_* metadata from a prior call on a pooled thread can't
                    // leak into a later span. Always leave the sink in a known
                    // state after the loop — set when accumulated, cleared otherwise.
                    TraceContext.clearLlmMetadata();
                }
            }
        }

        /**
         * Accumulate {@code _mesh_usage} token counts from a provider response into the
         * per-call running totals (issue #1227). Null/missing-safe.
         */
        private void accumulateUsage(Map<String, Object> response) {
            Map<String, Object> usage = extractUsage(response);
            if (usage == null) {
                return;
            }
            accumulatedInputTokens += toTokenCount(usage.get("prompt_tokens"));
            accumulatedOutputTokens += toTokenCount(usage.get("completion_tokens"));
            Object model = usage.get("model");
            if (model instanceof String s && !s.isBlank()) {
                effectiveModel = s;
            }
        }

        private Map<String, Object> buildToolResultMessage(ParsedToolCall parsed) {
            log.debug("Executing tool: {} with args: {}", parsed.toolName(), parsed.toolArgs());
            String toolResult = executeToolCall(parsed.toolName(), parsed.toolArgs());
            return Map.of(
                "role", "tool",
                "tool_call_id", parsed.toolId(),
                "content", toolResult
            );
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
         * Resolve media URIs and attach as multipart content to the last user message.
         *
         * <p>Finds the last user message in the list and converts it from a plain
         * text message to a multipart message with text + image content blocks.
         * Uses MediaStore to fetch media data and MediaResolver to format for the
         * provider's vendor format (OpenAI-compatible by default for mesh delegation).
         *
         * @param llmMessages The mutable list of LLM messages
         * @param provider    The LLM provider endpoint info
         */
        private void attachMediaToLastUserMessage(
                List<Map<String, Object>> llmMessages,
                ProviderEndpoint provider) {

            if (mediaStore == null) {
                log.warn("Media URIs provided but MediaStore is not configured — ignoring {} media item(s)",
                    mediaUris.size());
                return;
            }

            // Resolve each URI to an image content block
            String vendor = provider.provider() != null ? provider.provider() : "openai";
            List<Map<String, Object>> mediaParts = resolveMediaUris(vendor);
            if (mediaParts.isEmpty()) {
                return;
            }

            log.info("Resolved {} media item(s) for user message", mediaParts.size());

            // Find the last user message and convert to multipart
            for (int i = llmMessages.size() - 1; i >= 0; i--) {
                Map<String, Object> msg = llmMessages.get(i);
                if ("user".equals(msg.get("role"))) {
                    Object existingContent = msg.get("content");

                    List<Object> multipartContent = new ArrayList<>();
                    if (existingContent instanceof String text) {
                        multipartContent.add(Map.of("type", "text", "text", text));
                    } else if (existingContent instanceof List<?> existingList) {
                        @SuppressWarnings("unchecked")
                        List<Object> typedList = (List<Object>) existingList;
                        multipartContent.addAll(typedList);
                    }
                    multipartContent.addAll(mediaParts);

                    // Replace with mutable map (Map.of() returns immutable)
                    Map<String, Object> updatedMsg = new LinkedHashMap<>();
                    updatedMsg.put("role", "user");
                    updatedMsg.put("content", multipartContent);
                    llmMessages.set(i, updatedMsg);
                    break;
                }
            }
        }

        /**
         * Resolve media URIs to provider-native image content blocks.
         *
         * @param vendor The LLM vendor name for formatting
         * @return List of image content blocks (empty if all resolutions fail)
         */
        private List<Map<String, Object>> resolveMediaUris(String vendor) {
            List<Map<String, Object>> parts = new ArrayList<>();

            for (String uri : mediaUris) {
                try {
                    MediaFetchResult fetchResult = mediaStore.fetch(uri);
                    String base64Data = Base64.getEncoder().encodeToString(fetchResult.data());
                    String mimeType = fetchResult.mimeType() != null ? fetchResult.mimeType() : "application/octet-stream";

                    Map<String, Object> imageBlock = MediaResolver.formatForVendor(base64Data, mimeType, vendor);
                    parts.add(imageBlock);

                    log.debug("Resolved media URI: uri={}, mimeType={}, size={}",
                        uri, mimeType, fetchResult.data().length);
                } catch (Exception e) {
                    log.error("Failed to resolve media URI {}: {}", uri, e.getMessage());
                }
            }

            return parts;
        }

        /**
         * Build JSON schema from the response type class.
         *
         * <p>Routes through the shared victools generator ({@link MeshSchemaSupport#generator()})
         * — the same generator used for tool input schemas — so the response-model
         * schema sent to LLM providers via {@code model_params.output_schema} is
         * richly nested (full {@code properties}/{@code items}/{@code anyOf} expansion),
         * not the shallow hand-rolled shape. The victools output carries
         * {@code $defs}/{@code $ref}; {@link MeshSchemaSupport#inlineRefs(Map)}
         * inlines them so every vendor — including Anthropic hint mode — receives a
         * self-contained schema.
         *
         * @param type the response type class
         * @return JSON schema as a Map, or null if schema cannot be built
         */
        private Map<String, Object> buildJsonSchema(Class<?> type) {
            JsonNode node = MeshSchemaSupport.generator().generateSchema(type);
            // Rewrite victools' bare "#" root self-reference into "#/$defs/<TypeName>"
            // (mirrors the tool-schema path) so inlineRefs' cycle guard can collapse
            // it to a bounded placeholder instead of leaving a non-self-contained "#".
            node = MeshSchemaSupport.rewriteRootSelfRefs(node, type);
            Map<String, Object> schema =
                objectMapper.convertValue(node, new TypeReference<Map<String, Object>>() {});
            // Issue #1230: close the structured-output schema — strip the stale
            // `anyOf:[{type:null}, X]` nullable branch from REQUIRED record
            // components so the LLM can't satisfy "required" by returning null
            // (which silently drops the field). Optional<T> fields are left out of
            // `required` upstream and stay nullable (escape hatch intact).
            return MeshSchemaSupport.stripRequiredNullBranches(
                MeshSchemaSupport.inlineRefs(schema));
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

            // Enrich with _mesh_endpoint for provider-side tool execution
            if (tool.available() && tool.endpoint() != null && !tool.endpoint().isEmpty()) {
                functionDef.put("_mesh_endpoint", tool.endpoint());
            }

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

    /**
     * Extract the provider's {@code _mesh_usage} token-usage object from a response.
     *
     * <p>The object — {@code {model, prompt_tokens, completion_tokens}} — may appear at
     * the response top level OR inside the nested {@code content[0].text} JSON envelope
     * that {@link #extractContent}/{@link #extractToolCalls} already unwrap. Mirrors that
     * same unwrap path. Returns {@code null} when no usage is present (non-LLM tools or
     * providers that don't report usage) so callers contribute nothing.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> extractUsage(Map<String, Object> response) {
        Object topLevel = response.get("_mesh_usage");
        if (topLevel instanceof Map<?, ?> m) {
            return (Map<String, Object>) m;
        }

        Object content = response.get("content");
        if (content instanceof List<?> contentList && !contentList.isEmpty()) {
            Object first = contentList.get(0);
            if (first instanceof Map<?, ?> block) {
                Object text = block.get("text");
                if (text instanceof String textStr && textStr.trim().startsWith("{")) {
                    try {
                        Map<String, Object> parsed = objectMapper.readValue(textStr, Map.class);
                        Object nested = parsed.get("_mesh_usage");
                        if (nested instanceof Map<?, ?> nm) {
                            return (Map<String, Object>) nm;
                        }
                    } catch (JacksonException e) {
                        log.trace("Failed to parse nested JSON for _mesh_usage: {}", e.getMessage());
                    }
                }
            }
        }

        return null;
    }

    /** Coerce a token-count field (Number or numeric String) to a long; 0 if missing/unparseable. */
    private static long toTokenCount(Object value) {
        if (value instanceof Number n) {
            return n.longValue();
        }
        if (value instanceof String s && !s.isBlank()) {
            try {
                return Long.parseLong(s.trim());
            } catch (NumberFormatException ignored) {
                return 0L;
            }
        }
        return 0L;
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
    private record ParsedToolCall(String toolId, String toolName, Map<String, Object> toolArgs) {}

    @SuppressWarnings("unchecked")
    private ParsedToolCall parseToolCall(Map<String, Object> toolCall) {
        String toolId = (String) toolCall.get("id");
        String toolName;
        Map<String, Object> toolArgs;

        Map<String, Object> function = (Map<String, Object>) toolCall.get("function");
        if (function != null) {
            toolName = (String) function.get("name");
            Object argsObj = function.get("arguments");
            toolArgs = parseToolArguments(argsObj);
        } else {
            toolName = (String) toolCall.get("name");
            Object argsObj = toolCall.get("arguments");
            toolArgs = parseToolArguments(argsObj);
        }

        return new ParsedToolCall(toolId, toolName, toolArgs);
    }

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
    // Package-private static for tests (issue #1164 LOW).
    static String buildErrorResponse(String errorType, String toolName, String message) {
        // Issue #1164 LOW: serialize with Jackson — the previous hand-rolled
        // escaping missed newlines/control chars, producing invalid JSON for
        // exception messages containing them.
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("type", errorType);
        error.put("tool", toolName);
        error.put("message", message != null ? message : "Unknown error");
        Map<String, Object> wrapper = new LinkedHashMap<>();
        wrapper.put("error", error);
        try {
            return objectMapper.writeValueAsString(wrapper);
        } catch (Exception e) {
            log.warn("Failed to serialize error response ({} / {}): {}", errorType, toolName, e.getMessage());
            return "{\"error\":{\"type\":\"serialization_error\",\"tool\":\"unknown\","
                + "\"message\":\"failed to serialize error response\"}}";
        }
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
