package io.mcpmesh.ai;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshLlmProvider;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.ai.handlers.LlmProviderHandler;
import io.mcpmesh.ai.handlers.LlmProviderHandler.OutputSchema;
import io.mcpmesh.ai.handlers.LlmProviderHandler.ToolDefinition;
import io.mcpmesh.ai.handlers.LlmProviderHandlerRegistry;
import io.mcpmesh.core.AgentSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.aop.support.AopUtils;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationContextAware;
import org.springframework.core.annotation.AnnotationUtils;

import java.util.*;

/**
 * Processes @MeshLlmProvider annotations and registers LLM capabilities.
 *
 * <p>When a class is annotated with @MeshLlmProvider, this processor:
 * <ol>
 *   <li>Extracts the model configuration</li>
 *   <li>Creates a Spring AI ChatClient for the model</li>
 *   <li>Registers an LLM tool capability with the mesh (via llm_provider field)</li>
 *   <li>Handles incoming LLM generation requests</li>
 * </ol>
 *
 * <h2>MCP Endpoint</h2>
 * <p>The provider exposes an MCP tool with the following interface:
 * <pre>
 * {
 *   "name": "llm_generate",
 *   "description": "Generate LLM response",
 *   "parameters": {
 *     "messages": [{"role": "string", "content": "string"}],
 *     "tools": [...optional tool definitions...],
 *     "max_tokens": 4096,
 *     "temperature": 0.7
 *   }
 * }
 * </pre>
 *
 * <h2>Heartbeat Registration</h2>
 * <p>The tool spec includes an {@code llm_provider} JSON field that tells the
 * Rust core this is a provider (not a consumer). Format:
 * <pre>
 * {
 *   "capability": "llm",
 *   "tags": ["llm", "claude", "anthropic", "provider"],
 *   "version": "1.0.0",
 *   "namespace": "default"
 * }
 * </pre>
 */
