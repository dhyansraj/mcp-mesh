package io.mcpmesh.spring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * Wrapper for @MeshTool annotated methods.
 *
 * <p>This wrapper is registered with the MCP Java SDK and handles:
 * <ul>
 *   <li>Mapping MCP arguments to method parameters</li>
 *   <li>Injecting McpMeshTool dependencies from cached proxies</li>
 *   <li>Injecting MeshLlmAgent from cached proxy</li>
 *   <li>Exception unwrapping</li>
 *   <li>Async method support (CompletableFuture)</li>
 * </ul>
 *
 * <p>The wrapper's internal dependency arrays are updated by heartbeat events,
 * and calls use the latest cached values (fast path, no registry lookup).
 *
 * @see MeshToolWrapperRegistry
 */
public class MeshToolWrapper {

    private static final Logger log = LoggerFactory.getLogger(MeshToolWrapper.class);
    private static final long ASYNC_TIMEOUT_SECONDS = 30;

    private final String funcId;
    private final String capability;
    private final String description;
    private final Object bean;
    private final Method method;

    // Parameter metadata
    private final List<ParamInfo> mcpParams;           // MCP-exposed parameters (with @Param)
    private final List<Integer> meshToolPositions;     // Positions of McpMeshTool params
    private final List<Integer> llmAgentPositions;     // Positions of MeshLlmAgent params
    private final Map<String, Object> inputSchema;     // JSON Schema for MCP

    // Mutable dependency arrays (updated by heartbeat)
    private final AtomicReferenceArray<McpMeshTool> injectedDeps;
    private final AtomicReferenceArray<MeshLlmAgent> injectedLlmAgents;

    // Dependency names for error messages
    private final List<String> dependencyNames;

    private final ObjectMapper objectMapper;

    /**
     * Create a wrapper for a @MeshTool annotated method.
     *
     * @param funcId         Unique function identifier (e.g., "com.example.Calc.calc")
     * @param capability     The capability name from @MeshTool
     * @param description    Description from @MeshTool
     * @param bean           The Spring bean instance
     * @param method         The method to invoke
     * @param dependencyNames Names of declared dependencies (for composite keys)
     * @param objectMapper   Jackson ObjectMapper for serialization
     */
    public MeshToolWrapper(
            String funcId,
            String capability,
            String description,
            Object bean,
            Method method,
            List<String> dependencyNames,
            ObjectMapper objectMapper) {

        this.funcId = funcId;
        this.capability = capability;
        this.description = description;
        this.bean = bean;
        this.method = method;
        this.dependencyNames = dependencyNames != null ? dependencyNames : List.of();
        this.objectMapper = objectMapper;

        // Make method accessible (for private methods)
        method.setAccessible(true);

        // Analyze parameters
        this.mcpParams = new ArrayList<>();
        this.meshToolPositions = new ArrayList<>();
        this.llmAgentPositions = new ArrayList<>();

        analyzeParameters();

        // Initialize dependency arrays
        this.injectedDeps = new AtomicReferenceArray<>(meshToolPositions.size());
        this.injectedLlmAgents = new AtomicReferenceArray<>(llmAgentPositions.size());

        // Generate input schema (excluding injected params)
        this.inputSchema = generateInputSchema();

        log.debug("Created wrapper for {} with {} MCP params, {} mesh deps, {} LLM agents",
            funcId, mcpParams.size(), meshToolPositions.size(), llmAgentPositions.size());
    }

    /**
     * Analyze method parameters to identify:
     * - MCP parameters (with @Param annotation)
     * - McpMeshTool injection positions
     * - MeshLlmAgent injection positions
     */
    private void analyzeParameters() {
        Parameter[] params = method.getParameters();

        for (int i = 0; i < params.length; i++) {
            Parameter param = params[i];
            Class<?> type = param.getType();

            if (McpMeshTool.class.isAssignableFrom(type)) {
                // Mesh tool dependency - will be injected
                meshToolPositions.add(i);
            } else if (MeshLlmAgent.class.isAssignableFrom(type)) {
                // LLM agent - will be injected
                llmAgentPositions.add(i);
            } else {
                // Regular MCP parameter - must have @Param
                Param paramAnn = param.getAnnotation(Param.class);
                if (paramAnn != null) {
                    mcpParams.add(new ParamInfo(
                        i,
                        paramAnn.value(),
                        paramAnn.description(),
                        paramAnn.required(),
                        type
                    ));
                } else {
                    // No @Param annotation on non-injectable parameter
                    throw new IllegalStateException(
                        "Parameter at position " + i + " in method " + method.getName() +
                        " must have @Param annotation. Injectable types (McpMeshTool, MeshLlmAgent) are exempt."
                    );
                }
            }
        }
    }

