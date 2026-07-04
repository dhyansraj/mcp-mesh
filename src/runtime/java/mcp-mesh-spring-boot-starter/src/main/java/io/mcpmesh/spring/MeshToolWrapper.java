package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.JobContext;
import io.mcpmesh.JobController;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.core.MeshCore;
import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.spring.tracing.SpanScope;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TraceInfo;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
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
    /**
     * Default await budget for {@link CompletableFuture}-returning tools when
     * the inbound request carries no {@code X-Mesh-Timeout} budget. When the
     * header IS present, its value bounds the await instead (issue #1164 MED-5).
     */
    static final long ASYNC_TIMEOUT_SECONDS = 30;
    /**
     * CAP on the margin shaved off the propagated {@code X-Mesh-Timeout}
     * budget when awaiting a {@link CompletableFuture} result. The caller's
     * socket read timeout typically fires at roughly the same budget; ending
     * the await slightly earlier lets the structured timeout error (a proper
     * JSON-RPC error payload) reach the caller instead of racing — and
     * losing to — the caller's transport-level timeout, which surfaces as an
     * opaque read-timeout IOException (#1164 review follow-up).
     *
     * <p>The actual margin is proportional — {@code min(cap, budget/10)} —
     * so small budgets keep most of their window: a fixed 2s margin ate 2/3
     * of a 3s budget. Tiny budgets (under 10s) get little or no margin and
     * accept the socket-timeout race; that trade beats forfeiting the
     * useful await time.
     */
    static final long ASYNC_AWAIT_MARGIN_SECS = 2;
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

    // Per declared-dependency-index required flags (issue #1268), parallel to
    // {@link #dependencyNames}. Threaded by {@link MeshToolBeanPostProcessor}
    // from {@code @MeshTool(dependencies=...)} {@code Selector.required()}.
    // All-false (optional) until set, so the claim gate is a no-op for tools
    // with no required deps and for the many test constructors that never set
    // it. Consulted by {@link #requiredDepsResolved()} (pre-claim gate) and
    // {@link #invokeForClaim} (pre-invoke safety net).
    private volatile boolean[] dependencyRequired;

    // Positional pairing between the DECLARED dependency list and this
    // method's injectable slots (issue #1193 fix round). Declared
    // dependencies pair positionally with injectable parameters
    // (McpMeshTool + MeshJob) in parameter order — the same contract as
    // Python/TypeScript. The two index spaces differ whenever a MeshJob
    // dependency is declared: e.g. dependencies = ["job_cap", "db_cap"]
    // with params (MeshJob job, McpMeshTool db) has db_cap at DECLARED
    // index 1 but McpMeshTool SLOT ordinal 0. Registry events carry the
    // declared index; injectedDeps/meshToolReturnTypes are slot-ordinal
    // arrays — these tables translate between the two.
    /** Declared dep index → McpMeshTool slot ordinal; -1 = no proxy slot (MeshJob-backed or excess). */
    private final int[] depIndexToSlot;
    /** McpMeshTool slot ordinal → declared dep index; -1 = no declared dependency backs the slot. */
    private final int[] slotToDepIndex;
    /**
     * Declared dependency index paired with the {@code MeshJob} parameter
     * position, or -1 when this method has no MeshJob slot OR the slot has no
     * declared dependency backing it. The MeshJob param consumes one declared
     * dependency index via the SAME positional pairing the McpMeshTool slots
     * use (eligible positions = McpMeshTool + MeshJob, sorted, paired to the
     * declared dependency list). This lets the consumer-side
     * {@link JobsRuntimeManager} wiring bind the {@link MeshJobSubmitter} to
     * the EXACT declared capability the user typed {@code MeshJob} for —
     * mirroring Python, which keys the submitter off the declared dependency
     * capability at the MeshJob param's dep_index rather than a local
     * {@code task()} registry probe.
     */
    private final int meshJobDepIndex;

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

    // Issue #923: @A2AConsumer-injected A2AClient. The slot index is
    // captured at construction time by analyzeParameters (so the
    // parameter is exempt from the MCP input schema). The client itself
    // is bound lazily by MeshToolBeanPostProcessor once the
    // A2AConsumerBeanPostProcessor has finished computing the cached
    // instance for this method's (url, skillId, auth, timeout) tuple.
    private Integer a2aClientParamIndex;
    private final AtomicReference<A2AClient> a2aClient = new AtomicReference<>();

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
        // Default all-optional (#1268) until MeshToolBeanPostProcessor threads
        // the per-dep required flags via setDependencyRequired.
        this.dependencyRequired = new boolean[this.dependencyNames.size()];
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

        // Build the declared-index ↔ slot-ordinal translation (see field
        // javadoc). Eligible positions = McpMeshTool + MeshJob parameter
        // positions in parameter order; dependencies[k] pairs with the
        // k-th eligible position.
        this.depIndexToSlot = new int[this.dependencyNames.size()];
        this.slotToDepIndex = new int[meshToolPositions.size()];
        Arrays.fill(this.depIndexToSlot, -1);
        Arrays.fill(this.slotToDepIndex, -1);
        List<Integer> eligiblePositions = new ArrayList<>(meshToolPositions);
        if (meshJobParamIndex != null) {
            eligiblePositions.add(meshJobParamIndex);
            Collections.sort(eligiblePositions);
        }
        int meshJobDep = -1;
        for (int k = 0; k < eligiblePositions.size() && k < this.dependencyNames.size(); k++) {
            int paramPos = eligiblePositions.get(k);
            if (meshJobParamIndex != null && paramPos == meshJobParamIndex) {
                // MeshJob-backed dependency: the submitter is wired
                // locally (JobsRuntimeManager), never by a proxy event —
                // no slot, no settle key. Capture the declared dependency
                // index paired with the MeshJob param so the consumer-side
                // wiring can bind the submitter to the EXACT declared
                // capability (mirrors Python's positional MeshJob→dep_index).
                meshJobDep = k;
                continue;
            }
            int slot = meshToolPositions.indexOf(paramPos);
            this.depIndexToSlot[k] = slot;
            this.slotToDepIndex[slot] = k;
        }
        this.meshJobDepIndex = meshJobDep;

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
            } else if (A2AClient.class.isAssignableFrom(type)) {
                // Issue #923: @A2AConsumer-injected A2AClient slot. The
                // index is captured here so the dispatch wrapper can
                // populate it from the cached client; the parameter is
                // exempt from the MCP input schema. Multiple A2AClient
                // params are an error — the bean post-processor enforces
                // exactly-one at boot, but the wrapper rejects defensively
                // in case the wrapper is constructed without going through
                // it (e.g. unit tests).
                if (!method.isAnnotationPresent(A2AConsumer.class)) {
                    // An A2AClient parameter without @A2AConsumer has no
                    // upstream URL/auth/timeout to bind to — the dispatch
                    // wrapper would silently inject null and the user
                    // method would NPE on the first call. Fail BOOT, not
                    // runtime, so the misuse is visible immediately.
                    throw new IllegalStateException(
                        "MeshTool method " + method.getName() + " has an A2AClient parameter "
                            + "but is not annotated with @A2AConsumer. A2AClient injection requires "
                            + "@A2AConsumer to declare the upstream URL + auth config (issue #923).");
                }
                if (a2aClientParamIndex != null) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " declares more than one A2AClient parameter; "
                            + "exactly one is required (issue #923).");
                }
                a2aClientParamIndex = i;
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
     *
     * <p>Issue #1164 MED-2: delegates to the shared builder in
     * {@link MeshSchemaSupport#buildToolInputSchema} — the SAME method the
     * heartbeat catalog ({@link MeshToolRegistry}) uses — so the MCP-served
     * schema and the registry-advertised schema can never drift. The shared
     * builder selects exactly the {@code @Param}-annotated parameters, which
     * is the same set as {@link #analyzeParameters}' {@code mcpParams}
     * (injectable types are exempt; non-injectable params without
     * {@code @Param} were already rejected at construction time).
     */
    private Map<String, Object> generateInputSchema() {
        return MeshSchemaSupport.buildToolInputSchema(method);
    }

    // =========================================================================
    // Dependency Updates (called by heartbeat)
    // =========================================================================

    /**
     * Update a McpMeshTool dependency at the given DECLARED index.
     * Called by MeshToolWrapperRegistry when heartbeat resolves a dependency.
     *
     * <p>The declared index is translated to the McpMeshTool slot ordinal
     * (they differ when a MeshJob dependency is declared — see
     * {@link #depIndexToSlot}). Updates for MeshJob-backed or excess
     * declared indices are ignored: a job dependency's resolution event
     * must never land a proxy in (or evict) another parameter's slot.
     *
     * <p>Settling-window grace (#1193): a non-null available proxy counts
     * down the per-consumer-slot settle latch ({@code funcId:dep_N}) AFTER
     * the array slot is written, so a settling call woken by the latch
     * re-reads a populated slot. Per-slot keying means only THIS wrapper's
     * waiters wake — another tool sharing the capability keeps waiting for
     * its own slot's event.
     *
     * @param depIndex The dependency index (0-based, in declaration order)
     * @param proxy    The resolved proxy (or null if unavailable)
     */
    @SuppressWarnings("rawtypes")
    public void updateDependency(int depIndex, McpMeshTool proxy) {
        if (depIndex < 0 || depIndex >= depIndexToSlot.length) {
            return;
        }
        int slot = depIndexToSlot[depIndex];
        if (slot < 0) {
            log.debug("Ignoring dependency update at declared index {} for {} — "
                + "no McpMeshTool slot (MeshJob-backed or excess dependency)",
                depIndex, funcId);
            return;
        }
        injectedDeps.set(slot, proxy);
        log.debug("Updated dependency {} at declared index {} (slot {}) for {}",
            proxy != null ? proxy.getCapability() : "null", depIndex, slot, funcId);
        if (proxy != null && proxy.isAvailable()) {
            MeshSettleState.getInstance().markResolved(
                MeshToolWrapperRegistry.buildDependencyKey(funcId, depIndex));
        }
    }

    /**
     * Thread the per-declared-dependency {@code required} flags (issue #1268)
     * from {@code @MeshTool(dependencies=...)} {@code Selector.required()}.
     * The list is positional to the DECLARED dependency list (the same order
     * as {@code dependencyNames}); shorter/longer lists are tolerated (missing
     * entries default optional). Called once at wrapper registration by
     * {@link MeshToolBeanPostProcessor}.
     *
     * @param required per-declared-dependency required flags, or null (no-op)
     */
    public void setDependencyRequired(List<Boolean> required) {
        if (required == null) {
            return;
        }
        boolean[] flags = new boolean[dependencyNames.size()];
        for (int i = 0; i < flags.length && i < required.size(); i++) {
            flags[i] = Boolean.TRUE.equals(required.get(i));
        }
        this.dependencyRequired = flags;
    }

    /**
     * Issue #1268 pre-claim / pre-invoke gate: whether every {@code required}
     * McpMeshTool dependency slot is locally resolved — non-null AND
     * {@link McpMeshTool#isAvailable()} (the same notion the route interceptor
     * enforces at {@code MeshRouteHandlerInterceptor}). Optional slots never
     * gate. Consulted by the {@link ClaimDispatcher} before each
     * {@code /jobs/claim} attempt so a job whose required dep is momentarily
     * unresolved stays queued (no owner, no attempt burn) and self-heals on a
     * later poll.
     *
     * @return true when all required deps are resolved (safe to claim/invoke)
     */
    public boolean requiredDepsResolved() {
        return firstUnresolvedRequiredDependency() == null;
    }

    /**
     * The capability name of the first {@code required} McpMeshTool dependency
     * that is currently unresolved (null slot OR present-but-{@code !isAvailable()}),
     * or {@code null} when every required dep is resolved (issue #1268).
     * Package-private: method-referenced by {@link JobsRuntimeManager} to gate
     * the claim loop with a named reason, and asserted directly in unit tests.
     */
    @SuppressWarnings("rawtypes")
    String firstUnresolvedRequiredDependency() {
        boolean[] req = this.dependencyRequired;
        for (int slot = 0; slot < meshToolPositions.size(); slot++) {
            int depIdx = slotToDepIndex[slot];
            if (depIdx < 0 || depIdx >= req.length || !req[depIdx]) {
                continue;
            }
            McpMeshTool proxy = injectedDeps.get(slot);
            if (proxy == null || !proxy.isAvailable()) {
                return dependencyNames.get(depIdx);
            }
        }
        return null;
    }

    /**
     * Build the structured {@code dependency_unavailable} tool result (issue
     * #1273) for a required dependency that is unresolved at direct-invoke
     * time. Same semantic class as the {@code @MeshRoute} perimeter's 503 body
     * {@code {"error":"dependency_unavailable","capability":"<cap>"}}; surfaced
     * here as an {@code isError=true} {@link CallToolResult} whose single
     * {@link TextContent} carries that JSON, so callers classify it as
     * retryable topology rather than an application failure.
     */
    private CallToolResult dependencyUnavailableResult(String capability) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", "dependency_unavailable");
        body.put("capability", capability);
        String json;
        try {
            json = objectMapper.writeValueAsString(body);
        } catch (Exception e) {
            // Trivial two-scalar map — serialization never realistically fails,
            // but fall back to a hand-built envelope so the contract holds.
            json = "{\"error\":\"dependency_unavailable\",\"capability\":\""
                + capability + "\"}";
        }
        return new CallToolResult(List.of(new TextContent(json)), true, null, null);
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

    /**
     * The currently-wired consumer-side {@link MeshJobSubmitter}, or
     * {@code null} when none has been wired. Package-private — exposed for
     * the {@link JobsRuntimeManager} consumer-wiring unit tests to assert the
     * submitter is bound (and targets the declared capability) without
     * driving a full invocation.
     */
    MeshJobSubmitter getJobSubmitter() {
        return this.jobSubmitter.get();
    }

    /** Whether this tool is registered with {@code task=true}. */
    public boolean isTask() {
        return task;
    }

    /** The position of the MeshJob param in the method signature, or null. */
    public Integer getMeshJobParamIndex() {
        return meshJobParamIndex;
    }

    /**
     * The DECLARED dependency capability paired with this method's
     * {@code MeshJob} parameter via positional pairing, or {@code null} when
     * the method has no MeshJob slot OR no declared dependency backs it.
     *
     * <p>Used by the consumer-side {@link JobsRuntimeManager} wiring to bind
     * the {@link MeshJobSubmitter} to the exact capability the user declared
     * for the MeshJob slot — independent of whether the producer is local or
     * remote, and regardless of how many other dependencies the method
     * declares. This mirrors Python's {@code dependency_injector}, which wires
     * the submitter off the declared dependency capability at the MeshJob
     * param's dep_index rather than a local {@code task()} registry probe.
     */
    public String getMeshJobDependencyCapability() {
        if (meshJobDepIndex < 0 || meshJobDepIndex >= dependencyNames.size()) {
            return null;
        }
        return dependencyNames.get(meshJobDepIndex);
    }

    /**
     * Issue #923: bind the cached {@link A2AClient} that {@code @A2AConsumer}
     * provisioned for this method. Called by {@link MeshToolBeanPostProcessor}
     * once {@link A2AConsumerBeanPostProcessor} has finished computing the
     * binding. Throws if the wrapper's analysed signature did not include
     * an A2AClient slot — keeps the binding wiring honest.
     *
     * @param paramIndex slot index reported by the bean post-processor;
     *                   must match the wrapper's own analysis.
     * @param client     the cached client to inject at dispatch time.
     */
    public void setA2AClientBinding(int paramIndex, A2AClient client) {
        if (a2aClientParamIndex == null) {
            throw new IllegalStateException(
                "Cannot bind A2AClient on " + funcId
                    + ": method has no A2AClient parameter slot to inject into.");
        }
        if (a2aClientParamIndex != paramIndex) {
            throw new IllegalStateException(
                "A2AClient binding mismatch for " + funcId
                    + ": wrapper analysed slot=" + a2aClientParamIndex
                    + " but post-processor reported slot=" + paramIndex);
        }
        this.a2aClient.set(client);
    }

    /** The position of the A2AClient param in the method signature, or null. */
    public Integer getA2AClientParamIndex() {
        return a2aClientParamIndex;
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
        // Issue #1164 MED-5: parse the propagated X-Mesh-Timeout budget for
        // EVERY inbound call (not only job dispatch) so CompletableFuture-
        // returning tools are awaited against the caller's actual budget
        // instead of the hard-coded 30s default.
        Long deadlineSecs = null;
        if (propagated != null) {
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
            // Claim generation minted by the registry on POST /jobs/claim
            // (issue #1252). Java's own claim path (ClaimDispatcher) invokes
            // handlers directly and fences via JobController.open(..., epoch) —
            // it never writes this header. So x-mesh-claim-epoch is currently
            // populated only by cross-runtime propagation, i.e. a Python/TS
            // claim dispatcher (which re-enters its wrapper and seeds the
            // header) forwarding into a Java tool. Absent ⇒ null ⇒ legacy
            // owner-only fencing; never fabricate a 0. Parse kept regardless
            // (harmless, future-proof). NOTE (#1263): the calling-job identity
            // carrier (x-mesh-calling-*) is intentionally SEPARATE from this
            // protocol pair and never feeds this dispatch gate.
            Long claimEpoch = parseClaimEpochHeader(
                propagated != null ? propagated.get("x-mesh-claim-epoch") : null);
            return dispatchAsJob(cleanArgs, jobIdHeader, deadlineSecs, claimEpoch);
        }

        // Build full argument array (MCP params + deps + LLM agents + a2a
        // client). This runs the per-slot settle-grace wait (#1193), so a
        // still-settling required dependency is given its full window before
        // the guard below judges it — a fresh agent restart must block-then-
        // succeed, not burst-refuse.
        Object[] fullArgs = buildFullArgs(cleanArgs);

        // Issue #1273: direct-invoke required-dependency guard — evaluated
        // AFTER buildFullArgs (i.e. AFTER settle grace), mirroring Python/TS
        // and the @MeshRoute perimeter, all of which guard post-settle. The
        // claim path ({@link #invokeForClaim}, #1268) and the route interceptor
        // ({@link MeshRouteHandlerInterceptor}'s 503) already refuse before a
        // handler can observe a null REQUIRED dependency — the plain tools/call
        // dispatch did not. A required dep flapping DOWN→UP flips the registry
        // view to available before THIS callee's own heartbeat refills its
        // injection slot; a call landing in that ~sub-second window would invoke
        // the handler with a null required proxy (an NPE-shaped 500 the caller
        // can't classify). Refuse instead with the SAME dependency_unavailable
        // semantic class as the route perimeter — surfaced here as an
        // isError=true CallToolResult whose text carries
        // {"error":"dependency_unavailable","capability":"<cap>"} so callers
        // classify it as retryable topology, not application failure. Optional
        // deps keep their null-passthrough. Routes never reach here (the
        // interceptor 503s earlier, so no double-guard); the job-dispatch path
        // guards separately (release-the-lease) and the claim path is unchanged.
        String missingRequired = firstUnresolvedRequiredDependency();
        if (missingRequired != null) {
            log.warn("Direct-invoke guard for {}: required dependency '{}' unavailable "
                + "at invocation time — refusing with dependency_unavailable (not "
                + "invoking the handler with a null required proxy)", funcId, missingRequired);
            return dependencyUnavailableResult(missingRequired);
        }

        // Phase B MeshJob substrate: fill MeshJob slot for non-job paths.
        // - Consumer side (method has dependencies + jobSubmitter set): inject submitter.
        // - Otherwise (incl. task=true called sync): inject null.
        if (meshJobParamIndex != null) {
            fullArgs[meshJobParamIndex] = jobSubmitter.get(); // null when no submitter wired
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

        // Handle async results (CompletableFuture) — bounded by the inbound
        // X-Mesh-Timeout budget when present (issue #1164 MED-5).
        result = awaitIfFuture(result, deadlineSecs);

        return result;
    }

    /**
     * Build the full argument array for the user method: MCP parameters,
     * the @A2AConsumer-injected A2AClient slot, McpMeshTool dependencies,
     * and MeshLlmAgent dependencies (with template-context wiring).
     *
     * <p>The MeshJob slot ({@link #meshJobParamIndex}) is intentionally
     * left untouched here — the caller fills it (submitter, controller, or
     * null) depending on the invocation path. Array index assignment is
     * order-independent, so collecting the rest of the fills here is safe.
     */
    private Object[] buildFullArgs(Map<String, Object> cleanArgs) throws Exception {
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

        // Issue #923: fill the @A2AConsumer-injected A2AClient slot, if any.
        // The bean post-processor has already validated the binding; the
        // null-guard here is defensive (e.g. wrapper constructed without
        // going through the post-processor in unit tests).
        if (a2aClientParamIndex != null) {
            fullArgs[a2aClientParamIndex] = a2aClient.get();
        }

        // Fill McpMeshTool dependencies (null if unavailable for graceful degradation)
        MeshSettleState settleState = MeshSettleState.getInstance();
        for (int i = 0; i < meshToolPositions.size(); i++) {
            int paramPos = meshToolPositions.get(i);
            McpMeshTool proxy = injectedDeps.get(i);
            // Declared dependency index backing this slot — NOT i: the two
            // index spaces skew when a MeshJob dependency is declared
            // (e.g. ["job_cap", "db_cap"] puts db_cap at declared index 1
            // but slot ordinal 0). -1 = slot has no declared dependency.
            int depIdx = slotToDepIndex[i];

            // Settling-window grace (#1193): while the agent is still
            // settling, block — bounded by the remaining settle budget — on
            // THIS consumer slot's latch (composite funcId:dep_N key,
            // counted down by updateDependency AFTER it writes the slot),
            // then re-read the slot. A proxy may exist but be unavailable
            // (endpoint not yet landed), so the wait is keyed on
            // AVAILABILITY, not just null-ness. No-op (single latch check)
            // once settled — fail-fast behavior is unchanged. Blocking is
            // fine here: tool dispatch runs on Spring's request pool,
            // never an event loop.
            if ((proxy == null || !proxy.isAvailable())
                    && depIdx >= 0
                    && !settleState.isSettled()) {
                settleState.awaitDependency(
                    MeshToolWrapperRegistry.buildDependencyKey(funcId, depIdx),
                    dependencyNames.get(depIdx));
                proxy = injectedDeps.get(i);
            }

            // Allow null for graceful degradation - tool method can check:
            //   if (dep != null && dep.isAvailable()) { ... } else { fallback }
            if (proxy == null) {
                String depName = depIdx >= 0 ? dependencyNames.get(depIdx) : "unknown";
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

        return fullArgs;
    }

    /**
     * Claim-path entry point: build the user method's full argument array
     * (the SAME shaping the inbound path uses — {@code @Param} coercion,
     * McpMeshTool / MeshLlmAgent dependency slots WITH settle-grace, and the
     * {@code @A2AConsumer}-injected A2AClient slot), place the producer
     * {@link JobController} at the MeshJob slot, invoke the method, and await
     * a {@link CompletableFuture} result on the JOB budget.
     *
     * <p>This replaces the old thin reflection invoker in
     * {@link JobsRuntimeManager} so claim-dispatched {@code task=true}
     * producers resolve their dependency proxies exactly like the inbound
     * (push-mode) path does — mirroring Python, whose claim path re-runs the
     * same DI-wrapped handler. The wrapper already holds the heartbeat-
     * resolved proxies and the settle latches, so delegating here is what
     * makes a {@code task=true} producer with {@code McpMeshTool} /
     * {@code MeshLlmAgent} dependencies work.
     *
     * <p>Runs synchronously on the dispatch thread so the injected proxies'
     * outbound calls inherit the {@code X-Mesh-Job-Id} header and cancel
     * binding that {@link ClaimDispatcher} established around this call
     * (via {@code runAsJobWithRegistryBinding} + {@code JobContext.withJob}).
     * No new thread hops are introduced.
     *
     * <p>The await uses {@link JobsRuntimeManager#awaitFutureWithJobBudget}
     * (24h {@code NO_DEADLINE_AWAIT_CEILING_SECS} ceiling, or the job's
     * {@code max_duration} when present via the bound {@link JobContext}),
     * NOT the wrapper's 30s inbound default — a long-running job must not be
     * strangled by the push-path timeout.
     *
     * @param payload      The {@code submitted_payload} from the claim
     * @param controller   The producer controller bound to the claimed job
     * @param deadlineSecs The job's {@code max_duration} budget (or null);
     *                     the await reads it from the bound {@link JobContext}
     *                     that the dispatcher established, so this is carried
     *                     for symmetry with the inbound path's signature.
     * @return The user method's (await-unwrapped) result
     * @throws Exception the user exception, unwrapped from
     *                   {@link InvocationTargetException} so
     *                   {@link ClaimDispatcher}'s {@code retryOn} matching works
     */
    Object invokeForClaim(Map<String, Object> payload, JobController controller, Long deadlineSecs)
            throws Exception {
        return invokeForClaim(payload, controller, deadlineSecs,
            reason -> {
                if (controller != null) {
                    controller.releaseLease(reason);
                }
            });
    }

    /**
     * Claim-path entry point with an injectable lease-release action
     * (issue #1268). The {@code leaseReleaser} seam lets unit tests assert the
     * pre-invoke guard's release path without an FFI-backed
     * {@link JobController}; the production overload above supplies
     * {@link JobController#releaseLease(String)}.
     *
     * <p><b>Pre-invoke required-dependency guard (safety net):</b> the claim
     * gate ({@link #requiredDepsResolved()}) and the consumer's local proxy
     * injection run on two independent clocks, so a required dep flapping
     * DOWN→UP can grant a claim whose slot is still null at invocation time. If
     * a required slot is null/unavailable here, do NOT invoke the handler (it
     * would observe a null required proxy and NPE) and do NOT {@code fail()}
     * (terminal by design — that would reproduce the very bug this guards). The
     * lease is released so the job returns to the queue (retryable while budget
     * remains) and self-heals once the proxy lands.
     */
    Object invokeForClaim(Map<String, Object> payload, JobController controller, Long deadlineSecs,
                          java.util.function.Consumer<String> leaseReleaser)
            throws Exception {
        String missing = firstUnresolvedRequiredDependency();
        if (missing != null) {
            log.warn("Claim-invoke guard for {}: required dependency '{}' unavailable at "
                + "invocation time — releasing lease so the job re-queues (NOT failing; "
                + "a handler exception would be terminal by design)", funcId, missing);
            leaseReleaser.accept("required dependency unavailable: " + missing);
            return null;
        }
        Object[] fullArgs = buildFullArgs(payload != null ? payload : Map.of());
        if (meshJobParamIndex != null) {
            fullArgs[meshJobParamIndex] = controller;
        }
        Object result;
        try {
            result = method.invoke(bean, fullArgs);
        } catch (InvocationTargetException e) {
            // Unwrap to the user exception so ClaimDispatcher's retryOn
            // matching (cls.isInstance(cause)) still works — a wrapped
            // InvocationTargetException would never match the user's
            // declared exception types.
            Throwable cause = e.getCause();
            if (cause instanceof Exception ex) throw ex;
            throw new RuntimeException(cause);
        } catch (IllegalAccessException e) {
            throw new RuntimeException("Method access denied: " + e.getMessage(), e);
        }
        if (result instanceof CompletableFuture<?> cf) {
            // Job budget, NOT the wrapper's 30s inbound default.
            result = JobsRuntimeManager.awaitFutureWithJobBudget(cf, capability);
        }
        return result;
    }

    /**
     * Await a {@link CompletableFuture} result, unwrapping execution /
     * interruption failures to match the synchronous invocation's exception
     * contract. Non-future results pass through.
     *
     * <p>Issue #1164 MED-5: the await is bounded by the caller's propagated
     * {@code X-Mesh-Timeout} budget when present, falling back to
     * {@link #ASYNC_TIMEOUT_SECONDS} when absent. The timed-out future is
     * cancelled, which frees this dispatch thread, cancels dependent stages,
     * and turns a late {@code complete()} into a no-op. Note that
     * {@link CompletableFuture#cancel} does NOT interrupt whatever thread is
     * computing the value ({@code mayInterruptIfRunning} has no effect per
     * its javadoc) — orphaned producer-side work runs to completion in the
     * background.
     *
     * @param budgetSecs await budget in seconds, or null for the default
     */
    static Object awaitIfFuture(Object result, Long budgetSecs) throws Exception {
        if (result instanceof CompletableFuture<?> future) {
            long timeoutSecs = effectiveAsyncAwaitSecs(budgetSecs);
            try {
                return future.get(timeoutSecs, TimeUnit.SECONDS);
            } catch (TimeoutException e) {
                future.cancel(true);
                throw new RuntimeException("Async operation timed out after " + timeoutSecs + " seconds");
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

    /**
     * Effective async-await budget: the propagated {@code X-Mesh-Timeout} /
     * job deadline when present and positive, otherwise the
     * {@link #ASYNC_TIMEOUT_SECONDS} default (issue #1164 MED-5).
     *
     * <p>A present budget is reduced by a proportional margin —
     * {@code min(}{@link #ASYNC_AWAIT_MARGIN_SECS}{@code , budget/10)},
     * floor 1s — so the structured timeout error wins the race against the
     * caller's socket read timeout without eating most of a small budget;
     * see the margin constant's javadoc.
     */
    static long effectiveAsyncAwaitSecs(Long budgetSecs) {
        if (budgetSecs == null || budgetSecs <= 0) {
            return ASYNC_TIMEOUT_SECONDS;
        }
        long margin = Math.min(ASYNC_AWAIT_MARGIN_SECS, budgetSecs / 10);
        return Math.max(1L, budgetSecs - margin);
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
    private Object dispatchAsJob(Map<String, Object> cleanArgs, String jobId, Long deadlineSecs,
                                Long claimEpoch) throws Exception {
        // Build full args (MCP params + deps + LLM agents + a2a client);
        // the MeshJob slot is filled below with the controller or null.
        Object[] fullArgs = buildFullArgs(cleanArgs);

        // Decide whether we can build a JobController: we need a slot
        // index AND both binding fields. If any piece is missing the
        // job is still routed through the wrap (so outbound calls
        // propagate the right headers via JobContext) but without the
        // controller — see the gate-site javadoc. (PR #891 review.)
        boolean canInjectController = meshJobParamIndex != null
            && instanceId.get() != null
            && registryUrl.get() != null;

        // Issue #1273: required-dependency guard on the inbound JOB-header path
        // (task tool called with X-Mesh-Job-Id — cross-runtime claim
        // propagation). Settle grace already ran (buildFullArgs). A still-
        // unresolved required dep here must NOT invoke the handler with a null
        // proxy — and because this is a JOB-flavored invocation (the row is
        // claimed / `working`), the correct recovery is to RELEASE THE LEASE so
        // the job re-queues (retryable), mirroring {@link #invokeForClaim} and
        // the claim dispatcher. Never a tool-error refusal and never a terminal
        // fail (which would reproduce the very race the guard prevents). When
        // the controller wiring is incomplete there is no lease to manage — the
        // job re-queues on lease expiry instead.
        String missingRequiredJob = firstUnresolvedRequiredDependency();
        if (missingRequiredJob != null) {
            log.warn("Job-dispatch guard for tool={} job={}: required dependency "
                + "'{}' unavailable at invocation time — releasing lease so the job "
                + "re-queues (NOT invoking, NOT failing)", funcId, jobId, missingRequiredJob);
            if (canInjectController) {
                JobController controller = JobController.open(
                    jobId, instanceId.get(), registryUrl.get(), claimEpoch);
                try {
                    controller.releaseLease(
                        "required dependency unavailable: " + missingRequiredJob);
                } finally {
                    controller.close();
                }
            } else {
                log.warn("Job-dispatch guard for tool={} job={}: cannot release lease "
                    + "(controller wiring incomplete); job re-queues on lease expiry",
                    funcId, jobId);
            }
            return null;
        }

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
            JobContext.Snapshot snap = new JobContext.Snapshot(jobId, deadlineSecs, claimEpoch);
            return runAsJobWithRegistryBinding(jobId, deadlineSecs, claimEpoch,
                () -> JobContext.withJob(snap, () -> invokeNoController(fullArgs, deadlineSecs)));
        }

        // Construct the producer controller. Free in finally. Fenced to the
        // claim generation when present (issue #1252). Free in finally.
        JobController controller = JobController.open(jobId, instanceId.get(), registryUrl.get(), claimEpoch);
        try {
            // Inject the controller at the MeshJob slot
            fullArgs[meshJobParamIndex] = controller;

            // Bind both the Rust-side cancel registry (via mesh_run_as_job)
            // and the Java-side ThreadLocal job context (via JobContext.withJob)
            // for the duration of the user method. See class javadoc on
            // dispatchAsJob for the rationale (resolved via #889).
            JobContext.Snapshot snap = new JobContext.Snapshot(jobId, deadlineSecs, claimEpoch);
            try {
                return runAsJobWithRegistryBinding(jobId, deadlineSecs, claimEpoch,
                    () -> JobContext.withJob(snap, () -> invokeAndAutoComplete(fullArgs, controller, deadlineSecs)));
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
            String jobId, Long deadlineSecs, Long claimEpoch,
            java.util.concurrent.Callable<Object> body)
            throws Exception {
        String snapshotJson = buildRunAsJobSnapshot(jobId, deadlineSecs, claimEpoch);
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
    private String buildRunAsJobSnapshot(String jobId, Long deadlineSecs, Long claimEpoch) {
        try {
            Map<String, Object> snap = new LinkedHashMap<>();
            snap.put("job_id", jobId);
            snap.put("deadline_secs", deadlineSecs);
            // Additive (issue #1252): carry the claim generation so the Rust
            // JobContext exposes it via mesh_current_job. null ⇒ legacy.
            snap.put("claim_epoch", claimEpoch);
            return objectMapper.writeValueAsString(snap);
        } catch (Exception e) {
            throw new IllegalStateException(
                "failed to serialize mesh_run_as_job snapshot for job=" + jobId, e);
        }
    }

    /**
     * Parse the propagated {@code x-mesh-claim-epoch} header (issue #1252)
     * into a {@link Long} claim generation, or {@code null} when absent /
     * malformed / negative. Only a registry-minted non-negative generation is
     * a real epoch — a genuine {@code 0} is valid; never fabricate one the
     * registry didn't mint (a bad value degrades to legacy owner-only fencing).
     */
    static Long parseClaimEpochHeader(String raw) {
        if (raw == null || raw.isEmpty()) {
            return null;
        }
        try {
            long parsed = Long.parseLong(raw.trim());
            return parsed >= 0 ? parsed : null;
        } catch (NumberFormatException nfe) {
            return null;
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
    private Object invokeNoController(Object[] fullArgs, Long deadlineSecs) throws Exception {
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
        result = awaitIfFuture(result, deadlineSecs);
        return result;
    }

    private Object invokeAndAutoComplete(Object[] fullArgs, JobController controller, Long deadlineSecs) throws Exception {
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
            // Issue #1164 MED-5: await against the job's actual budget
            // (X-Mesh-Timeout / deadline) instead of the hard-coded 30s.
            // Cancelling the timed-out future frees this dispatch thread,
            // cancels dependent stages, and makes a late complete() a no-op
            // — it does NOT interrupt the running work (CompletableFuture
            // cancel semantics); orphaned work runs to completion.
            long timeoutSecs = effectiveAsyncAwaitSecs(deadlineSecs);
            try {
                result = future.get(timeoutSecs, TimeUnit.SECONDS);
            } catch (TimeoutException e) {
                future.cancel(true);
                tryFail(controller, "async operation timed out after " + timeoutSecs + "s");
                throw new RuntimeException("Async operation timed out after " + timeoutSecs + " seconds");
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
     * Get the expected return type for a dependency at the given DECLARED index.
     *
     * <p>This is extracted from the generic type parameter of McpMeshTool&lt;T&gt;.
     * For example, for {@code McpMeshTool<Integer>}, this returns {@code Integer.class}.
     *
     * <p>The declared index is translated to the McpMeshTool slot ordinal
     * (the spaces skew when a MeshJob dependency is declared — see
     * {@link #depIndexToSlot}).
     *
     * @param depIndex The dependency index (0-based, in declaration order)
     * @return The return type, or null if not specified or index out of bounds
     */
    public Type getDependencyReturnType(int depIndex) {
        if (depIndex >= 0 && depIndex < depIndexToSlot.length) {
            int slot = depIndexToSlot[depIndex];
            if (slot >= 0 && slot < meshToolReturnTypes.size()) {
                return meshToolReturnTypes.get(slot);
            }
        }
        return null;
    }

    /**
     * Declared dependency indices backed by McpMeshTool slots — the
     * indices whose composite keys ({@code funcId:dep_N}) participate in
     * the settling-window grace (#1193). MeshJob-backed dependencies are
     * excluded (the submitter is constructed locally, no resolution event
     * will ever arrive for the slot), as are excess dependencies with no
     * parameter to land in.
     */
    List<Integer> getSettleDepIndices() {
        List<Integer> indices = new ArrayList<>();
        for (int depIndex = 0; depIndex < depIndexToSlot.length; depIndex++) {
            if (depIndexToSlot[depIndex] >= 0) {
                indices.add(depIndex);
            }
        }
        return indices;
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
