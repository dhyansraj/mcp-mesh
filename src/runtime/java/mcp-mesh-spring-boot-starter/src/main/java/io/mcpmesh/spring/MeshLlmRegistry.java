package io.mcpmesh.spring;

import io.mcpmesh.FilterMode;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.util.Locale;
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
            resolveMaxIterations(System.getenv("MESH_LLM_MAX_ITERATIONS"), annotation.maxIterations()),
            annotation.systemPrompt(),
            annotation.contextParam(),
            annotation.filter(),
            resolveFilterModeOrdinal(System.getenv("MESH_LLM_FILTER_MODE"), annotation.filterMode()),
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

    /**
     * Resolve the effective {@code maxIterations} applying the precedence
     * ENV &gt; annotation &gt; default.
     *
     * <p>Pure function: takes the raw {@code MESH_LLM_MAX_ITERATIONS} value as a
     * parameter so it is unit-testable without mutating process env.
     *
     * @param envVal        raw value of {@code MESH_LLM_MAX_ITERATIONS} (may be null/blank)
     * @param annotationVal the annotation (or default) value to fall back to
     * @return the env value if it parses to a positive int; otherwise {@code annotationVal}
     */
    static int resolveMaxIterations(String envVal, int annotationVal) {
        if (envVal == null || envVal.isBlank()) {
            return annotationVal;
        }
        try {
            int parsed = Integer.parseInt(envVal.trim());
            if (parsed > 0) {
                return parsed;
            }
            log.warn("MESH_LLM_MAX_ITERATIONS='{}' is not positive; using {}", envVal, annotationVal);
            return annotationVal;
        } catch (NumberFormatException e) {
            log.warn("MESH_LLM_MAX_ITERATIONS='{}' is not a valid integer; using {}", envVal, annotationVal);
            return annotationVal;
        }
    }

    /**
     * Resolve the effective filter-mode ordinal applying the precedence
     * ENV &gt; annotation &gt; default.
     *
     * <p>Pure function: takes the raw {@code MESH_LLM_FILTER_MODE} value as a
     * parameter so it is unit-testable without mutating process env. Accepts the
     * wire vocabulary ({@code all}/{@code best_match}/{@code wildcard},
     * case-insensitive) — the same vocabulary emitted by MeshAutoConfiguration —
     * rather than {@link FilterMode#valueOf}.
     *
     * @param envVal        raw value of {@code MESH_LLM_FILTER_MODE} (may be null/blank)
     * @param annotationVal the annotation (or default) FilterMode to fall back to
     * @return the matching FilterMode ordinal, or {@code annotationVal.ordinal()} if unknown/blank
     */
    static int resolveFilterModeOrdinal(String envVal, FilterMode annotationVal) {
        if (envVal == null || envVal.isBlank()) {
            return annotationVal.ordinal();
        }
        switch (envVal.trim().toLowerCase(Locale.ROOT)) {
            case "all":
                return FilterMode.ALL.ordinal();
            case "best_match":
                return FilterMode.BEST_MATCH.ordinal();
            case "wildcard":
                return FilterMode.WILDCARD.ordinal();
            default:
                log.warn("MESH_LLM_FILTER_MODE='{}' is not a recognized mode "
                    + "(all|best_match|wildcard); using {}", envVal, annotationVal);
                return annotationVal.ordinal();
        }
    }
}
