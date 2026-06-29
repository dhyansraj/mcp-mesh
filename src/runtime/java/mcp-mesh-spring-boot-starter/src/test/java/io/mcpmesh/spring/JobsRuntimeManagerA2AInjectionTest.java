package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.StandardEnvironment;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #923 regression cover: verify the claim path fills the
 * {@link A2AClient} parameter slot for {@code task=true @A2AConsumer}
 * producers. Without this, uc27 tc04/05/06/08 fail with
 * {@code NullPointerException} on the first {@code a2a.send(...)} call.
 *
 * <p>The claim path now delegates to
 * {@link MeshToolWrapper#invokeForClaim} (Wave-1 A1) instead of a thin
 * reflection invoker in {@code JobsRuntimeManager}. The A2AClient binding
 * the {@link A2AConsumerBeanPostProcessor} computes is wired onto the
 * wrapper via {@link MeshToolWrapper#setA2AClientBinding} — exactly as
 * {@code MeshToolBeanPostProcessor} does at boot — so the slot is filled
 * by the wrapper's {@code buildFullArgs}, the SAME shaping the inbound
 * path uses.
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

    private static Method reportMethod() throws Exception {
        return TaskBean.class.getMethod("generateReport",
            String.class, List.class, A2AClient.class, MeshJob.class);
    }

    private static MeshToolWrapper wrapperFor(TaskBean bean) throws Exception {
        return new MeshToolWrapper(
            "TaskBean.generateReport",
            "report",
            "test",
            bean,
            reportMethod(),
            List.of(),
            JsonMapper.builder().build(),
            true);
    }

    @Test
    void claimPath_injectsBoundA2AClientOnTaskBridge() throws Exception {
        // 1. Compute the A2A binding the bean post-processor would produce.
        A2AConsumerBeanPostProcessor a2a = new A2AConsumerBeanPostProcessor(new StandardEnvironment());
        TaskBean bean = new TaskBean();
        a2a.postProcessAfterInitialization(bean, "task");
        A2AConsumerBeanPostProcessor.MethodBinding binding = a2a.bindingFor(reportMethod());
        assertNotNull(binding, "A2AConsumerBeanPostProcessor must produce a binding for the task bridge");

        // 2. Build the wrapper and wire the binding (mimics MeshToolBeanPostProcessor).
        MeshToolWrapper wrapper = wrapperFor(bean);
        wrapper.setA2AClientBinding(binding.a2aParamIndex(), binding.client());

        // 3. Drive the claim path (the producer JobController is null — the
        //    method only touches the A2AClient slot here).
        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "alice", "sections", List.of("intro")),
            null,
            null);

        assertNotNull(result);
        // The smoking-gun assertion — without the claim-path injection
        // fix, bean.received.get() is null and the user method NPEs on
        // the first a2a.send(...).
        assertNotNull(bean.received.get(),
            "claim-path delegate (invokeForClaim) MUST inject the cached A2AClient at the bound slot — "
                + "uc27 tc04/05/06/08 regression cover");
        assertSame(binding.client(), bean.received.get(),
            "the injected client must be the one the bean post-processor cached");
    }

    @Test
    void claimPath_passesNullA2AClient_whenNoBinding() throws Exception {
        // Defensive cover: a wrapper with no A2A binding wired (e.g. legacy
        // environments without the A2A processor) must still invoke
        // task methods, just leaving the A2AClient slot null.
        TaskBean bean = new TaskBean();
        MeshToolWrapper wrapper = wrapperFor(bean);

        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "alice", "sections", List.of()),
            null,
            null);
        assertNotNull(result);
        assertNull(bean.received.get(),
            "no A2A binding wired → A2AClient slot stays null");
    }
}
