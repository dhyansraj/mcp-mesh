package io.mcpmesh.spring;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshJobSubmitter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
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
 *       polls {@code POST /jobs/claim} for that capability (pull-mode).</li>
 *   <li><b>Consumer side</b> — for every wrapper that declares a
 *       {@link io.mcpmesh.MeshJob}-typed parameter and at least one
 *       declared dependency, constructs a {@link MeshJobSubmitter}
 *       bound to the first declared dependency capability and calls
 *       {@link MeshToolWrapper#setJobSubmitter} so the slot is filled
 *       on each invocation (Phase 1 simplification — see contract).</li>
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

    private final Map<String, ClaimDispatcher> dispatchers = new ConcurrentHashMap<>();
    private final AtomicBoolean started = new AtomicBoolean(false);
    private final AtomicBoolean stopped = new AtomicBoolean(false);

    public JobsRuntimeManager(
            MeshRuntime runtime,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry) {
        this.runtime = runtime;
        this.toolRegistry = toolRegistry;
        this.wrapperRegistry = wrapperRegistry;
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
        //    one declared dependency gets a MeshJobSubmitter bound to
        //    dep[0] (Phase 1 simplification — Phase 2 will surface task=
        //    true status from the registry's dependency events).
        wireConsumers(instanceId, registryUrl);

        // Helper tools are registered earlier (in MeshAutoConfiguration's
        // buildAgentSpec) so the synthetic ToolSpecs make it into the
        // heartbeat catalog. Don't double-register here.
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

            // Spawn a ClaimDispatcher that invokes the same method via reflection.
            ClaimDispatcher dispatcher = new ClaimDispatcher(
                meta.capability(),
                instanceId,
                registryUrl,
                (payload, controller) -> invokeViaReflection(meta, payload, controller)
            );
            dispatcher.start();
            dispatchers.put(meta.capability(), dispatcher);
            log.info("MeshJob producer wired: capability={} (wrapper={}, dispatcher started)",
                meta.capability(), wrapper.getFuncId());
        }
    }

    private void wireConsumers(String instanceId, String registryUrl) {
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
            String depCapability = deps.get(0).capability();
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
     * Reflectively invoke the producer method for one claimed job.
     *
     * <p>Mirrors the inbound dispatch wrapper's argument-shaping logic
     * (mcp params + dep slots + MeshJob slot) — but for the claim path,
     * deps are NOT injected (the claim path is intentionally limited to
     * "user method + payload + controller"; deps would require resolving
     * them from the registry inside the dispatcher, which Phase 2 may
     * add). User methods that depend on deps AND are claim-dispatched
     * will see null deps; design.org calls this out as a Phase 1 limit.
     */
    private Object invokeViaReflection(
            MeshToolRegistry.ToolMetadata meta,
            Map<String, Object> payload,
            JobController controller) throws Exception {
        Method method = meta.method();
        Object bean = meta.bean();
        method.setAccessible(true);

        Object[] fullArgs = new Object[method.getParameterCount()];
        java.lang.reflect.Parameter[] params = method.getParameters();
        for (int i = 0; i < params.length; i++) {
            Class<?> type = params[i].getType();
            if (io.mcpmesh.MeshJob.class.isAssignableFrom(type)) {
                fullArgs[i] = controller;
                continue;
            }
            io.mcpmesh.Param paramAnn = params[i].getAnnotation(io.mcpmesh.Param.class);
            if (paramAnn != null) {
                Object val = payload != null ? payload.get(paramAnn.value()) : null;
                fullArgs[i] = coerce(val, type);
                continue;
            }
            // McpMeshTool / MeshLlmAgent on the claim path are filled with null
            // (Phase 1 limit — see method javadoc).
            fullArgs[i] = null;
        }

        try {
            Object result = method.invoke(bean, fullArgs);
            if (result instanceof java.util.concurrent.CompletableFuture<?> cf) {
                result = cf.get();
            }
            return result;
        } catch (InvocationTargetException ite) {
            Throwable cause = ite.getCause();
            if (cause instanceof Exception ex) throw ex;
            throw new RuntimeException(cause);
        }
    }

    /** Best-effort scalar coercion — identical to MeshToolWrapper's fast path. */
    private static Object coerce(Object val, Class<?> target) {
        if (val == null) {
            if (target.isPrimitive()) {
                if (target == boolean.class) return false;
                if (target == int.class) return 0;
                if (target == long.class) return 0L;
                if (target == double.class) return 0.0d;
                if (target == float.class) return 0.0f;
                if (target == short.class) return (short) 0;
                if (target == byte.class) return (byte) 0;
                if (target == char.class) return '\0';
            }
            return null;
        }
        if (target.isInstance(val)) return val;
        if (val instanceof Number n) {
            if (target == Integer.class || target == int.class) return n.intValue();
            if (target == Long.class || target == long.class) return n.longValue();
            if (target == Double.class || target == double.class) return n.doubleValue();
        }
        return val;
    }

    private MeshToolWrapper lookupWrapperForMethod(MeshToolRegistry.ToolMetadata meta) {
        // Wrappers are keyed by funcId == className.methodName
        String funcId = meta.bean().getClass().getName() + "." + meta.method().getName();
        MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);
        if (wrapper == null) {
            // Fall back via method name (covers CGLIB-proxied beans where
            // the class name diverges from the user's source class).
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