public class MeshLlmProviderProcessor implements BeanPostProcessor, ApplicationContextAware {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmProviderProcessor.class);
    private static final ObjectMapper objectMapper = MeshObjectMappers.create();

    /** Default tool name for LLM provider (matches Python/TypeScript SDKs). */
    public static final String LLM_TOOL_NAME = "llm_generate";

    private ApplicationContext applicationContext;
    private final List<LlmProviderConfig> registeredProviders = new ArrayList<>();
    private final List<AgentSpec.ToolSpec> toolSpecs = new ArrayList<>();

    @Override
    public void setApplicationContext(ApplicationContext applicationContext) throws BeansException {
        this.applicationContext = applicationContext;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        // Get the target class (unwrap CGLIB proxies)
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        // Check for @MeshLlmProvider annotation (handle meta-annotations too)
        MeshLlmProvider providerAnnotation = AnnotationUtils.findAnnotation(targetClass, MeshLlmProvider.class);
        if (providerAnnotation != null) {
            log.info("Found @MeshLlmProvider on bean '{}' (class: {})", beanName, targetClass.getName());
            processLlmProvider(targetClass, providerAnnotation);
        }

        return bean;
    }

    private void processLlmProvider(Class<?> beanClass, MeshLlmProvider annotation) {
        String model = annotation.model();
        String capability = annotation.capability();
        String[] tags = annotation.tags();
        String version = annotation.version();

        log.info("Processing @MeshLlmProvider: model={}, capability={}", model, capability);

        // Parse model string (provider/model-name)
        String[] modelParts = model.split("/", 2);
        String provider = modelParts.length > 1 ? modelParts[0] : model;
        String modelName = modelParts.length > 1 ? modelParts[1] : model;

        // Create config
        LlmProviderConfig config = new LlmProviderConfig(
            capability,
            provider,
            modelName,
            List.of(tags),
            version
        );

        registeredProviders.add(config);

        // Create ToolSpec for heartbeat registration
        AgentSpec.ToolSpec toolSpec = createToolSpec(config);
        toolSpecs.add(toolSpec);

        log.info("Registered LLM provider: {} ({}) with tags {} - tool spec created for heartbeat",
            capability, model, Arrays.toString(tags));
    }

    /**
     * Create a ToolSpec for the LLM provider.
     *
     * <p>This tool spec includes the {@code llm_provider} field that tells the
     * Rust core to treat this as a provider (discoverable by consumers).
     *
     * @param config The provider configuration
     * @return ToolSpec ready for heartbeat registration
     */
    private AgentSpec.ToolSpec createToolSpec(LlmProviderConfig config) {
        AgentSpec.ToolSpec spec = new AgentSpec.ToolSpec();

        // Tool name - used for MCP tool invocation
        spec.setFunctionName(LLM_TOOL_NAME);

        // Capability - used for mesh discovery
        spec.setCapability(config.capability());

        // Description for tool listing
        spec.setDescription("Generate LLM response using " + config.provider() + "/" + config.modelName());

        // Version from annotation
        spec.setVersion(config.version());

        // Tags for filtering
        spec.setTags(new ArrayList<>(config.tags()));

        // Input schema for the LLM request
        spec.setInputSchema(buildInputSchemaJson());

        // LLM provider spec - this is the key field that tells Rust core
        // this is a provider (not a consumer)
        spec.setLlmProvider(buildLlmProviderJson(config));

        return spec;
    }

    /**
     * Build the llm_provider JSON for heartbeat.
     * Format matches Python/TypeScript SDKs.
     */
    private String buildLlmProviderJson(LlmProviderConfig config) {
        try {
            Map<String, Object> providerData = new LinkedHashMap<>();
            providerData.put("capability", config.capability());
            providerData.put("tags", config.tags());
            providerData.put("version", config.version());
            providerData.put("namespace", "default");
            return objectMapper.writeValueAsString(providerData);
        } catch (JacksonException e) {
            log.error("Failed to serialize llm_provider JSON", e);
            return "{}";
        }
    }

    /**
     * Build the input schema JSON for the LLM tool.
     */
    private String buildInputSchemaJson() {
        try {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");

            Map<String, Object> properties = new LinkedHashMap<>();

            // messages parameter (required)
            Map<String, Object> messagesSchema = new LinkedHashMap<>();
            messagesSchema.put("type", "array");
            messagesSchema.put("description", "Conversation messages");
            Map<String, Object> messageItem = new LinkedHashMap<>();
            messageItem.put("type", "object");
            Map<String, Object> messageProps = new LinkedHashMap<>();
            messageProps.put("role", Map.of("type", "string", "enum", List.of("system", "user", "assistant", "tool")));
            messageProps.put("content", Map.of("type", "string"));
            messageItem.put("properties", messageProps);
            messageItem.put("required", List.of("role", "content"));
            messagesSchema.put("items", messageItem);
            properties.put("messages", messagesSchema);

            // tools parameter (optional)
            Map<String, Object> toolsSchema = new LinkedHashMap<>();
            toolsSchema.put("type", "array");
            toolsSchema.put("description", "Available tools (optional)");
            properties.put("tools", toolsSchema);

            // max_tokens parameter
            properties.put("max_tokens", Map.of("type", "integer", "default", 4096, "description", "Maximum tokens to generate"));

            // temperature parameter
            properties.put("temperature", Map.of("type", "number", "default", 0.7, "description", "Sampling temperature"));

            schema.put("properties", properties);
            schema.put("required", List.of("messages"));

            return objectMapper.writeValueAsString(schema);
        } catch (JacksonException e) {
            log.error("Failed to serialize input schema", e);
            return "{}";
        }
    }

    /**
     * Get tool specs for registered LLM providers.
     *
     * <p>Called by MeshAutoConfiguration to include in agent registration.
     *
     * @return List of tool specs with llm_provider field set
     */
    public List<AgentSpec.ToolSpec> getToolSpecs() {
        return new ArrayList<>(toolSpecs);
    }

    /**
     * Check if any LLM providers are registered.
     */
    public boolean hasProviders() {
        return !registeredProviders.isEmpty();
    }

    /**
     * Get registered LLM provider configurations.
     */
    public List<LlmProviderConfig> getRegisteredProviders() {
        return new ArrayList<>(registeredProviders);
    }

    /**
     * Create tool wrappers for MCP server registration.
     *
     * <p>Called by MeshAutoConfiguration to get handlers that can process
     * incoming MCP calls for the LLM tool.
     *
     * @return List of tool wrappers ready for MeshToolWrapperRegistry
     */
    public List<LlmProviderToolWrapper> createToolWrappers() {
        List<LlmProviderToolWrapper> wrappers = new ArrayList<>();

        for (LlmProviderConfig config : registeredProviders) {
            LlmProviderToolWrapper wrapper = new LlmProviderToolWrapper(
                config.capability(),
                "Generate LLM response using " + config.provider() + "/" + config.modelName(),
                config.version(),
                config.tags(),
                this
            );
            wrappers.add(wrapper);
        }

        return wrappers;
    }

    /**
     * Handle an LLM generation request.
     *
     * <p>For mesh delegation mode:
     * <ol>
     *   <li>Receives request with messages, tools, and optional output_schema</li>
     *   <li>Formats system prompt with structured output instructions (vendor-specific)</li>
     *   <li>Calls LLM with tools (without auto-executing)</li>
     *   <li>Returns tool_calls to caller for execution</li>
     * </ol>
     *
     * @param capability The capability name
     * @param params     Request parameters (messages, tools, output_schema, etc.)
     * @return Response map with content and optional tool_calls
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> handleGenerateRequest(String capability, Map<String, Object> params) {
        log.debug("handleGenerateRequest called with capability: {}", capability);

        // Find provider config
        LlmProviderConfig config = findProvider(capability);
        if (config == null) {
            throw new IllegalArgumentException("No LLM provider for capability: " + capability);
        }

        // Get Spring AI LLM provider
        SpringAiLlmProvider llmProvider;
        try {
            llmProvider = applicationContext.getBean(SpringAiLlmProvider.class);
        } catch (BeansException e) {
            throw new IllegalStateException("SpringAiLlmProvider not available", e);
        }

        // Handle both direct format {"messages": [...]} and wrapped format {"request": {"messages": [...]}}
        // The Python SDK sends wrapped format via mesh delegation
        Map<String, Object> requestData = params;
        if (params.containsKey("request") && params.get("request") instanceof Map) {
            log.debug("Unwrapping 'request' envelope from mesh delegation");
            requestData = (Map<String, Object>) params.get("request");
        }

        // Extract request parameters
        List<Map<String, Object>> messages = (List<Map<String, Object>>) requestData.get("messages");
        List<Map<String, Object>> tools = (List<Map<String, Object>>) requestData.get("tools");

        // Extract model_params (contains output_schema for mesh delegation)
        Map<String, Object> modelParams = (Map<String, Object>) requestData.get("model_params");

        // Extract output_schema from model_params (mesh delegation) or directly (direct mode)
        Map<String, Object> outputSchemaData = null;
        String outputTypeName = null;
        if (modelParams != null) {
            outputSchemaData = (Map<String, Object>) modelParams.get("output_schema");
            outputTypeName = (String) modelParams.get("output_type_name");
        }
        // Also check direct location for backwards compatibility
        if (outputSchemaData == null) {
            outputSchemaData = (Map<String, Object>) requestData.get("output_schema");
        }

        log.debug("Generating response with provider={}, messageCount={}, toolCount={}, hasOutputSchema={}, outputTypeName={}",
            config.provider(),
            messages != null ? messages.size() : 0,
            tools != null ? tools.size() : 0,
            outputSchemaData != null,
            outputTypeName);

        // Get vendor-specific handler
        LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler(config.provider());
        log.debug("Using handler: {}", handler.getClass().getSimpleName());

        // Get ChatModel for this provider
        ChatModel model = llmProvider.getModelForProvider(config.provider());

        // Build response
        Map<String, Object> response = new LinkedHashMap<>();

        try {
            if (messages == null || messages.isEmpty()) {
                // Fallback to simple generation if no messages
                String content = llmProvider.generate(config.provider(), "", "Hello");
                response.put("content", content);
                response.put("tool_calls", List.of());
            } else if (tools == null || tools.isEmpty()) {
                // No tools - use simple message generation with optional structured output
                String content;
                if (outputSchemaData != null) {
                    // Format system prompt with output schema
                    OutputSchema outputSchema = parseOutputSchema(outputSchemaData, outputTypeName);
                    content = generateWithOutputSchema(handler, model, messages, outputSchema);
                } else {
                    content = llmProvider.generateWithMessages(config.provider(), messages);
                }
                response.put("content", content);
                response.put("tool_calls", List.of());
            } else {
                // Tools present - use native tool calling without auto-execution
                log.debug("Using tool-aware generation with {} tools (no auto-execution)", tools.size());

                // Convert tool definitions to handler format
                List<ToolDefinition> toolDefs = parseToolDefinitions(tools);

                // Parse output schema if present
                OutputSchema outputSchema = outputSchemaData != null ?
                    parseOutputSchema(outputSchemaData, outputTypeName) : null;

                // Generate with tools - provider does NOT execute tools
                // Tool execution happens on the consumer (caller) side
                LlmProviderHandler.LlmResponse llmResponse = generateWithToolsNoExecution(
                    handler, model, messages, toolDefs, outputSchema
                );

                response.put("content", llmResponse.content());
                response.put("tool_calls", convertToolCalls(llmResponse.toolCalls()));
            }
        } catch (Exception e) {
            log.error("LLM generation failed: {}", e.getMessage(), e);
            throw new RuntimeException("LLM generation failed", e);
        }

        response.put("model", config.provider() + "/" + config.modelName());
        return response;
    }

    /**
     * Parse tool definitions from OpenAI function calling format.
     */
    @SuppressWarnings("unchecked")
    private List<ToolDefinition> parseToolDefinitions(List<Map<String, Object>> tools) {
        List<ToolDefinition> toolDefs = new ArrayList<>();
        for (Map<String, Object> tool : tools) {
            // Handle OpenAI format: {"type": "function", "function": {...}}
            String type = (String) tool.get("type");
            if ("function".equals(type)) {
                Map<String, Object> function = (Map<String, Object>) tool.get("function");
                if (function != null) {
                    String name = (String) function.get("name");
                    String description = (String) function.get("description");
                    Map<String, Object> parameters = (Map<String, Object>) function.get("parameters");
                    toolDefs.add(new ToolDefinition(name, description, parameters));
                }
            } else {
                // Handle direct format: {"name": "...", "description": "...", "parameters": {...}}
                String name = (String) tool.get("name");
                String description = (String) tool.get("description");
                Map<String, Object> parameters = (Map<String, Object>) tool.get("parameters");
                if (name != null) {
                    toolDefs.add(new ToolDefinition(name, description, parameters));
                }
            }
        }
        return toolDefs;
    }

    /**
     * Parse output schema from request.
     *
     * @param outputSchemaData The schema data map
     * @param outputTypeName Optional type name from model_params (takes precedence over name in schema)
     */
    @SuppressWarnings("unchecked")
    private OutputSchema parseOutputSchema(Map<String, Object> outputSchemaData, String outputTypeName) {
        // Use outputTypeName if provided, otherwise fall back to name in schema data
        String name = outputTypeName != null ? outputTypeName :
            (String) outputSchemaData.getOrDefault("name", "Response");
        Map<String, Object> schema = (Map<String, Object>) outputSchemaData.get("schema");
        if (schema == null) {
            // Schema might be at top level
            schema = new LinkedHashMap<>(outputSchemaData);
            schema.remove("name");
        }
        return OutputSchema.fromSchema(name, schema);
    }

    /**
     * Generate response with output schema (no tools).
     *
     * <p>Delegates to handler's generateWithTools() with empty tools list
     * to leverage the handler's proper response_format support.
     */
    private String generateWithOutputSchema(
            LlmProviderHandler handler,
            ChatModel model,
            List<Map<String, Object>> messages,
            OutputSchema outputSchema) {

        // Delegate to handler which has proper vendor-specific response_format
        // Pass empty tools list and null executor (no tool execution needed)
        LlmProviderHandler.LlmResponse response = handler.generateWithTools(
            model, messages, List.of(), null, outputSchema, Map.of()
        );

        return response.content();
    }

    /**
     * Generate with tools but WITHOUT executing them.
     *
     * <p>This is the key method for mesh delegation:
     * <ul>
     *   <li>Provider calls LLM with tool schemas</li>
     *   <li>LLM returns tool_calls</li>
     *   <li>Provider returns tool_calls to caller (no execution)</li>
     *   <li>Caller (consumer) executes tools and sends results back</li>
     * </ul>
     *
     * <p>Delegates to the handler's generateWithTools() which has the proper
     * vendor-specific options (response_format for OpenAI/Gemini structured output).
     */
    private LlmProviderHandler.LlmResponse generateWithToolsNoExecution(
            LlmProviderHandler handler,
            ChatModel model,
            List<Map<String, Object>> messages,
            List<ToolDefinition> toolDefs,
            OutputSchema outputSchema) {

        // Delegate to handler which has proper vendor-specific options (response_format for OpenAI/Gemini)
        // The handler's generateWithTools() already handles:
        // - Formatting system prompt
        // - Creating tool callbacks with proper schemas
        // - Applying response_format for structured output (OpenAI/Gemini)
        // - Tool execution callback (we pass null since we don't execute here)
        //
        // Passing null for toolExecutor tells the handler to NOT execute tools,
        // just return the tool_calls in the response.

        log.debug("Delegating to handler.generateWithTools() with {} tools (no execution)", toolDefs.size());

        return handler.generateWithTools(model, messages, toolDefs, null, outputSchema, Map.of());
    }
    /**
     * Convert tool calls to response format (OpenAI style).
     */
    private List<Map<String, Object>> convertToolCalls(List<LlmProviderHandler.ToolCall> toolCalls) {
        List<Map<String, Object>> result = new ArrayList<>();

        for (LlmProviderHandler.ToolCall tc : toolCalls) {
            Map<String, Object> toolCall = new LinkedHashMap<>();
            toolCall.put("id", tc.id());
            toolCall.put("type", "function");

            Map<String, Object> function = new LinkedHashMap<>();
            function.put("name", tc.name());
            function.put("arguments", tc.arguments());
            toolCall.put("function", function);

            result.add(toolCall);
        }

        return result;
    }

    /**
     * Build tool specification for MCP registration.
     */
    public Map<String, Object> buildToolSpec(LlmProviderConfig config) {
        Map<String, Object> spec = new LinkedHashMap<>();
        spec.put("name", "llm_generate");
        spec.put("description", "Generate LLM response using " + config.provider() + "/" + config.modelName());

        Map<String, Object> parameters = new LinkedHashMap<>();
        parameters.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();

        // messages parameter
        Map<String, Object> messagesSchema = new LinkedHashMap<>();
        messagesSchema.put("type", "array");
        messagesSchema.put("description", "Conversation messages");
        Map<String, Object> messageItem = new LinkedHashMap<>();
        messageItem.put("type", "object");
        Map<String, Object> messageProps = new LinkedHashMap<>();
        messageProps.put("role", Map.of("type", "string", "enum", List.of("system", "user", "assistant", "tool")));
        messageProps.put("content", Map.of("type", "string"));
        messageItem.put("properties", messageProps);
        messagesSchema.put("items", messageItem);
        properties.put("messages", messagesSchema);

        // tools parameter (optional)
        Map<String, Object> toolsSchema = new LinkedHashMap<>();
        toolsSchema.put("type", "array");
        toolsSchema.put("description", "Available tools (optional)");
        properties.put("tools", toolsSchema);

        // max_tokens parameter
        properties.put("max_tokens", Map.of("type", "integer", "default", 4096));

        // temperature parameter
        properties.put("temperature", Map.of("type", "number", "default", 0.7));

        parameters.put("properties", properties);
        parameters.put("required", List.of("messages"));

        spec.put("parameters", parameters);

        return spec;
    }

    private LlmProviderConfig findProvider(String capability) {
        return registeredProviders.stream()
            .filter(p -> p.capability().equals(capability))
            .findFirst()
            .orElse(null);
    }

    private String extractSystemPrompt(List<Map<String, Object>> messages) {
        if (messages == null) return "";

        return messages.stream()
            .filter(m -> "system".equals(m.get("role")))
            .map(m -> (String) m.get("content"))
            .filter(Objects::nonNull)
            .findFirst()
            .orElse("");
    }

    private String extractUserPrompt(List<Map<String, Object>> messages) {
        if (messages == null) return "";

        // Get the last user message
        StringBuilder prompt = new StringBuilder();
        for (int i = messages.size() - 1; i >= 0; i--) {
            Map<String, Object> msg = messages.get(i);
            if ("user".equals(msg.get("role"))) {
                String content = (String) msg.get("content");
                if (content != null) {
                    prompt.insert(0, content);
                }
                break;
            }
        }

        // Include assistant/tool history if present (for multi-turn)
        return prompt.toString();
    }

    /**
     * Configuration for a registered LLM provider.
     */
    public record LlmProviderConfig(
        String capability,
        String provider,
        String modelName,
        List<String> tags,
        String version
    ) {}
}
