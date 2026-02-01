package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.Param;
import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.spring.tracing.SpanScope;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TraceInfo;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;
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
 * @see McpToolHandler
 */
public class MeshToolWrapper implements McpToolHandler {

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
    private final List<Type> meshToolReturnTypes;      // Generic return types for McpMeshTool params
    private final List<Integer> llmAgentPositions;     // Positions of MeshLlmAgent params
    private final Map<String, Object> inputSchema;     // JSON Schema for MCP

    // Mutable dependency arrays (updated by heartbeat)
    @SuppressWarnings("rawtypes")
    private final AtomicReferenceArray<McpMeshTool> injectedDeps;
    private final AtomicReferenceArray<MeshLlmAgent> injectedLlmAgents;

    // Dependency names for error messages
    private final List<String> dependencyNames;

    private final ObjectMapper objectMapper;

    // Tracing support (set lazily via setter)
    private final AtomicReference<ExecutionTracer> tracerRef = new AtomicReference<>();

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
        this.meshToolReturnTypes = new ArrayList<>();
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
     * - McpMeshTool injection positions and their generic return types
     * - MeshLlmAgent injection positions
     */
    private void analyzeParameters() {
        Parameter[] params = method.getParameters();
        Type[] genericTypes = method.getGenericParameterTypes();

        for (int i = 0; i < params.length; i++) {
            Parameter param = params[i];
            Class<?> type = param.getType();

            if (McpMeshTool.class.isAssignableFrom(type)) {
                // Mesh tool dependency - will be injected
                meshToolPositions.add(i);
                // Extract generic type argument (e.g., Integer from McpMeshTool<Integer>)
                Type returnType = extractGenericTypeArgument(genericTypes[i]);
                meshToolReturnTypes.add(returnType);
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
    @SuppressWarnings("rawtypes")
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

    /**
     * Set the ExecutionTracer for this wrapper.
     *
     * @param tracer The tracer to use
     */
    public void setTracer(ExecutionTracer tracer) {
        tracerRef.set(tracer);
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

        // Extract trace context from arguments (fallback for TypeScript agents)
        // If TracingFilter didn't set context (e.g., came from TypeScript agent via FastMCP),
        // try extracting from arguments where trace IDs are injected
        Map<String, Object> cleanArgs = extractAndSetupTraceContext(mcpArgs);

        // Get tracer and start span if tracing is enabled
        ExecutionTracer tracer = tracerRef.get();
        Map<String, Object> spanMetadata = new LinkedHashMap<>();
        spanMetadata.put("capability", capability);
        spanMetadata.put("args_count", cleanArgs.size());
        spanMetadata.put("injected_dependencies", meshToolPositions.size());

        // Use method name for trace (not full funcId) - matches Python/TypeScript behavior
        String traceName = method.getName();
        try (SpanScope span = tracer != null ? tracer.startSpan(traceName, spanMetadata) : SpanScope.NOOP) {
            Object result = invokeInternal(cleanArgs);
            span.withResult(result);
            return result;
        }
    }

    /**
     * Extract trace context from arguments and set up TraceContext if not already set.
     *
     * <p>TypeScript agents inject trace context into arguments since FastMCP doesn't
     * expose HTTP headers to tool handlers. This method extracts those fields and
     * removes them from the arguments before passing to the tool.
     *
     * @param mcpArgs The MCP arguments (may contain _trace_id and _parent_span)
     * @return Clean arguments with trace fields removed
     */
    private Map<String, Object> extractAndSetupTraceContext(Map<String, Object> mcpArgs) {
        if (mcpArgs == null) {
            return new LinkedHashMap<>();
        }

        // Make a mutable copy
        Map<String, Object> cleanArgs = new LinkedHashMap<>(mcpArgs);

        // Extract trace context from arguments
        String traceId = null;
        String parentSpan = null;

        Object traceIdObj = cleanArgs.remove("_trace_id");
        Object parentSpanObj = cleanArgs.remove("_parent_span");

        if (traceIdObj instanceof String) {
            traceId = (String) traceIdObj;
        }
        if (parentSpanObj instanceof String) {
            parentSpan = (String) parentSpanObj;
        }

        // Set trace context from arguments (authoritative source for trace propagation)
        // Arguments take precedence over any existing context because:
        // 1. TypeScript agents inject trace IDs into arguments (FastMCP doesn't expose headers)
        // 2. InheritableThreadLocal can leak stale context from thread pool reuse
        // 3. The calling agent explicitly passed these trace IDs for this specific call
        if (traceId != null && !traceId.isEmpty()) {
            TraceInfo traceInfo = TraceInfo.fromHeaders(traceId, parentSpan);
            TraceContext.set(traceInfo);
            log.trace("Set trace context from arguments: trace={}, parent={}",
                traceId.substring(0, Math.min(8, traceId.length())),
                parentSpan != null ? parentSpan.substring(0, Math.min(8, parentSpan.length())) : "null");
        }

        return cleanArgs;
    }

    /**
     * Internal invoke method that handles the actual method invocation.
     */
    private Object invokeInternal(Map<String, Object> cleanArgs) throws Exception {
        // Build full argument array
        Object[] fullArgs = new Object[method.getParameterCount()];

        // Fill MCP parameters
        for (ParamInfo param : mcpParams) {
            Object value = cleanArgs.get(param.name());

            if (value == null && param.required()) {
                throw new IllegalArgumentException("Missing required parameter: " + param.name());
            }

            // Convert value to target type
            fullArgs[param.position()] = convertValue(value, param.type());
        }

        // Fill McpMeshTool dependencies (null if unavailable for graceful degradation)
        for (int i = 0; i < meshToolPositions.size(); i++) {
            int paramPos = meshToolPositions.get(i);
            McpMeshTool proxy = injectedDeps.get(i);

            // Allow null for graceful degradation - tool method can check:
            //   if (dep != null && dep.isAvailable()) { ... } else { fallback }
            if (proxy == null) {
                String depName = i < dependencyNames.size() ? dependencyNames.get(i) : "unknown";
                log.debug("Dependency {} not available for {}, passing null for graceful degradation",
                    depName, funcId);
            }

            fullArgs[paramPos] = proxy;
        }

        // Fill MeshLlmAgent dependencies and set context for template rendering
        // Allow null for graceful degradation - method can check:
        //   if (llm != null && llm.isAvailable()) { ... } else { fallback }
        for (int i = 0; i < llmAgentPositions.size(); i++) {
            int paramPos = llmAgentPositions.get(i);
            MeshLlmAgent agent = injectedLlmAgents.get(i);

            if (agent == null) {
                log.debug("LLM agent not available for {}, passing null for graceful degradation", funcId);
            } else if (agent instanceof MeshLlmAgentProxy proxy) {
                // Set context for template rendering
                Map<String, Object> context = extractContextForTemplate(proxy.getContextParamName(), cleanArgs);
                if (context != null) {
                    proxy.setInvocationContext(context);
                    log.debug("Set invocation context with {} variables for LLM agent",
                        context.size());
                }
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
     * Extract context from MCP args for template rendering.
     *
     * <p>Looks for a parameter matching the contextParamName and wraps it
     * in a Map with the contextParamName as the key. This allows templates
     * to reference the context as {@code ${ctx.field}} when contextParam="ctx".
     *
     * @param contextParamName The parameter name to look for
     * @param mcpArgs          The MCP arguments
     * @return A Map suitable for template rendering with contextParamName as key
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> extractContextForTemplate(String contextParamName, Map<String, Object> mcpArgs) {
        if (contextParamName == null || mcpArgs == null) {
            return null;
        }

        Object contextValue = mcpArgs.get(contextParamName);
        if (contextValue == null) {
            // If no specific context param, use all MCP args as context
            return new HashMap<>(mcpArgs);
        }

        // Wrap the context value with the param name as key
        // This allows templates to use ${ctx.field} when contextParam="ctx"
        Map<String, Object> templateContext = new HashMap<>();
        templateContext.put(contextParamName, contextValue);

        // Also add all other MCP args to context (except injected params)
        for (Map.Entry<String, Object> entry : mcpArgs.entrySet()) {
            if (!entry.getKey().equals(contextParamName)) {
                templateContext.put(entry.getKey(), entry.getValue());
            }
        }

        return templateContext;
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

    /**
     * Extract the type argument from a parameterized type.
     *
     * <p>For {@code McpMeshTool<Integer>}, returns {@code Integer.class}.
     * For raw {@code McpMeshTool}, returns {@code null}.
     *
     * @param type The generic parameter type
     * @return The first type argument, or null if not parameterized
     */
    private Type extractGenericTypeArgument(Type type) {
        if (type instanceof ParameterizedType pt) {
            Type[] typeArgs = pt.getActualTypeArguments();
            if (typeArgs.length > 0) {
                return typeArgs[0];
            }
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
     * Get the expected return type for a dependency at the given index.
     *
     * <p>This is extracted from the generic type parameter of McpMeshTool&lt;T&gt;.
     * For example, for {@code McpMeshTool<Integer>}, this returns {@code Integer.class}.
     *
     * @param depIndex The dependency index
     * @return The return type, or null if not specified or index out of bounds
     */
    public Type getDependencyReturnType(int depIndex) {
        if (depIndex >= 0 && depIndex < meshToolReturnTypes.size()) {
            return meshToolReturnTypes.get(depIndex);
        }
        return null;
    }

    /**
     * Check if all dependencies are available.
     */
    @SuppressWarnings("rawtypes")
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
