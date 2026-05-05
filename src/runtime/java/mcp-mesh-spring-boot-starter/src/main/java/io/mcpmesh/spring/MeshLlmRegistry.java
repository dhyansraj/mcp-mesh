package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for @MeshLlm annotated methods.
 *
 * <p>Stores configuration extracted from @MeshLlm annotations for later use
 * during method invocation when MeshLlmAgent needs to be injected.
 */
public class MeshLlmRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmRegistry.class);

    /**
     * Configuration extracted from @MeshLlm annotation.
     */
    public record LlmConfig(
        String functionId,
        Selector providerSelector,  // For mesh delegation
        int maxIterations,
        String systemPrompt,
        String contextParam,
        Selector[] filters,
        int filterMode,
        int maxTokens,
        double temperature,
        boolean parallelToolCalls
    ) {}

    // Registry: functionId -> LlmConfig
    private final Map<String, LlmConfig> configsByFunctionId = new ConcurrentHashMap<>();

    // Registry: method signature -> LlmConfig
    private final Map<String, LlmConfig> configsByMethod = new ConcurrentHashMap<>();

    /**
     * Register an @MeshLlm annotated method.
     *
     * @param targetClass The class containing the method
     * @param method      The annotated method
     * @param annotation  The @MeshLlm annotation
     */
    public void register(Class<?> targetClass, Method method, MeshLlm annotation) {
        String functionId = targetClass.getName() + "." + method.getName();
        String methodKey = getMethodKey(method);

        // v2: direct LLM mode is gone — every @MeshLlm consumer must point
        // providerSelector at a registered @MeshLlmProvider. An empty selector
        // would silently skip llmProvider enrichment in MeshAutoConfiguration
        // and the consumer would fail at first generate() with no upstream
        // bound. Catch the misconfig at registration time so the failure mode
        // is loud and actionable.
        Selector selector = annotation.providerSelector();
        if (selector == null || selector.capability() == null || selector.capability().isEmpty()) {
            throw new IllegalStateException(
                "@MeshLlm on " + functionId + " requires providerSelector with a non-empty capability(). "
                + "Direct LLM mode was removed in v2 — every consumer must specify a provider via "
                + "@Selector(capability=\"llm\", tags={\"+claude\"}). "
                + "See docs/java/llm/index.md for the migration."
            );
        }

        LlmConfig config = new LlmConfig(
            functionId,
            selector,
            annotation.maxIterations(),
            annotation.systemPrompt(),
            annotation.contextParam(),
            annotation.filter(),
            annotation.filterMode().ordinal(),
            annotation.maxTokens(),
            annotation.temperature(),
            annotation.parallelToolCalls()
        );

        configsByFunctionId.put(functionId, config);
        configsByMethod.put(methodKey, config);

        log.info("Registered @MeshLlm: {} (mesh-delegated)", functionId);
    }

    /**
     * Get LLM config by function ID.
     */
    public LlmConfig getByFunctionId(String functionId) {
        return configsByFunctionId.get(functionId);
    }

    /**
     * Get LLM config by method.
     */
    public LlmConfig getByMethod(Method method) {
        return configsByMethod.get(getMethodKey(method));
    }

    /**
     * Check if a method has @MeshLlm configuration.
     */
    public boolean hasConfig(Method method) {
        return configsByMethod.containsKey(getMethodKey(method));
    }

    /**
     * Get all registered configurations.
     */
    public Map<String, LlmConfig> getAllConfigs() {
        return Map.copyOf(configsByFunctionId);
    }

    private String getMethodKey(Method method) {
        return method.getDeclaringClass().getName() + "#" + method.getName();
    }
}