    /**
     * Generate JSON Schema for MCP, excluding injected parameters.
     */
    private Map<String, Object> generateInputSchema() {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        for (ParamInfo param : mcpParams) {
            Map<String, Object> propSchema = new LinkedHashMap<>();
            propSchema.put("type", getJsonType(param.type()));

            if (!param.description().isEmpty()) {
                propSchema.put("description", param.description());
            }

            properties.put(param.name(), propSchema);

            if (param.required()) {
                required.add(param.name());
            }
        }

        schema.put("properties", properties);
        if (!required.isEmpty()) {
            schema.put("required", required);
        }

        return schema;
    }

    private String getJsonType(Class<?> type) {
        if (type == String.class) {
            return "string";
        } else if (type == int.class || type == Integer.class ||
                   type == long.class || type == Long.class) {
            return "integer";
        } else if (type == double.class || type == Double.class ||
                   type == float.class || type == Float.class) {
            return "number";
        } else if (type == boolean.class || type == Boolean.class) {
            return "boolean";
        } else if (type.isArray() || List.class.isAssignableFrom(type)) {
            return "array";
        } else {
            return "object";
        }
    }

    // =========================================================================
    // Dependency Updates (called by heartbeat)
    // =========================================================================

    /**
     * Update a McpMeshTool dependency at the given index.
     * Called by MeshToolWrapperRegistry when heartbeat resolves a dependency.
     *
     * @param depIndex The dependency index (0-based, in declaration order)
     * @param proxy    The resolved proxy (or null if unavailable)
     */
    public void updateDependency(int depIndex, McpMeshTool proxy) {
        if (depIndex >= 0 && depIndex < injectedDeps.length()) {
            injectedDeps.set(depIndex, proxy);
            log.debug("Updated dependency {} at index {} for {}",
                proxy != null ? proxy.getCapability() : "null", depIndex, funcId);
        }
    }

    /**
     * Update a MeshLlmAgent at the given index.
     *
     * @param llmIndex The LLM agent index
     * @param agent    The configured agent proxy
     */
    public void updateLlmAgent(int llmIndex, MeshLlmAgent agent) {
        if (llmIndex >= 0 && llmIndex < injectedLlmAgents.length()) {
            injectedLlmAgents.set(llmIndex, agent);
            log.debug("Updated LLM agent at index {} for {}", llmIndex, funcId);
        }
    }

    // =========================================================================
    // Tool Invocation (called by MCP SDK)
    // =========================================================================

