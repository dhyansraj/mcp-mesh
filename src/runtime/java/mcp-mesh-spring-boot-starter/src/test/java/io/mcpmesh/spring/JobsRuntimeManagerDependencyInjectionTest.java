package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Wave-1 A1 cover: a {@code @MeshTool(task=true)} producer that declares a
 * {@link McpMeshTool} dependency must have that dependency RESOLVED on the
 * claim path — not nulled (the pre-fix behaviour) nor rejected at startup
 * (the pre-fix {@code validateProducerParams} guard).
 *
 * <p>The claim path now delegates to {@link MeshToolWrapper#invokeForClaim},
 * which reuses {@code buildFullArgs} — the SAME argument shaping the inbound
 * path uses — so a heartbeat-resolved proxy pushed via
 * {@link MeshToolWrapper#updateDependency} flows into the producer. This
 * mirrors Python, whose claim path re-runs the same DI-wrapped handler.
 *
 * <p>Mirrors the assertion style of
 * {@link JobsRuntimeManagerA2AInjectionTest}: stub a
 * resolved proxy, drive the claim delegate, assert the bean saw a non-null
 * dependency and the sentinel flows through.
 */
class JobsRuntimeManagerDependencyInjectionTest {

    /** Producer that needs a helper-tool dependency on the claim path. */
    public static class TaskBean {
        final AtomicReference<McpMeshTool<?>> receivedDep = new AtomicReference<>();
        final AtomicReference<Object> depResult = new AtomicReference<>();

        @MeshTool(capability = "summarize", task = true,
            dependencies = @io.mcpmesh.Selector(capability = "lookup"))
        public Object summarize(
                @Param("user_id") String userId,
                McpMeshTool<String> lookup,
                MeshJob job) {
            receivedDep.set(lookup);
            if (lookup != null && lookup.isAvailable()) {
                depResult.set(lookup.call(Map.of("user_id", userId)));
            }
            // Tolerate a null dep result (graceful degradation) — Map.of
            // rejects nulls, so use a mutable map.
            java.util.Map<String, Object> out = new java.util.HashMap<>();
            out.put("user_id", userId);
            out.put("lookup", depResult.get());
            return out;
        }
    }

    /** Stub proxy: available, returns a sentinel from every call(...). */
    static class StubProxy implements McpMeshTool<String> {
        static final String SENTINEL = "resolved-via-claim-path";

        @Override public String call() { return SENTINEL; }
        @Override public String call(Map<String, Object> params) { return SENTINEL; }
        @Override public String call(Object... args) { return SENTINEL; }
        @Override public CompletableFuture<String> callAsync() {
            return CompletableFuture.completedFuture(SENTINEL);
        }
        @Override public CompletableFuture<String> callAsync(Map<String, Object> params) {
            return CompletableFuture.completedFuture(SENTINEL);
        }
        @Override public CompletableFuture<String> callAsync(Object... keyValuePairs) {
            return CompletableFuture.completedFuture(SENTINEL);
        }
        @Override public String getCapability() { return "lookup"; }
        @Override public String getEndpoint() { return "http://stub"; }
        @Override public String getFunctionName() { return "lookup"; }
        @Override public boolean isAvailable() { return true; }
    }

    private static Method summarizeMethod() throws Exception {
        return TaskBean.class.getMethod("summarize",
            String.class, McpMeshTool.class, MeshJob.class);
    }

    private static MeshToolWrapper wrapperFor(TaskBean bean) throws Exception {
        return new MeshToolWrapper(
            "TaskBean.summarize",
            "summarize",
            "test",
            bean,
            summarizeMethod(),
            List.of("lookup"),
            JsonMapper.builder().build(),
            true);
    }

    @Test
    void claimPath_resolvesMcpMeshToolDependency() throws Exception {
        TaskBean bean = new TaskBean();
        MeshToolWrapper wrapper = wrapperFor(bean);

        // Push a resolved proxy as the heartbeat would (declared index 0).
        StubProxy stub = new StubProxy();
        wrapper.updateDependency(0, stub);

        // Drive the claim delegate (the producer JobController is null —
        // this test only exercises dependency injection, not job control).
        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "alice"),
            null,
            null);

        assertNotNull(result);
        // Smoking-gun assertions — pre-fix, the claim path nulled this slot
        // (and startup rejected the signature outright).
        assertNotNull(bean.receivedDep.get(),
            "claim-path delegate (invokeForClaim) MUST inject the resolved McpMeshTool dependency");
        assertSame(stub, bean.receivedDep.get(),
            "the injected proxy must be the one pushed via updateDependency");
        assertEquals(StubProxy.SENTINEL, bean.depResult.get(),
            "the dependency's call(...) sentinel must flow through the producer");
    }

    @Test
    void claimPath_passesNullDependency_whenUnresolved() throws Exception {
        // Graceful degradation: with no proxy pushed, the slot stays null
        // and the producer still runs (it null-checks the dep).
        TaskBean bean = new TaskBean();
        MeshToolWrapper wrapper = wrapperFor(bean);

        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "bob"),
            null,
            null);

        assertNotNull(result);
        assertNull(bean.receivedDep.get(),
            "no proxy resolved → McpMeshTool slot stays null for graceful degradation");
    }
}
