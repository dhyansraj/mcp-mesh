package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Wave-1 A2 cover: a Java consumer that declares a dependency on a REMOTE
 * {@code task=true} capability — MIXED with another ordinary dependency —
 * must get a {@link MeshJobSubmitter} wired into its {@link MeshJob}-typed
 * slot, bound to the DECLARED task capability.
 *
 * <p>Before the fix, {@code JobsRuntimeManager.wireConsumers} bound the
 * submitter only when the task-backed dep was found in the LOCAL registry
 * (a {@code task()} probe — impossible for a remote producer) OR exactly ONE
 * dependency was declared. A remote task dep mixed with another dep therefore
 * left the MeshJob slot null. The fix binds off the DECLARED dependency the
 * MeshJob param was positionally paired with at wrapper construction
 * ({@link MeshToolWrapper#getMeshJobDependencyCapability}) — mirroring Python,
 * which keys the submitter off the declared capability rather than a local
 * {@code task()} lookup.
 */
class JobsRuntimeManagerConsumerWiringTest {

    /**
     * Consumer that declares two dependencies — an ordinary
     * {@code lookup_db} (injected as {@code McpMeshTool}) and a
     * {@code long_task} (a REMOTE task producer, consumed via the
     * {@code MeshJob} slot). The {@code long_task} dep is declared SECOND
     * AND is not registered locally — the exact mix the old local-probe /
     * single-dep heuristic failed on.
     */
    @SuppressWarnings("unused")
    public static class ConsumerBean {
        public Map<String, Object> commissionReport(
                @Param("user_id") String userId,
                McpMeshTool<String> lookupDb,
                MeshJob longTask) {
            return Map.of("user_id", userId);
        }
    }

    private static Method commissionMethod() throws Exception {
        return ConsumerBean.class.getMethod("commissionReport",
            String.class, McpMeshTool.class, MeshJob.class);
    }

    /**
     * Wrapper funcId MUST equal {@code <BeanClass>.<methodName>} so
     * {@code JobsRuntimeManager.lookupWrapperForMethod} (keyed by
     * {@code AopUtils.getTargetClass(bean).getName() + "." + method.getName()})
     * resolves it.
     */
    private static MeshToolWrapper wrapperFor(ConsumerBean bean) throws Exception {
        return new MeshToolWrapper(
            ConsumerBean.class.getName() + ".commissionReport",
            "commission_report",
            "test",
            bean,
            commissionMethod(),
            // Declared dependency order: ordinary dep FIRST, remote task
            // dep SECOND. db pairs with the McpMeshTool slot (declared
            // index 0); long_task pairs with the MeshJob slot (declared
            // index 1).
            List.of("lookup_db", "long_task"),
            JsonMapper.builder().build(),
            false);
    }

    private static MeshToolRegistry.DependencyInfo dep(String capability) {
        return new MeshToolRegistry.DependencyInfo(
            capability, List.of(), "", null, SchemaMode.NONE);
    }

    private static MeshToolRegistry.ToolMetadata consumerMeta(ConsumerBean bean, Method method) {
        return new MeshToolRegistry.ToolMetadata(
            "commission_report",
            "",
            "1.0.0",
            new java.util.ArrayList<>(),
            // Same two declared deps, ordinary FIRST + remote task SECOND.
            List.of(dep("lookup_db"), dep("long_task")),
            Map.of(),
            null,
            true,
            /* task = */ false,
            bean,
            method);
    }

    @Test
    void remoteTaskDep_mixedWithOrdinaryDep_wiresSubmitterToDeclaredCapability() throws Exception {
        ConsumerBean bean = new ConsumerBean();
        Method method = commissionMethod();
        MeshToolWrapper wrapper = wrapperFor(bean);

        // Sanity: the MeshJob slot is positionally paired with the SECOND
        // declared dependency (long_task), not the first.
        assertEquals("long_task", wrapper.getMeshJobDependencyCapability(),
            "MeshJob param must pair with the declared task capability (declared index 1)");

        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        // NOTE: long_task is a REMOTE producer — deliberately NOT registered
        // as a local task tool. Only the consumer itself is in the registry.
        MeshToolWrapperRegistry wrapperRegistry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory(new McpHttpClient()));
        wrapperRegistry.registerWrapper(wrapper);

        // Seed the consumer tool metadata so wireConsumers can iterate it.
        seedToolMetadata(toolRegistry, consumerMeta(bean, method));

        MeshRuntime runtime = new MeshRuntime(
            new AgentSpec("consumer-agent", "http://localhost:8000")
                .agentId("consumer-agent-abc123"));
        JobsRuntimeManager manager =
            new JobsRuntimeManager(runtime, toolRegistry, wrapperRegistry);

        manager.wireConsumers("consumer-agent-abc123", "http://localhost:8000");

        MeshJobSubmitter submitter = wrapper.getJobSubmitter();
        assertNotNull(submitter,
            "consumer with a REMOTE task dep mixed with an ordinary dep MUST get a "
                + "MeshJobSubmitter wired (pre-fix: null because the local task() probe "
                + "missed the remote producer and the dep count was > 1)");
        assertEquals("long_task", submitter.capability(),
            "submitter must target the DECLARED task capability the MeshJob slot was paired with");
    }

    @Test
    void localTaskDep_singleDep_stillWires_behaviorPreserved() throws Exception {
        // Regression guard for the widening: the previously-working
        // single-dep path must still wire the submitter.
        SingleDepConsumer bean = new SingleDepConsumer();
        Method method = SingleDepConsumer.class.getMethod(
            "run", String.class, MeshJob.class);
        MeshToolWrapper wrapper = new MeshToolWrapper(
            SingleDepConsumer.class.getName() + ".run",
            "single_consumer",
            "test",
            bean,
            method,
            List.of("worker"),
            JsonMapper.builder().build(),
            false);

        assertEquals("worker", wrapper.getMeshJobDependencyCapability());

        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        MeshToolWrapperRegistry wrapperRegistry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory(new McpHttpClient()));
        wrapperRegistry.registerWrapper(wrapper);
        seedToolMetadata(toolRegistry, new MeshToolRegistry.ToolMetadata(
            "single_consumer", "", "1.0.0", new java.util.ArrayList<>(),
            List.of(dep("worker")), Map.of(), null, true, false, bean, method));

        MeshRuntime runtime = new MeshRuntime(
            new AgentSpec("c2", "http://localhost:8000").agentId("c2-id"));
        new JobsRuntimeManager(runtime, toolRegistry, wrapperRegistry)
            .wireConsumers("c2-id", "http://localhost:8000");

        MeshJobSubmitter submitter = wrapper.getJobSubmitter();
        assertNotNull(submitter, "single-dep consumer must still wire (no narrowing)");
        assertEquals("worker", submitter.capability());
    }

    @SuppressWarnings("unused")
    public static class SingleDepConsumer {
        public Map<String, Object> run(@Param("x") String x, MeshJob worker) {
            return Map.of();
        }
    }

    /**
     * MeshToolRegistry has no public bulk seeder; register via the public
     * registerTool path is annotation-driven. The wireConsumers loop reads
     * getAllTools(), so seed through reflection on the private map — the
     * minimal seam needed to exercise consumer wiring without a full Spring
     * scan. (The wiring logic under test is otherwise untouched.)
     */
    private static void seedToolMetadata(MeshToolRegistry registry,
                                         MeshToolRegistry.ToolMetadata meta) throws Exception {
        java.lang.reflect.Field f = MeshToolRegistry.class.getDeclaredField("tools");
        f.setAccessible(true);
        @SuppressWarnings("unchecked")
        Map<String, MeshToolRegistry.ToolMetadata> tools =
            (Map<String, MeshToolRegistry.ToolMetadata>) f.get(registry);
        tools.put(meta.capability(), meta);
    }
}
