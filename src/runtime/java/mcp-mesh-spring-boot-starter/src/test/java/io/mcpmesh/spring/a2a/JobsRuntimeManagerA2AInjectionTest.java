package io.mcpmesh.spring.a2a;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.spring.A2AConsumerBeanPostProcessor;
import io.mcpmesh.spring.JobsRuntimeManager;
import io.mcpmesh.spring.MeshToolRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.StandardEnvironment;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #923 regression cover: verify the claim-path reflection invoker
 * in {@link JobsRuntimeManager} fills the {@link A2AClient} parameter
 * slot for {@code task=true @A2AConsumer} producers. Without this,
 * uc27 tc04/05/06/08 fail with {@code NullPointerException} on the
 * first {@code a2a.send(...)} call (the claim path doesn't go through
 * {@link io.mcpmesh.spring.MeshToolWrapper}, so its
 * {@code setA2AClientBinding} wiring is bypassed).
 */
class JobsRuntimeManagerA2AInjectionTest {

    /** Shape mirrors the uc27 consumer-report-agent-java fixture. */
    public static class TaskBean {
        final AtomicReference<A2AClient> received = new AtomicReference<>();

        @MeshTool(capability = "report", task = true)
        @A2AConsumer(url = "http://localhost:9091/agents/report", skillId = "generate-report")
        public Object generateReport(
                @Param("user_id") String userId,
                @Param(value = "sections", required = false) List<String> sections,
                A2AClient a2a,
                MeshJob job) {
            received.set(a2a);
            return Map.of("user_id", userId, "sections", sections == null ? List.of() : sections);
        }
    }

    @Test
    void claimPath_injectsBoundA2AClientOnTaskBridge() throws Exception {
        // 1. Stand up the A2A processor + wire the task bean.
        A2AConsumerBeanPostProcessor a2a = new A2AConsumerBeanPostProcessor(new StandardEnvironment());
        TaskBean bean = new TaskBean();
        a2a.postProcessAfterInitialization(bean, "task");

        // 2. Register the tool with MeshToolRegistry (mimics what
        //    MeshToolBeanPostProcessor would do at boot).
        MeshToolRegistry registry = new MeshToolRegistry();
        Method method = TaskBean.class.getMethod("generateReport",
            String.class, List.class, A2AClient.class, MeshJob.class);
        registry.registerTool(bean, method, method.getAnnotation(MeshTool.class));

        // 3. Build the JobsRuntimeManager — only the invokeViaReflection
        //    path matters for this test; we don't start the full
        //    SmartLifecycle.
        JobsRuntimeManager mgr = new JobsRuntimeManager(
            null, registry, null, a2a);

        // 4. Drive invokeViaReflection through reflection (the method is
        //    private, but visible to the test in the same module).
        Method invokeMethod = JobsRuntimeManager.class.getDeclaredMethod(
            "invokeViaReflection",
            MeshToolRegistry.ToolMetadata.class,
            Map.class,
            JobController.class);
        invokeMethod.setAccessible(true);

        MeshToolRegistry.ToolMetadata meta = registry.getTool("report");
        assertNotNull(meta);

        Object result = invokeMethod.invoke(mgr, meta,
            Map.of("user_id", "alice", "sections", List.of("intro")),
            null);

        assertNotNull(result);
        // The smoking-gun assertion — without the claim-path injection
        // fix, bean.received.get() is null and the user method NPEs on
        // the first a2a.send(...).
        assertNotNull(bean.received.get(),
            "claim-path reflection invoker MUST inject the cached A2AClient at the bound slot — "
                + "uc27 tc04/05/06/08 regression cover");
    }

    @Test
    void claimPath_passesNullA2AClient_whenNoBinding() throws Exception {
        // Defensive cover: a JobsRuntimeManager constructed without the
        // A2A processor (e.g. legacy environments) must still invoke
        // task-only methods without the slot, just leaving A2AClient
        // params as null. Mirrors the McpMeshTool "Phase 1 limit" path.
        MeshToolRegistry registry = new MeshToolRegistry();
        TaskBean bean = new TaskBean();
        Method method = TaskBean.class.getMethod("generateReport",
            String.class, List.class, A2AClient.class, MeshJob.class);
        registry.registerTool(bean, method, method.getAnnotation(MeshTool.class));

        JobsRuntimeManager mgr = new JobsRuntimeManager(
            null, registry, null, null);

        Method invokeMethod = JobsRuntimeManager.class.getDeclaredMethod(
            "invokeViaReflection",
            MeshToolRegistry.ToolMetadata.class,
            Map.class,
            JobController.class);
        invokeMethod.setAccessible(true);

        MeshToolRegistry.ToolMetadata meta = registry.getTool("report");
        Object result = invokeMethod.invoke(mgr, meta,
            Map.of("user_id", "alice", "sections", List.of()), null);
        assertNotNull(result);
        assertNull(bean.received.get(),
            "no A2A processor wired → A2AClient slot stays null (matches Phase 1 limit for other inject types)");
    }
}
