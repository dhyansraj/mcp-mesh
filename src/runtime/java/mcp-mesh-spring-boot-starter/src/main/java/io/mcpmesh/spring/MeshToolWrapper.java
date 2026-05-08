package io.mcpmesh.spring;

import tools.jackson.databind.JsonNode;
import com.github.victools.jsonschema.generator.SchemaGenerator;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.JobContext;
import io.mcpmesh.JobController;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.Param;
import io.mcpmesh.core.MeshCore;
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
    private static final SchemaGenerator SCHEMA_GENERATOR = MeshSchemaSupport.generator();
    /** Issue #895: shared empty {@code retryOn} array — sentinel for "no retry-eligible exceptions". */
    @SuppressWarnings("unchecked")
    private static final Class<? extends Throwable>[] EMPTY_RETRY_ON =
        (Class<? extends Throwable>[]) new Class<?>[0];

    private final String funcId;
    private final String capability;
    private final String description;
    private final Object bean;
    private final Method method;
    private final boolean task;
    /**
     * Issue #895: per-tool retry-eligible exception whitelist read from
     * {@code @MeshTool(retryOn=...)}. When a handler raises a Throwable
     * matching one of these classes, the dispatch wrapper calls
     * {@link JobController#releaseLease(String)} instead of
     * {@link JobController#fail(String)} so a peer replica can re-claim
     * the job within ~5s. Always non-null (zero-length when not set).
     */
    private final Class<? extends Throwable>[] retryOn;

    // Parameter metadata
    private final List<ParamInfo> mcpParams;           // MCP-exposed parameters (with @Param)
    private final List<Integer> meshToolPositions;     // Positions of McpMeshTool params
    private final List<Type> meshToolReturnTypes;      // Generic return types for McpMeshTool params
    private final List<Integer> llmAgentPositions;     // Positions of MeshLlmAgent params
    private final Integer meshJobParamIndex;           // Position of MeshJob param, or null
    private final Map<String, Object> inputSchema;     // JSON Schema for MCP

    // Mutable dependency arrays (updated by heartbeat)
    @SuppressWarnings("rawtypes")
    private final AtomicReferenceArray<McpMeshTool> injectedDeps;
    private final AtomicReferenceArray<MeshLlmAgent> injectedLlmAgents;

    // Dependency names for error messages
    private final List<String> dependencyNames;

    // Consumer-side: MeshJobSubmitter to inject when MeshJob slot is present
    // and this method depends on a task=true capability. Set by the runtime
    // wiring (MeshAutoConfiguration / MeshEventProcessor) once the registry
    // tells us the dep is task=true. Null when this slot is producer-side
    // only (i.e. method is task=true) or when no submitter applies.
    private final AtomicReference<MeshJobSubmitter> jobSubmitter = new AtomicReference<>();

    // Producer-side: agent's own per-replica instance ID + registry URL.
    // Used to construct JobController on inbound dispatch when the request
    // bears X-Mesh-Job-Id. Set lazily via setJobBindingContext (so the
    // wrapper doesn't need a hard dep on MeshRuntime at construction time).
    private final AtomicReference<String> instanceId = new AtomicReference<>();
    private final AtomicReference<String> registryUrl = new AtomicReference<>();

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
        this(funcId, capability, description, bean, method, dependencyNames, objectMapper, false);
    }

    /**
     * Create a wrapper for a @MeshTool annotated method, with explicit
     * task flag for MeshJob substrate (Phase B).
     */
    public MeshToolWrapper(
            String funcId,
            String capability,
            String description,
            Object bean,
            Method method,
            List<String> dependencyNames,
            ObjectMapper objectMapper,
            boolean task) {
        this(funcId, capability, description, bean, method, dependencyNames,
            objectMapper, task, EMPTY_RETRY_ON);
    }

    /**
     * Create a wrapper for a @MeshTool annotated method, with explicit
     * task flag and {@code retryOn} whitelist (issue #895).
     *
     * @param retryOn Per-tool retry-eligible exception classes from
     *                {@link io.mcpmesh.MeshTool#retryOn()}. May be null
     *                or empty for "no retry-eligible exceptions".
     */
    public MeshToolWrapper(
            String funcId,
            String capability,
            String description,
            Object bean,
            Method method,
            List<String> dependencyNames,
            ObjectMapper objectMapper,
            boolean task,
            Class<? extends Throwable>[] retryOn) {

        this.funcId = funcId;
        this.capability = capability;
        this.description = description;
        this.bean = bean;
        this.method = method;
        this.task = task;
        this.retryOn = retryOn != null ? retryOn : EMPTY_RETRY_ON;
        this.dependencyNames = dependencyNames != null ? dependencyNames : List.of();
        this.objectMapper = objectMapper;

        // Make method accessible (for private methods)
        method.setAccessible(true);

        // Analyze parameters via the resolver so MeshJob index is captured.
        MeshJobResolver.Resolved resolved = MeshJobResolver.resolve(method);
        this.meshJobParamIndex = resolved.meshJobParamIndex().orElse(null);

        // Analyze remaining parameters (mcp params + mesh deps + llm agents)
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

        log.debug("Created wrapper for {} with {} MCP params, {} mesh deps, {} LLM agents, task={}, meshJobParamIndex={}",
            funcId, mcpParams.size(), meshToolPositions.size(), llmAgentPositions.size(),
            task, meshJobParamIndex);
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

            if (MeshJob.class.isAssignableFrom(type)) {
                // Phase B MeshJob substrate: this slot is filled separately
                // by the dispatch wrapper (JobController on inbound job
                // dispatch, MeshJobSubmitter on consumer side). No @Param
                // required; the param is exempt from the MCP input schema.
                continue;
            } else if (McpMeshTool.class.isAssignableFrom(type)) {
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
                        genericTypes[i]
                    ));
                } else {
                    // No @Param annotation on non-injectable parameter
                    throw new IllegalStateException(
                        "Parameter at position " + i + " in method " + method.getName() +
                        " must have @Param annotation. Injectable types (McpMeshTool, MeshLlmAgent, MeshJob) are exempt."
                    );
                }
            }
        }
    }

    /**
     * Generate JSON Schema for MCP, excluding injected parameters.
     * Uses victools/jsonschema-generator for proper nested type handling.
     */
    private Map<String, Object> generateInputSchema() {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        for (ParamInfo param : mcpParams) {
            // Use victools to generate schema for the parameter type
            JsonNode paramSchema = SCHEMA_GENERATOR.generateSchema(param.type());
            Map<String, Object> propSchema = convertJsonNodeToMap(paramSchema);

            // Add description from @Param annotation if not already present
            if (!param.description().isEmpty() && !propSchema.containsKey("description")) {
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

    /**
     * Convert Jackson JsonNode to Map for schema representation.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> convertJsonNodeToMap(JsonNode node) {
        try {
            return objectMapper.convertValue(node, Map.class);
        } catch (Exception e) {
            log.warn("Failed to convert JsonNode to Map: {}", e.getMessage());
            Map<String, Object> fallback = new LinkedHashMap<>();
            fallback.put("type", "object");
            return fallback;
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
            log.info("Updated LLM agent at index {} for {} (proxy@{})",
                llmIndex, funcId,
                agent != null ? System.identityHashCode(agent) : "null");
        } else {
            log.warn("LLM index {} out of bounds for {} (max: {})",
                llmIndex, funcId, injectedLlmAgents.length());
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

    /**
     * Bind the producer-side context needed to construct a {@link JobController}
     * on inbound job dispatch. Called once at startup by the runtime wiring
     * (MeshAutoConfiguration / MeshEventProcessor) once the agent's
     * per-replica instance id and registry URL are known.
     *
     * <p>No-op when this tool is not {@code task=true} — the wrapper would
     * never construct a controller in that case anyway.
     *
     * @param instanceId  Per-replica agent ID (matches what the registry
     *                    sees as {@code owner_instance_id} on claim)
     * @param registryUrl Mesh registry base URL
     */
    public void setJobBindingContext(String instanceId, String registryUrl) {
        if (instanceId != null) this.instanceId.set(instanceId);
        if (registryUrl != null) this.registryUrl.set(registryUrl);
    }

    /**
     * Set or clear the consumer-side {@link MeshJobSubmitter} to inject at
     * the {@code MeshJob} slot for a regular (non-job) tool call. Set by
     * the runtime once the registry tells us a declared dependency is a
     * {@code task=true} capability.
     *
     * @param submitter The submitter to inject, or null to clear
     */
    public void setJobSubmitter(MeshJobSubmitter submitter) {
        this.jobSubmitter.set(submitter);
    }

    /** Whether this tool is registered with {@code task=true}. */
    public boolean isTask() {
        return task;
    }

    /** The position of the MeshJob param in the method signature, or null. */
    public Integer getMeshJobParamIndex() {
        return meshJobParamIndex;
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

        // Always copy to avoid mutating the original map via remove() calls below
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
        // 2. ThreadLocal retains stale context when servlet threads are reused
        // 3. The calling agent explicitly passed these trace IDs for this specific call
        if (traceId != null && !traceId.isEmpty()) {
            TraceInfo traceInfo = TraceInfo.forPropagation(traceId, parentSpan);
            TraceContext.set(traceInfo);
            log.trace("Set trace context from arguments: trace={}, parent={}",
                traceId.substring(0, Math.min(8, traceId.length())),
                parentSpan != null ? parentSpan.substring(0, Math.min(8, parentSpan.length())) : "null");
        }

        // Extract _mesh_headers from arguments and set propagated headers context
        Object meshHeadersObj = cleanArgs.remove("_mesh_headers");
        if (meshHeadersObj instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> meshHeaders = (Map<String, Object>) meshHeadersObj;
            Map<String, String> filtered = new HashMap<>();
            if (!TraceContext.getPropagateHeaderNames().isEmpty()) {
                for (Map.Entry<String, Object> entry : meshHeaders.entrySet()) {
                    if (entry.getValue() instanceof String
                        && TraceContext.matchesPropagateHeader(entry.getKey())) {
                        filtered.put(entry.getKey().toLowerCase(), (String) entry.getValue());
                    }
                }
            }
            if (!filtered.isEmpty()) {
                // Merge with any headers already captured by TracingFilter
                Map<String, String> existing = TraceContext.getPropagatedHeaders();
                if (!existing.isEmpty()) {
                    Map<String, String> merged = new HashMap<>(existing);
                    // Args headers fill in gaps but don't override HTTP headers
                    for (Map.Entry<String, String> e : filtered.entrySet()) {
                        merged.putIfAbsent(e.getKey(), e.getValue());
                    }
                    filtered = merged;
                }
                TraceContext.setPropagatedHeaders(filtered);
                log.trace("Set {} propagated headers from _mesh_headers args", filtered.size());
            }
        }

        return cleanArgs;
    }

    /**
     * Internal invoke method that handles the actual method invocation.
     */
    private Object invokeInternal(Map<String, Object> cleanArgs) throws Exception {
        // Phase B MeshJob substrate: detect inbound job dispatch.
        // X-Mesh-Job-Id is captured by TracingFilter (we register it as a
        // propagation header in MeshAutoConfiguration), so it lands in
        // TraceContext.getPropagatedHeaders() with a lowercased key.
        Map<String, String> propagated = TraceContext.getPropagatedHeaders();
        String jobIdHeader = propagated != null ? propagated.get("x-mesh-job-id") : null;
        Long deadlineSecs = null;
        if (jobIdHeader != null && !jobIdHeader.isEmpty()) {
            String timeoutHeader = propagated.get("x-mesh-timeout");
            if (timeoutHeader != null && !timeoutHeader.isEmpty()) {
                try {
                    double secs = Double.parseDouble(timeoutHeader.trim());
                    if (Double.isFinite(secs) && secs > 0) {
                        // Round, don't truncate. `(long) 0.7 == 0` would
                        // collapse a sub-second budget into "immediate"
                        // and bypass the `secs > 0` filter below; rounding
                        // preserves at-least-the-budget semantics for
                        // sub-second timeouts (PR review #874).
                        deadlineSecs = Math.max(1L, Math.round(secs));
                    }
                } catch (NumberFormatException nfe) {
                    log.debug("Invalid X-Mesh-Timeout header value '{}': {}", timeoutHeader, nfe.getMessage());
                }
            }
        }

        // If task=true tool is being called as a job, dispatch through the
        // job pipeline: build a JobController bound to this job_id, set
        // both Java + native contexts, inject the controller at
        // meshJobParamIndex, auto-complete on successful return.
        //
        // Gate is intentionally narrow — only `task=true` + a present
        // `X-Mesh-Job-Id` header. Whether a JobController gets injected
        // (requires meshJobParamIndex + instanceId + registryUrl) is
        // decided INSIDE dispatchAsJob; if any of those is missing, we
        // still bind the JobContext snapshot so outbound calls
        // propagate the right job-id headers, but invoke the user
        // method without the controller. The previous all-or-nothing
        // gate silently skipped the wrap when the wiring was partial,
        // leaving downstream calls headerless. (PR #891 review.)
        if (task && jobIdHeader != null && !jobIdHeader.isEmpty()) {
            return dispatchAsJob(cleanArgs, jobIdHeader, deadlineSecs);
        }

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

        // Phase B MeshJob substrate: fill MeshJob slot for non-job paths.
        // - Consumer side (method has dependencies + jobSubmitter set): inject submitter.
        // - Otherwise (incl. task=true called sync): inject null.
        if (meshJobParamIndex != null) {
            MeshJobSubmitter submitter = jobSubmitter.get();
            fullArgs[meshJobParamIndex] = submitter; // null when no submitter wired
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
                log.warn("LLM agent at index {} is null for {} - passing null for graceful degradation",
                    i, funcId);
            } else if (agent instanceof MeshLlmAgentProxy proxy) {
                log.info("Injecting LLM agent for {} (index={}, proxy@{}, available={}, provider={})",
                    funcId, i, System.identityHashCode(proxy), proxy.isAvailable(), proxy.getProvider());
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
     * Phase B MeshJob substrate: invoke the user method as a job.
     *
     * <p>Constructs a {@link JobController} bound to {@code jobId}, sets
     * the Java-side {@link JobContext} (for in-process reads via
     * {@code JobContext.current()}), injects the controller at
     * {@link #meshJobParamIndex}, invokes the user method, and auto-
     * completes the controller with the return value if the user did
     * not explicitly call {@code complete()} / {@code fail()}.
     *
     * <p>On exception, attempts a best-effort {@code controller.fail(...)}
     * if not already terminal, then propagates the exception so the MCP
     * SDK surfaces it as a tool-call error.
     *
     * <p><b>How the Java sync path binds the Rust cancel registry:</b>
     * The dispatch wraps the user invocation in {@code mesh_run_as_job}
     * (a C-ABI export that internally calls {@code run_as_job} and binds
     * the cancel registry entry for the job ID). The Rust side wraps the
     * callback in {@code tokio::task::block_in_place} so nested
     * {@code block_on} calls from inside the callback (e.g.
     * {@code mesh_job_controller_complete}) don't panic. This makes
     * {@code POST /jobs/{id}/cancel} fire the in-flight cancel token
     * immediately, matching Python and TypeScript behaviour. The
     * Java-side {@link JobContext} ThreadLocal is still bound on top
     * because the Rust task-local isn't visible to Java code in the
     * callback — user code's {@code JobContext.current()} reads and
     * outbound-header injection both depend on the ThreadLocal mirror.
     * Resolved via #889.
     *
     * <p>Mirrors (Java-adapted):
     * <ul>
     *   <li>Python {@code _mcp_mesh.engine.job_dispatch._run_and_autocomplete}</li>
     *   <li>TypeScript {@code runWithJobContext} in inbound-job-dispatch.ts</li>
     * </ul>
     */
    private Object dispatchAsJob(Map<String, Object> cleanArgs, String jobId, Long deadlineSecs) throws Exception {
        // Build full args with the controller injected at the MeshJob slot
        Object[] fullArgs = new Object[method.getParameterCount()];
        for (ParamInfo param : mcpParams) {
            Object value = cleanArgs.get(param.name());
            if (value == null && param.required()) {
                throw new IllegalArgumentException("Missing required parameter: " + param.name());
            }
            fullArgs[param.position()] = convertValue(value, param.type());
        }
        // Fill McpMeshTool dependencies and LLM agents (mirrors the
        // non-job path; needed so a task=true method that ALSO has deps
        // / LLM agents sees them populated)
        for (int i = 0; i < meshToolPositions.size(); i++) {
            int paramPos = meshToolPositions.get(i);
            McpMeshTool proxy = injectedDeps.get(i);
            fullArgs[paramPos] = proxy;
        }
        for (int i = 0; i < llmAgentPositions.size(); i++) {
            int paramPos = llmAgentPositions.get(i);
            MeshLlmAgent agent = injectedLlmAgents.get(i);
            if (agent instanceof MeshLlmAgentProxy proxy) {
                Map<String, Object> context = extractContextForTemplate(proxy.getContextParamName(), cleanArgs);
                if (context != null) {
                    proxy.setInvocationContext(context);
                }
            }
            fullArgs[paramPos] = agent;
        }

        // Decide whether we can build a JobController: we need a slot
        // index AND both binding fields. If any piece is missing the
        // job is still routed through the wrap (so outbound calls
        // propagate the right headers via JobContext) but without the
        // controller — see the gate-site javadoc. (PR #891 review.)
        boolean canInjectController = meshJobParamIndex != null
            && instanceId.get() != null
            && registryUrl.get() != null;

        if (!canInjectController) {
            log.warn("Job dispatch for tool={} job={} is missing wiring " +
                "(meshJobParamIndex={}, instanceId={}, registryUrl={}); " +
                "binding JobContext only — controller NOT injected",
                funcId, jobId,
                meshJobParamIndex, instanceId.get(), registryUrl.get());
            // Fill the MeshJob slot (if any) with null — user code that
            // declares a MeshJob param tolerates null per DDDI.
            if (meshJobParamIndex != null) {
                fullArgs[meshJobParamIndex] = null;
            }
            JobContext.Snapshot snap = new JobContext.Snapshot(jobId, deadlineSecs);
            return runAsJobWithRegistryBinding(jobId, deadlineSecs,
                () -> JobContext.withJob(snap, () -> invokeNoController(fullArgs)));
        }

        // Construct the producer controller. Free in finally.
        JobController controller = JobController.open(jobId, instanceId.get(), registryUrl.get());
        try {
            // Inject the controller at the MeshJob slot
            fullArgs[meshJobParamIndex] = controller;

            // Bind both the Rust-side cancel registry (via mesh_run_as_job)
            // and the Java-side ThreadLocal job context (via JobContext.withJob)
            // for the duration of the user method. See class javadoc on
            // dispatchAsJob for the rationale (resolved via #889).
            JobContext.Snapshot snap = new JobContext.Snapshot(jobId, deadlineSecs);
            try {
                return runAsJobWithRegistryBinding(jobId, deadlineSecs,
                    () -> JobContext.withJob(snap, () -> invokeAndAutoComplete(fullArgs, controller)));
            } catch (Throwable t) {
                // Defensive: runAsJobWithRegistryBinding can throw BEFORE
                // invokeAndAutoComplete runs (snapshot serialization or
                // mesh_run_as_job rc != 0 path). The row was claimed
                // (status=working); without a terminal call here it would
                // sit in working until lease expiry. Mark failed best-effort
                // before rethrowing so the consumer's await() resolves
                // promptly. tryFail is no-op when already terminal (e.g.
                // invokeAndAutoComplete ran and the helper already
                // reported), so the double-cover is safe.
                tryFail(controller, "dispatch error before user method: " +
                    (t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName()));
                throw t;
            }
        } finally {
            controller.close();
        }
    }

    /**
     * Wrap a Java {@link Callable} in {@link MeshCore#mesh_run_as_job} so
     * the Rust cancel-registry entry for {@code jobId} is bound while the
     * callable runs. {@code POST /jobs/{jobId}/cancel} can then fire the
     * in-flight cancel token via {@code mesh_cancel_active_job} — the
     * Java-only path previously skipped this binding (Phase A of #889).
     *
     * <p>Throwables raised by the body callable are captured in a closure-
     * captured holder and rethrown after {@code mesh_run_as_job} returns,
     * preserving the original exception type for the auto-complete logic
     * ({@code retryOn} matching, etc.) — the Rust callback's {@code int}
     * return is too coarse to carry exception identity.
     *
     * <p>Snapshot serialization is a precondition, NOT part of the body:
     * a Jackson failure inside {@link #buildRunAsJobSnapshot} (extremely
     * unlikely given the trivial two-scalar map shape) propagates as
     * {@link IllegalStateException} to the caller and never reaches the
     * native FFI. The unified rethrow logic only covers exceptions raised
     * inside the user-supplied callable.
     */
    private Object runAsJobWithRegistryBinding(
            String jobId, Long deadlineSecs, java.util.concurrent.Callable<Object> body)
            throws Exception {
        String snapshotJson = buildRunAsJobSnapshot(jobId, deadlineSecs);
        Object[] resultBox = new Object[1];
        Throwable[] thrownBox = new Throwable[1];
        MeshCore core = MeshCore.load();
        int rc = core.mesh_run_as_job(snapshotJson, userData -> {
            // Inside mesh_run_as_job's run_as_job scope on a Tokio worker
            // thread (block_in_place applied on the Rust side so nested
            // controller block_on calls are legal).
            try {
                resultBox[0] = body.call();
                return 0;
            } catch (Throwable t) {
                thrownBox[0] = t;
                return -1;
            }
        }, null);
        if (thrownBox[0] != null) {
            if (thrownBox[0] instanceof Exception ex) throw ex;
            if (thrownBox[0] instanceof Error err) throw err;
            throw new RuntimeException(thrownBox[0]);
        }
        if (rc != 0) {
            throw new RuntimeException(
                "mesh_run_as_job failed (rc=" + rc + ") for job=" + jobId
                + ": " + readLastError(core));
        }
        return resultBox[0];
    }

    /**
     * Build the {@code mesh_run_as_job} snapshot payload:
     * {@code {"job_id": "...", "deadline_secs": <number>|null}}.
     */
    private String buildRunAsJobSnapshot(String jobId, Long deadlineSecs) {
        try {
            Map<String, Object> snap = new LinkedHashMap<>();
            snap.put("job_id", jobId);
            snap.put("deadline_secs", deadlineSecs);
            return objectMapper.writeValueAsString(snap);
        } catch (Exception e) {
            throw new IllegalStateException(
                "failed to serialize mesh_run_as_job snapshot for job=" + jobId, e);
        }
    }

    /**
     * Drain {@code mesh_last_error} into a Java string for diagnostic use,
     * freeing the native pointer. Returns {@code "<no error>"} when the
     * last-error slot is empty.
     */
    private static String readLastError(MeshCore core) {
        jnr.ffi.Pointer err = core.mesh_last_error();
        if (err == null) return "<no error>";
        try {
            return err.getString(0);
        } finally {
            core.mesh_free_string(err);
        }
    }

    /**
     * Invoke the user method when we cannot construct a controller
     * (missing wiring). Returns the user's result directly; no
     * auto-complete because there's no controller to mark terminal.
     * Matches the inbound non-job code path's invocation logic but
     * stays inside the JobContext snapshot so outbound headers still
     * carry the job id. (PR #891 review.)
     */
    private Object invokeNoController(Object[] fullArgs) throws Exception {
        Object result;
        try {
            result = method.invoke(bean, fullArgs);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause();
            if (cause instanceof Exception ex) throw ex;
            throw new RuntimeException(cause);
        } catch (IllegalAccessException e) {
            throw new RuntimeException("Method access denied: " + e.getMessage(), e);
        }
        if (result instanceof CompletableFuture<?> future) {
            try {
                result = future.get(ASYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            } catch (TimeoutException e) {
                throw new RuntimeException("Async operation timed out after " + ASYNC_TIMEOUT_SECONDS + " seconds");
            } catch (ExecutionException e) {
                Throwable cause = e.getCause();
                if (cause instanceof Exception ex) throw ex;
                throw new RuntimeException(cause);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("Async operation interrupted", e);
            }
        }
        return result;
    }

    private Object invokeAndAutoComplete(Object[] fullArgs, JobController controller) throws Exception {
        Object result;
        try {
            result = method.invoke(bean, fullArgs);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause();
            // Issue #895: retryOn-aware exception handling. Mirrors Python
            // `_run_and_autocomplete` (job_dispatch.py:336-386) and TS
            // `runWithJobContext` (inbound-job-dispatch.ts:160-225):
            //   1) probe is_terminal — user's terminal call wins;
            //   2) retryOn match → releaseLease (suppress on success,
            //      fall back to fail() on release failure);
            //   3) non-matching → existing best-effort fail() then rethrow.
            if (cause != null && handleRetryOrFail(controller, cause)) {
                // Suppressed by retryOn — registry now owns the row's
                // lifecycle (peer replica re-claims within ~5s).
                return null;
            }
            // cause==null path: nothing to match against retryOn, so preserve
            // the original best-effort failure-report with the helpful
            // "method invocation failed" literal and rethrow `e` unchanged.
            if (cause == null) {
                tryFail(controller, "method invocation failed");
                throw e;
            }
            if (cause instanceof Exception ex) throw ex;
            throw new RuntimeException(cause);
        } catch (IllegalAccessException e) {
            tryFail(controller, e.toString());
            throw new RuntimeException("Method access denied: " + e.getMessage(), e);
        }

        // If the method returns a CompletableFuture, await it before
        // deciding whether to auto-complete (matches the Python /
        // TypeScript async semantics).
        if (result instanceof CompletableFuture<?> future) {
            try {
                result = future.get(ASYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            } catch (TimeoutException e) {
                tryFail(controller, "async operation timed out after " + ASYNC_TIMEOUT_SECONDS + "s");
                throw new RuntimeException("Async operation timed out after " + ASYNC_TIMEOUT_SECONDS + " seconds");
            } catch (ExecutionException e) {
                // Issue #895: same retryOn-aware handling as the synchronous
                // throw path — a CompletableFuture that completes
                // exceptionally with a retry-eligible cause should also
                // release the lease.
                Throwable cause = e.getCause();
                if (cause == null) cause = e;
                if (handleRetryOrFail(controller, cause)) {
                    return null;
                }
                if (cause instanceof Exception ex) throw ex;
                throw new RuntimeException(cause);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                tryFail(controller, "async operation interrupted");
                throw new RuntimeException("Async operation interrupted", e);
            }
        }

        // Auto-complete iff the user didn't already close the row
        // themselves. Matches Python's _run_and_autocomplete + TS's
        // runWithJobContext.
        try {
            if (!controller.isTerminal()) {
                controller.complete(result);
            }
        } catch (Exception e) {
            log.warn("Auto-complete failed for job {}: {}", controller.jobId(), e.getMessage());
            // Don't shadow the user's return value — the registry sweep
            // is the ultimate backstop for stale `working` rows.
        }
        return result;
    }

    private static void tryFail(JobController controller, String reason) {
        try {
            if (!controller.isTerminal()) {
                controller.fail(reason);
            }
        } catch (Exception ignored) {
            // Best-effort — already logged the original cause.
        }
    }

    /**
     * Issue #895 — central retryOn-aware terminal handler shared between
     * the synchronous-throw path and the {@link CompletableFuture}-failure
     * path of {@link #invokeAndAutoComplete}. Mirrors the canonical Python
     * pattern in {@code _run_and_autocomplete} (job_dispatch.py:336-386).
     *
     * <p>Returns {@code true} when the exception was suppressed (caller
     * should return {@code null} as the dispatch result; the registry
     * now owns the row's lifecycle). Returns {@code false} when the
     * caller must propagate {@code cause} — either because the user
     * already terminated the controller, no retryOn entry matched, or
     * the {@code releaseLease} call failed and we fell back to {@code fail()}.
     */
    private boolean handleRetryOrFail(JobController controller, Throwable cause) {
        // Step 1: probe is_terminal — user may have already called
        // complete()/fail(); their terminal call is the source of truth.
        boolean alreadyTerminal = false;
        try {
            alreadyTerminal = controller.isTerminal();
        } catch (Throwable probeErr) {
            // probe failed; fall through to default best-effort report.
            log.debug("[mesh-jobs] is_terminal probe failed for job={}: {}",
                controller.jobId(), probeErr.toString());
        }
        if (alreadyTerminal) {
            // Already terminal: user owns the outcome. Don't double-fail.
            return false;
        }

        // Step 2 (issue #895): retryOn match → releaseLease (suppress) or
        // fail() fallback → suppress. Non-matching falls through.
        if (retryOn != null && retryOn.length > 0) {
            for (Class<? extends Throwable> cls : retryOn) {
                if (cls.isInstance(cause)) {
                    String reason = cause.getClass().getSimpleName() +
                        ": " + cause.getMessage();
                    try {
                        controller.releaseLease(reason);
                        log.info("[mesh-jobs] retryOn match for job={} ({}); released lease for fast retry",
                            controller.jobId(), reason);
                        return true;
                    } catch (Throwable releaseErr) {
                        log.warn("[mesh-jobs] release_lease failed for job={} ({}); falling back to fail()",
                            controller.jobId(), releaseErr.toString());
                        try {
                            controller.fail(
                                "retry-eligible " + reason +
                                "; release_lease failed: " + releaseErr.getMessage()
                            );
                        } catch (Throwable failErr) {
                            log.debug("[mesh-jobs] fallback fail() also failed for job={}: {}",
                                controller.jobId(), failErr.toString());
                        }
                        return true;
                    }
                }
            }
        }

        // Step 3: non-retryable → existing behaviour (best-effort fail
        // then propagate). Caller propagates the cause.
        tryFail(controller, cause.toString());
        return false;
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
    private Object convertValue(Object value, Type targetType) {
        Class<?> rawType;
        if (targetType instanceof Class<?> c) {
            rawType = c;
        } else if (targetType instanceof ParameterizedType pt) {
            rawType = (Class<?>) pt.getRawType();
        } else {
            rawType = Object.class;
        }

        if (value == null) {
            return getDefaultValue(rawType);
        }

        // Already correct type (skip for parameterized types so Jackson deserializes elements)
        if (!(targetType instanceof ParameterizedType) && rawType.isInstance(value)) {
            return value;
        }

        // Fast path for common type conversions — avoid Jackson round-trip
        if (value instanceof Number n) {
            if (rawType == Integer.class || rawType == int.class) return n.intValue();
            if (rawType == Long.class || rawType == long.class) return n.longValue();
            if (rawType == Double.class || rawType == double.class) return n.doubleValue();
        }

        // Use Jackson for complex conversions (with full generic type info)
        try {
            tools.jackson.databind.JavaType javaType = objectMapper.getTypeFactory().constructType(targetType);
            String json = objectMapper.writeValueAsString(value);
            return objectMapper.readValue(json, javaType);
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
        Type type
    ) {
        Class<?> rawType() {
            if (type instanceof Class<?> c) return c;
            if (type instanceof ParameterizedType pt) return (Class<?>) pt.getRawType();
            return Object.class;
        }
    }
}
