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
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1268 — claim-gating for {@code required=true} dependencies.
 *
 * <p>Covers the pure, below-FFI halves of the fix:
 * <ul>
 *   <li>{@link MeshToolWrapper#setDependencyRequired} threads per-position
 *       required flags; {@link MeshToolWrapper#requiredDepsResolved} /
 *       {@link MeshToolWrapper#firstUnresolvedRequiredDependency} reflect
 *       them against the heartbeat-resolved proxy slots.</li>
 *   <li>The pre-invoke guard in {@link MeshToolWrapper#invokeForClaim}: a
 *       null/unavailable REQUIRED slot at invocation time releases the lease
 *       and does NOT invoke the handler (and never {@code fail()}s).</li>
 *   <li>Optional deps are unaffected — a null optional slot still passes
 *       through to the handler (regression guard).</li>
 * </ul>
 *
 * <p>The lease-release action is injected via the package-private
 * {@code invokeForClaim} overload so the release path can be asserted without
 * an FFI-backed {@link io.mcpmesh.JobController} — the same "stay below the FFI
 * boundary" posture as {@link ClaimDispatcherTest}.
 */
class MeshToolWrapperRequiredDepGuardTest {

    /** Producer with ONE required McpMeshTool dependency ("lookup"). */
    public static class RequiredDepBean {
        final AtomicBoolean handlerRan = new AtomicBoolean(false);
        final AtomicReference<McpMeshTool<?>> receivedDep = new AtomicReference<>();

        @MeshTool(capability = "summarize", task = true,
            dependencies = @io.mcpmesh.Selector(capability = "lookup", required = true))
        public Object summarize(
                @Param("user_id") String userId,
                McpMeshTool<String> lookup,
                MeshJob job) {
            handlerRan.set(true);
            receivedDep.set(lookup);
            java.util.Map<String, Object> out = new java.util.HashMap<>();
            out.put("user_id", userId);
            return out;
        }
    }

    /** Available stub proxy returning a sentinel. */
    static class StubProxy implements McpMeshTool<String> {
        static final String SENTINEL = "resolved";
        private final boolean available;
        StubProxy(boolean available) { this.available = available; }
        @Override public String call() { return SENTINEL; }
        @Override public String call(Map<String, Object> params) { return SENTINEL; }
        @Override public String call(Object... args) { return SENTINEL; }
        @Override public CompletableFuture<String> callAsync() { return CompletableFuture.completedFuture(SENTINEL); }
        @Override public CompletableFuture<String> callAsync(Map<String, Object> params) { return CompletableFuture.completedFuture(SENTINEL); }
        @Override public CompletableFuture<String> callAsync(Object... keyValuePairs) { return CompletableFuture.completedFuture(SENTINEL); }
        @Override public String getCapability() { return "lookup"; }
        @Override public String getEndpoint() { return "http://stub"; }
        @Override public String getFunctionName() { return "lookup"; }
        @Override public boolean isAvailable() { return available; }
    }

    private static Method summarizeMethod() throws Exception {
        return RequiredDepBean.class.getMethod("summarize",
            String.class, McpMeshTool.class, MeshJob.class);
    }

    private static MeshToolWrapper wrapperFor(RequiredDepBean bean, boolean required) throws Exception {
        MeshToolWrapper w = new MeshToolWrapper(
            "RequiredDepBean.summarize",
            "summarize",
            "test",
            bean,
            summarizeMethod(),
            List.of("lookup"),
            JsonMapper.builder().build(),
            true);
        w.setDependencyRequired(List.of(required));
        return w;
    }

    // ---- required flags threaded per position -------------------------------

    @Test
    void setDependencyRequired_threadsFlagPerPosition() throws Exception {
        RequiredDepBean bean = new RequiredDepBean();
        MeshToolWrapper wrapper = wrapperFor(bean, true);

        // Required dep unresolved (no proxy pushed) → gate closed, names the cap.
        assertFalse(wrapper.requiredDepsResolved(),
            "a required dep with no resolved proxy must gate claiming");
        assertEquals("lookup", wrapper.firstUnresolvedRequiredDependency(),
            "the gate must name the unresolved required capability");
    }

    @Test
    void requiredDep_null_thenResolved_flipsGate() throws Exception {
        RequiredDepBean bean = new RequiredDepBean();
        MeshToolWrapper wrapper = wrapperFor(bean, true);

        // null slot → gate closed.
        assertFalse(wrapper.requiredDepsResolved());

        // present-but-unavailable proxy still counts as unresolved (#1268).
        wrapper.updateDependency(0, new StubProxy(false));
        assertFalse(wrapper.requiredDepsResolved(),
            "an unavailable proxy must NOT satisfy a required slot");

        // available proxy → gate opens.
        wrapper.updateDependency(0, new StubProxy(true));
        assertTrue(wrapper.requiredDepsResolved(),
            "an available required proxy must open the gate");
        assertNull(wrapper.firstUnresolvedRequiredDependency());
    }

    @Test
    void optionalDep_neverGates() throws Exception {
        RequiredDepBean bean = new RequiredDepBean();
        // Same signature, but the dep is declared optional.
        MeshToolWrapper wrapper = wrapperFor(bean, false);

        assertTrue(wrapper.requiredDepsResolved(),
            "an optional dep must never gate claiming even when unresolved");
        assertNull(wrapper.firstUnresolvedRequiredDependency());
    }

    // ---- pre-invoke guard ---------------------------------------------------

    @Test
    void invokeForClaim_requiredSlotNull_releasesAndDoesNotInvoke() throws Exception {
        RequiredDepBean bean = new RequiredDepBean();
        MeshToolWrapper wrapper = wrapperFor(bean, true);

        AtomicReference<String> releasedReason = new AtomicReference<>();

        // Controller is null; the injected releaser records the release call
        // so we assert the release path WITHOUT an FFI-backed controller.
        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "alice"),
            null,
            null,
            releasedReason::set);

        assertNull(result, "guard must return null (job re-queues), not a handler result");
        assertFalse(bean.handlerRan.get(),
            "handler MUST NOT run when a required dependency is unresolved");
        assertNotNull(releasedReason.get(),
            "the lease MUST be released (not failed) so the job re-queues");
        assertTrue(releasedReason.get().contains("lookup"),
            "release reason must name the missing capability; got: " + releasedReason.get());
    }

    @Test
    void invokeForClaim_requiredSlotResolved_invokesHandler() throws Exception {
        RequiredDepBean bean = new RequiredDepBean();
        MeshToolWrapper wrapper = wrapperFor(bean, true);

        wrapper.updateDependency(0, new StubProxy(true));

        AtomicBoolean released = new AtomicBoolean(false);
        Object result = wrapper.invokeForClaim(
            Map.of("user_id", "bob"),
            null,
            null,
            reason -> released.set(true));

        assertNotNull(result, "handler must run and return a result once the required dep resolves");
        assertTrue(bean.handlerRan.get(), "handler must run when required deps are resolved");
        assertNotNull(bean.receivedDep.get(), "resolved required proxy must be injected");
        assertFalse(released.get(), "lease must NOT be released when required deps are resolved");
    }
}
