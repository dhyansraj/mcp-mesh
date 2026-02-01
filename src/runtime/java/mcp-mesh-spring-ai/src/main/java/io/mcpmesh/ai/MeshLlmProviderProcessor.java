package io.mcpmesh.ai;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshLlmProvider;
import io.mcpmesh.core.AgentSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
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
    private static final ObjectMapper objectMapper = new ObjectMapper();

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
     * @param capability The capability name
     * @param params     Request parameters (messages, tools, etc.)
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

        log.debug("Generating response with provider={}, messageCount={}", config.provider(),
            messages != null ? messages.size() : 0);

        // Generate response with full message history
        String content;
        try {
            if (messages != null && !messages.isEmpty()) {
                // Use full message history for multi-turn conversations
                content = llmProvider.generateWithMessages(config.provider(), messages);
            } else {
                // Fallback to simple generation if no messages
                content = llmProvider.generate(config.provider(), "", "Hello");
            }
        } catch (Exception e) {
            log.error("LLM generation failed: {}", e.getMessage());
            throw new RuntimeException("LLM generation failed", e);
        }

        // Build response
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("content", content);
        response.put("model", config.provider() + "/" + config.modelName());

        // Note: Tool calling is not yet implemented in Spring AI direct mode
        // For now, we return just the text response
        response.put("tool_calls", List.of());

        return response;
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
