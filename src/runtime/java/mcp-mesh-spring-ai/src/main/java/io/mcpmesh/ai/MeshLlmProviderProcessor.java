package io.mcpmesh.ai;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshLlmProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationContextAware;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Processes @MeshLlmProvider annotations and registers LLM capabilities.
 *
 * <p>When a class is annotated with @MeshLlmProvider, this processor:
 * <ol>
 *   <li>Extracts the model configuration</li>
 *   <li>Creates a Spring AI ChatClient for the model</li>
 *   <li>Registers an LLM tool capability with the mesh</li>
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
 */
@Component
public class MeshLlmProviderProcessor implements BeanPostProcessor, ApplicationContextAware {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmProviderProcessor.class);
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private ApplicationContext applicationContext;
    private final List<LlmProviderConfig> registeredProviders = new ArrayList<>();

    @Override
    public void setApplicationContext(ApplicationContext applicationContext) throws BeansException {
        this.applicationContext = applicationContext;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> beanClass = bean.getClass();

        // Check for @MeshLlmProvider annotation
        MeshLlmProvider providerAnnotation = beanClass.getAnnotation(MeshLlmProvider.class);
        if (providerAnnotation != null) {
            processLlmProvider(beanClass, providerAnnotation);
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

        log.info("Registered LLM provider: {} ({}) with tags {}",
            capability, model, Arrays.toString(tags));
    }

    /**
     * Get registered LLM provider configurations.
     */
    public List<LlmProviderConfig> getRegisteredProviders() {
        return new ArrayList<>(registeredProviders);
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

        // Extract request parameters
        List<Map<String, Object>> messages = (List<Map<String, Object>>) params.get("messages");
        List<Map<String, Object>> tools = (List<Map<String, Object>>) params.get("tools");

        // Build prompts from messages
        String systemPrompt = extractSystemPrompt(messages);
        String userPrompt = extractUserPrompt(messages);

        // Generate response
        String content;
        try {
            content = llmProvider.generate(config.provider(), systemPrompt, userPrompt);
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