    /**
     * Invoke the wrapped method with MCP arguments.
     * This is the entry point called by MCP SDK.
     *
     * @param mcpArgs Arguments from MCP call (Map of parameter name → value)
     * @return The serialized result
     * @throws Exception if invocation fails
     */
    public Object invoke(Map<String, Object> mcpArgs) throws Exception {
        log.debug("Invoking {} with args: {}", funcId, mcpArgs);

        // Build full argument array
        Object[] fullArgs = new Object[method.getParameterCount()];

        // Fill MCP parameters
        for (ParamInfo param : mcpParams) {
            Object value = mcpArgs.get(param.name());

            if (value == null && param.required()) {
                throw new IllegalArgumentException("Missing required parameter: " + param.name());
            }

            // Convert value to target type
            fullArgs[param.position()] = convertValue(value, param.type());
        }

        // Fill McpMeshTool dependencies
        for (int i = 0; i < meshToolPositions.size(); i++) {
            int paramPos = meshToolPositions.get(i);
            McpMeshTool proxy = injectedDeps.get(i);

            if (proxy == null) {
                String depName = i < dependencyNames.size() ? dependencyNames.get(i) : "unknown";
                throw new IllegalStateException(
                    "Dependency not available: " + depName + " (index " + i + ") for " + funcId +
                    ". The dependency may not be resolved yet or the providing agent is offline."
                );
            }

            fullArgs[paramPos] = proxy;
        }

        // Fill MeshLlmAgent dependencies
        for (int i = 0; i < llmAgentPositions.size(); i++) {
            int paramPos = llmAgentPositions.get(i);
            MeshLlmAgent agent = injectedLlmAgents.get(i);

            if (agent == null) {
                throw new IllegalStateException(
                    "LLM agent not available for " + funcId +
                    ". Check @MeshLlm configuration and provider availability."
                );
            }

            fullArgs[paramPos] = agent;
        }

        // Invoke the method
        Object result;
        try {
            result = method.invoke(bean, fullArgs);
        } catch (InvocationTargetException e) {
            // Unwrap to get the actual exception
            Throwable cause = e.getCause();
            log.error("Tool execution failed for {}: {}", funcId, cause.getMessage(), cause);
            if (cause instanceof Exception) {
                throw (Exception) cause;
            }
            throw new RuntimeException(cause);
        } catch (IllegalAccessException e) {
            log.error("Access denied for {}: {}", funcId, e.getMessage());
            throw new RuntimeException("Method access denied: " + e.getMessage(), e);
        }

        // Handle async results (CompletableFuture)
        if (result instanceof CompletableFuture<?> future) {
            try {
                result = future.get(ASYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            } catch (TimeoutException e) {
                throw new RuntimeException("Async operation timed out after " + ASYNC_TIMEOUT_SECONDS + " seconds");
            } catch (ExecutionException e) {
                Throwable cause = e.getCause();
                if (cause instanceof Exception) {
                    throw (Exception) cause;
                }
                throw new RuntimeException(cause);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("Async operation interrupted", e);
            }
        }

        return result;
    }

    /**
     * Convert an MCP argument value to the target parameter type.
     */
    @SuppressWarnings("unchecked")
    private Object convertValue(Object value, Class<?> targetType) {
        if (value == null) {
            return getDefaultValue(targetType);
        }

        // Already correct type
        if (targetType.isInstance(value)) {
            return value;
        }

        // Use Jackson for complex conversions
        try {
            return objectMapper.convertValue(value, targetType);
        } catch (Exception e) {
            log.warn("Failed to convert {} to {}: {}", value, targetType, e.getMessage());
            return value;
        }
    }

    private Object getDefaultValue(Class<?> type) {
        if (type.isPrimitive()) {
            if (type == boolean.class) return false;
            if (type == char.class) return '\0';
            if (type == byte.class) return (byte) 0;
            if (type == short.class) return (short) 0;
            if (type == int.class) return 0;
            if (type == long.class) return 0L;
            if (type == float.class) return 0.0f;
            if (type == double.class) return 0.0d;
        }
        return null;
    }

    // =========================================================================
    // Getters
    // =========================================================================

    public String getFuncId() {
        return funcId;
    }

    public String getCapability() {
        return capability;
    }

    /**
     * Get the method name (used as MCP tool name to match registry).
     */
    public String getMethodName() {
        return method.getName();
    }

    public String getDescription() {
        return description;
    }

    public Map<String, Object> getInputSchema() {
        return inputSchema;
    }

    public String getInputSchemaJson() {
        try {
            return objectMapper.writeValueAsString(inputSchema);
        } catch (Exception e) {
            return "{}";
        }
    }

    public int getDependencyCount() {
        return meshToolPositions.size();
    }

    public int getLlmAgentCount() {
        return llmAgentPositions.size();
    }

    public List<String> getDependencyNames() {
        return dependencyNames;
    }

    /**
     * Check if all dependencies are available.
     */
    public boolean areDependenciesAvailable() {
        for (int i = 0; i < injectedDeps.length(); i++) {
            McpMeshTool dep = injectedDeps.get(i);
            if (dep == null || !dep.isAvailable()) {
                return false;
            }
        }
        return true;
    }

    // =========================================================================
    // Inner Classes
    // =========================================================================

    /**
     * Metadata for an MCP parameter.
     */
    private record ParamInfo(
        int position,
        String name,
        String description,
        boolean required,
        Class<?> type
    ) {}
}
