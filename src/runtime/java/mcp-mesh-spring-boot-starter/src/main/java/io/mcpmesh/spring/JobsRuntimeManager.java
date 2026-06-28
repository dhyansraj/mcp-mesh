package io.mcpmesh.spring;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.a2a.A2AClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Lifecycle manager for the Phase B MeshJob substrate on the Java side.
 *
 * <p>Wires producer + consumer + helper-tool plumbing together once the
 * mesh runtime is up:
 *
 * <ul>
 *   <li><b>Producer side</b> — for every {@code @MeshTool(task=true)}
 *       wrapper, calls {@link MeshToolWrapper#setJobBindingContext} so
 *       inbound calls bearing {@code X-Mesh-Job-Id} can construct a
 *       {@link JobController}, AND spawns a {@link ClaimDispatcher} that
 *       polls {@code POST /jobs/claim} for that capability (pull-mode).
 *       The dispatcher delegates each claimed job back to the same
 *       {@link MeshToolWrapper} via
 *       {@link MeshToolWrapper#invokeForClaim}, so the claim path shapes
 *       arguments — {@code @Param} coercion, McpMeshTool / MeshLlmAgent
 *       dependency proxies (with settle-grace), and the
 *       {@code @A2AConsumer}-injected A2AClient — identically to the
 *       inbound (push-mode) path. A {@code task=true} producer may therefore
 *       declare dependency parameters; this mirrors Python, whose claim
 *       path re-runs the same DI-wrapped handler.</li>
 *   <li><b>Consumer side</b> — for every wrapper that declares a
 *       {@link io.mcpmesh.MeshJob}-typed parameter and at least one
 *       declared dependency, constructs a {@link MeshJobSubmitter}
 *       bound to the declared dependency capability the MeshJob slot was
 *       positionally paired with at wrapper construction
 *       ({@link MeshToolWrapper#getMeshJobDependencyCapability}) and calls
 *       {@link MeshToolWrapper#setJobSubmitter} so the slot is filled on each
 *       invocation. Binding off the DECLARED selector (not a local
 *       {@code task()} registry probe) wires the submitter whether the task
 *       producer is local or REMOTE, and regardless of how many other
 *       dependencies the consumer mixes in — mirroring Python.</li>
 *   <li><b>Helper tools</b> — invokes
 *       {@link JobsHelperToolsRegistrar#register} so every Java mesh
 *       agent advertises the three framework-internal helpers.</li>
 * </ul>
 *
 * <p>Lifecycle: starts AFTER {@link MeshRuntime} (so we know the
 * agent's per-replica id + registry URL), stops BEFORE it (so
 * dispatchers drain in-flight handlers before the runtime tears
 * down). Phase {@code MAX_VALUE - 30} sits between MeshRuntime
 * (MAX_VALUE - 100) and MeshEventProcessor (MAX_VALUE - 50) — it
 * stops earlier than both so handlers' terminal {@code complete()}
 * calls land on the registry before we lose the FFI runtime.
 */
public final class JobsRuntimeManager implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(JobsRuntimeManager.class);
    private static final int LIFECYCLE_PHASE = Integer.MAX_VALUE - 30;

    private final MeshRuntime runtime;
    private final MeshToolRegistry toolRegistry;
    private final MeshToolWrapperRegistry wrapperRegistry;
    /**
     * Retained for constructor compatibility. The claim path now resolves
     * the {@code @A2AConsumer}-injected A2AClient through the
     * {@link MeshToolWrapper} (the bean post-processor wires
     * {@link MeshToolWrapper#setA2AClientBinding} for {@code task=true}
     * wrappers too), so this manager no longer needs the processor to fill
     * A2A slots itself — the previous reflection invoker did.
     */
    @SuppressWarnings("unused")
    private final A2AConsumerBeanPostProcessor a2aProcessor;

    private final Map<String, ClaimDispatcher> dispatchers = new ConcurrentHashMap<>();
    private final AtomicBoolean started = new AtomicBoolean(false);
    private final AtomicBoolean stopped = new AtomicBoolean(false);

    public JobsRuntimeManager(
            MeshRuntime runtime,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry) {
        this(runtime, toolRegistry, wrapperRegistry, null);
    }

    /**
     * Issue #923 (historical): this overload accepted the
     * {@link A2AConsumerBeanPostProcessor} so the old claim-path reflection
     * invoker could fill {@link A2AClient} parameter slots on
     * {@code task=true @A2AConsumer} methods. The claim path now delegates to
     * {@link MeshToolWrapper#invokeForClaim}, which fills the A2A slot from the
     * binding the bean post-processor already wired onto the wrapper — so the
     * processor argument is retained only for source compatibility and may be
     * {@code null}.
     */
    public JobsRuntimeManager(
            MeshRuntime runtime,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            A2AConsumerBeanPostProcessor a2aProcessor) {
        this.runtime = runtime;
        this.toolRegistry = toolRegistry;
        this.wrapperRegistry = wrapperRegistry;
        this.a2aProcessor = a2aProcessor;
    }

    @Override
    public void start() {
        if (!started.compareAndSet(false, true)) {
            return;
        }

        String registryUrl = runtime.getAgentSpec().getRegistryUrl();
        String instanceId = runtime.getAgentSpec().getAgentId();
        if (registryUrl == null || registryUrl.isEmpty()) {
            log.info("MeshJob runtime: no registry URL — skipping job substrate wiring");
            return;
        }
        if (instanceId == null || instanceId.isEmpty()) {
            log.warn("MeshJob runtime: agent id not set — skipping job substrate wiring");
            return;
        }

        // 1. Producer-side: bind context on every task=true wrapper, spawn
        //    one ClaimDispatcher per task capability.
        wireProducers(instanceId, registryUrl);

        // 2. Consumer-side: any wrapper with a MeshJob slot AND at least
        //    one declared dependency gets a MeshJobSubmitter bound to the
        //    declared dependency capability the MeshJob slot was paired with
        //    (local OR remote task producer — see wireConsumers).
        wireConsumers(instanceId, registryUrl);

        // Helper tools are registered eagerly in MeshAutoConfiguration#meshRuntime
        // (synchronous bean-construction phase) so the synthetic handlers are
        // visible to mcpStatelessServer when it snapshots its tool list, and the
        // synthetic ToolSpecs make it into the heartbeat catalog via toolRegistry.
        // Don't double-register here.
    }

    private void wireProducers(String instanceId, String registryUrl) {
        for (MeshToolRegistry.ToolMetadata meta : toolRegistry.getAllTools()) {
            if (!meta.task()) continue;
            MeshToolWrapper wrapper = lookupWrapperForMethod(meta);
            if (wrapper == null) {
                log.warn("No wrapper found for task=true tool {}; producer dispatch will be inert",
                    meta.capability());
                continue;
            }
            wrapper.setJobBindingContext(instanceId, registryUrl);

            // Spawn a ClaimDispatcher that delegates each claimed job back to
            // the already-resolved MeshToolWrapper. The wrapper holds the
            // heartbeat-resolved McpMeshTool / MeshLlmAgent proxies (with
            // settle-grace) AND the @A2AConsumer-injected A2AClient, so the
            // claim path now shapes arguments identically to the inbound
            // (push-mode) path — a `task=true` producer can declare
            // dependency parameters and have them resolved, mirroring
            // Python's claim path (which re-runs the same DI-wrapped
            // handler). The dispatcher binds JobContext + the Rust cancel
            // registry around handle(), so invokeForClaim runs synchronously
            // on the dispatch thread with the right outbound-header / cancel
            // context — no extra thread hop.
            //
            // Issue #895: thread the @MeshTool(retryOn=...) whitelist through so
            // the claim-path matches the inbound-HTTP-path's release-and-retry
            // semantics. invokeForClaim unwraps InvocationTargetException to the
            // user exception so the dispatcher's retryOn matching still applies.
            ClaimDispatcher dispatcher = new ClaimDispatcher(
                meta.capability(),
                instanceId,
                registryUrl,
                (payload, controller) -> wrapper.invokeForClaim(
                    payload, controller, deadlineFromJobContext()),
                meta.retryOn()
            );
            dispatcher.start();
            dispatchers.put(meta.capability(), dispatcher);
            log.info("MeshJob producer wired: capability={} (wrapper={}, dispatcher started, retryOn={})",
                meta.capability(), wrapper.getFuncId(), meta.retryOn().length);
        }
    }

    // Package-private (not private) so unit tests can drive consumer-side
    // submitter wiring in isolation without spawning the producer-side
    // ClaimDispatchers (network pollers) that start() also kicks off.
    void wireConsumers(String instanceId, String registryUrl) {
        for (MeshToolRegistry.ToolMetadata meta : toolRegistry.getAllTools()) {
            MeshToolWrapper wrapper = lookupWrapperForMethod(meta);
            if (wrapper == null || wrapper.getMeshJobParamIndex() == null) continue;
            // Producer slot — the inbound dispatch path fills it with a
            // controller; nothing to wire here.
            if (meta.task()) continue;
            // Consumer needs at least one declared dependency to bind the
            // submitter. Without one, leave the slot empty (user code
            // tolerates null per the DDDI contract).
            List<MeshToolRegistry.DependencyInfo> deps = meta.dependencies();
            if (deps == null || deps.isEmpty()) continue;
            // Bind the submitter to the DECLARED dependency the user typed
            // the MeshJob slot for. The wrapper paired the MeshJob param
            // positionally with one declared dependency index at
            // construction (eligible positions = McpMeshTool + MeshJob,
            // sorted, paired to the declared dependency list) — the same
            // positional contract Python/TypeScript use. We trust that
            // declared capability rather than probing the LOCAL registry for
            // a `task=true` tool: a REMOTE task producer is invisible to the
            // local registry, so the old `task()` probe only ever wired the
            // submitter for an in-process producer (or the single-dep
            // fallback), silently leaving a remote task dep — especially one
            // mixed with other deps — with a null MeshJob slot. This mirrors
            // Python's dependency_injector, which wires the submitter off the
            // declared dependency capability at the MeshJob param's dep_index.
            String depCapability = wrapper.getMeshJobDependencyCapability();
            if (depCapability == null) {
                // Fallback for the (rare) case where the MeshJob slot has no
                // positionally-paired declared dependency (e.g. more MeshJob
                // params than declared deps): retain the legacy
                // local-task-probe / single-dep heuristic so the previously
                // working in-process happy path is preserved, not narrowed.
                depCapability = pickTaskBackedDependency(deps);
            }
            if (depCapability == null) {
                log.debug("Consumer {} declares MeshJob slot but no declared dependency backs it; " +
                    "skipping submitter wiring", meta.capability());
                continue;
            }
            try {
                MeshJobSubmitter submitter = new MeshJobSubmitter(depCapability, instanceId, registryUrl);
                wrapper.setJobSubmitter(submitter);
                log.info("MeshJob consumer wired: tool={} → MeshJobSubmitter for capability={}",
                    wrapper.getFuncId(), depCapability);
            } catch (Exception e) {
                log.warn("Failed to wire MeshJobSubmitter for {}: {}",
                    wrapper.getFuncId(), e.getMessage());
            }
        }
    }

    /**
     * Pick the capability of the first declared dependency that
     * resolves to a {@code task=true} tool in the local registry.
     * Returns {@code null} if no such dep is declared. Used by
     * {@link #wireConsumers} to bind the {@link MeshJobSubmitter} to
     * the correct slot when the consumer mixes ordinary + task deps.
     *
     * <p>The local registry only knows about THIS agent's tools; for
     * remote task=true deps the consumer should rely on the registry's
     * dependency-resolution metadata (Phase 2). Today the consumer +
     * task producer in the same agent is the only well-tested path.
     */
    private String pickTaskBackedDependency(List<MeshToolRegistry.DependencyInfo> deps) {
        for (MeshToolRegistry.DependencyInfo dep : deps) {
            MeshToolRegistry.ToolMetadata localTool = toolRegistry.getTool(dep.capability());
            if (localTool != null && localTool.task()) {
                return dep.capability();
            }
        }
        // Fallback: cross-agent task deps aren't introspectable from
        // this side without a registry round-trip. If exactly one dep
        // is declared, accept it — preserves the Phase 1 happy path
        // for the canonical "consumer + remote task producer" example
        // without reintroducing the wrong-pick bug above.
        if (deps.size() == 1) {
            return deps.get(0).capability();
        }
        return null;
    }

    /**
     * The remaining job budget bound by {@link ClaimDispatcher} around the
     * handler, surfaced from the current {@link io.mcpmesh.JobContext} snapshot
     * so {@link MeshToolWrapper#invokeForClaim} carries it for symmetry with
     * the inbound path. The actual async await
     * ({@link #awaitFutureWithJobBudget}) re-reads the context directly, so
     * this is informational — null when no deadline is bound.
     */
    private static Long deadlineFromJobContext() {
        io.mcpmesh.JobContext.Snapshot job = io.mcpmesh.JobContext.current();
        return job != null ? job.deadlineSecsRemaining : null;
    }

    /**
     * Issue #1164 MED-5: claim-path symmetry with the inbound wrapper's
     * bounded async await. The claim path previously called {@code cf.get()}
     * with no timeout — a never-completing future would pin a dispatch
     * thread forever. Bound the await to the job's actual budget
     * ({@code max_duration} from the claim, surfaced via the
     * {@link io.mcpmesh.JobContext} snapshot the dispatcher binds around
     * this handler), falling back to a generous ceiling when the job has no
     * deadline (jobs are unlimited-by-default per the registry contract, so
     * the fallback is a leak backstop, not a policy timeout). The timed-out
     * future is cancelled, which frees the dispatch thread, cancels
     * dependent stages, and turns a late {@code complete()} into a no-op —
     * {@code CompletableFuture.cancel} does NOT interrupt the thread
     * computing the value ({@code mayInterruptIfRunning} has no effect per
     * its javadoc), so orphaned producer-side work runs to completion in
     * the background.
     */
    static Object awaitFutureWithJobBudget(
            java.util.concurrent.CompletableFuture<?> cf, String capability) throws Exception {
        io.mcpmesh.JobContext.Snapshot job = io.mcpmesh.JobContext.current();
        Long budget = job != null ? job.deadlineSecsRemaining : null;
        long timeoutSecs = (budget != null && budget > 0) ? budget : NO_DEADLINE_AWAIT_CEILING_SECS;
        try {
            return cf.get(timeoutSecs, java.util.concurrent.TimeUnit.SECONDS);
        } catch (java.util.concurrent.TimeoutException te) {
            cf.cancel(true);
            throw new RuntimeException("Async operation timed out after " + timeoutSecs
                + " seconds (claim-path budget for capability '" + capability + "')");
        } catch (java.util.concurrent.ExecutionException ee) {
            // Unwrap to the user exception (mirrors MeshToolWrapper.awaitIfFuture
            // and the InvocationTargetException handling in invokeForClaim) —
            // the @MeshTool(retryOn=...) whitelist matches with cls.isInstance(cause)
            // in ClaimDispatcher.handleRetryOrFail, so a wrapped ExecutionException
            // would never match the user's declared exception types.
            Throwable cause = ee.getCause();
            if (cause instanceof Exception ex) throw ex;
            throw new RuntimeException(cause);
        } catch (InterruptedException ie) {
            // Restore the interrupt flag — the dispatcher's terminal handler
            // swallows the exception, so the flag is the only signal the
            // dispatch thread retains (mirrors MeshToolWrapper.awaitIfFuture).
            Thread.currentThread().interrupt();
            throw new RuntimeException("Async operation interrupted", ie);
        }
    }

    /**
     * Await ceiling for claim-dispatched jobs with no {@code max_duration}.
     * 24h — large enough to never strangle a legitimate long-running job,
     * small enough that a leaked never-completing future eventually frees
     * its dispatch thread.
     */
    static final long NO_DEADLINE_AWAIT_CEILING_SECS = 86_400L;

    private MeshToolWrapper lookupWrapperForMethod(MeshToolRegistry.ToolMetadata meta) {
        // Wrappers are keyed by funcId == targetClassName.methodName.
        // Unwrap AOP proxies the same way MeshToolBeanPostProcessor does when
        // constructing the wrapper key, so Spring-proxied beans
        // (Foo$$SpringCGLIB$$0) hit the primary lookup (issue #1164 MED-1).
        String funcId = org.springframework.aop.support.AopUtils.getTargetClass(meta.bean()).getName()
            + "." + meta.method().getName();
        MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);
        if (wrapper == null) {
            // Fall back via method name (defensive — covers any residual
            // key divergence between registration and lookup).
            log.debug("Wrapper lookup miss for funcId={}; falling back to method-name lookup '{}'",
                funcId, meta.method().getName());
            wrapper = wrapperRegistry.getWrapperByMethodName(meta.method().getName());
        }
        return wrapper;
    }

    @Override
    public void stop() {
        if (!stopped.compareAndSet(false, true)) {
            return;
        }
        log.info("Stopping MeshJob runtime: {} active dispatcher(s)", dispatchers.size());
        List<ClaimDispatcher> snapshot = new ArrayList<>(dispatchers.values());
        for (ClaimDispatcher d : snapshot) {
            try {
                d.close();
            } catch (Exception e) {
                log.debug("Dispatcher close raised: {}", e.getMessage());
            }
        }
        dispatchers.clear();
    }

    @Override
    public boolean isRunning() {
        return started.get() && !stopped.get();
    }

    @Override
    public int getPhase() {
        return LIFECYCLE_PHASE;
    }
}
