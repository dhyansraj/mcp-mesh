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
        String directProvider,      // For direct mode (e.g., "claude")
        Selector providerSelector,  // For mesh delegation mode
        int maxIterations,
        String systemPrompt,
        String contextParam,
        Selector[] filters,
        int filterMode,
        int maxTokens,
        double temperature
    ) {
        /**
         * Check if this is mesh delegation mode.
         */
        public boolean isMeshDelegation() {
            return directProvider == null || directProvider.isEmpty();
        }
    }

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

        LlmConfig config = new LlmConfig(
            functionId,
            annotation.provider().isEmpty() ? null : annotation.provider(),
            annotation.providerSelector(),
            annotation.maxIterations(),
            annotation.systemPrompt(),
            annotation.contextParam(),
            annotation.filter(),
            annotation.filterMode().ordinal(),
            annotation.maxTokens(),
            annotation.temperature()
        );

        configsByFunctionId.put(functionId, config);
        configsByMethod.put(methodKey, config);

        log.info("Registered @MeshLlm: {} (mode={})",
            functionId, config.isMeshDelegation() ? "mesh" : "direct:" + config.directProvider());
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
