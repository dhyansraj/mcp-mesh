package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.types.McpMeshTool;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.junit.jupiter.api.AfterEach;
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

    // ---- direct-invoke guard (issue #1273) ----------------------------------

    /** Plain (non-task) consumer with ONE required McpMeshTool dependency. */
    public static class DirectRequiredDepBean {
        final AtomicBoolean handlerRan = new AtomicBoolean(false);
        final AtomicReference<McpMeshTool<?>> receivedDep = new AtomicReference<>();

        @MeshTool(capability = "enrich",
            dependencies = @io.mcpmesh.Selector(capability = "lookup", required = true))
        public Object enrich(
                @Param("user_id") String userId,
                McpMeshTool<String> lookup) {
            handlerRan.set(true);
            receivedDep.set(lookup);
            java.util.Map<String, Object> out = new java.util.HashMap<>();
            out.put("user_id", userId);
            return out;
        }
    }

    private static MeshToolWrapper directWrapperFor(DirectRequiredDepBean bean, boolean required)
            throws Exception {
        Method m = DirectRequiredDepBean.class.getMethod("enrich", String.class, McpMeshTool.class);
        MeshToolWrapper w = new MeshToolWrapper(
            "DirectRequiredDepBean.enrich",
            "enrich",
            "test",
            bean,
            m,
            List.of("lookup"),
            JsonMapper.builder().build());
        w.setDependencyRequired(List.of(required));
        return w;
    }

    @Test
    void invoke_requiredSlotNull_refusesWithoutInvoking() throws Exception {
        DirectRequiredDepBean bean = new DirectRequiredDepBean();
        MeshToolWrapper wrapper = directWrapperFor(bean, true);

        Object result = wrapper.invoke(Map.of("user_id", "alice"));

        assertFalse(bean.handlerRan.get(),
            "handler MUST NOT run when a required dependency is unresolved at direct invoke");
        assertInstanceOf(CallToolResult.class, result,
            "the refusal must be a structured tool result, not a raw value");
        CallToolResult ctr = (CallToolResult) result;
        assertEquals(Boolean.TRUE, ctr.isError(),
            "the refusal must be an isError tool result (retryable topology, not app failure)");
        String text = ((TextContent) ctr.content().get(0)).text();
        assertTrue(text.contains("\"error\":\"dependency_unavailable\""),
            "text must carry the dependency_unavailable envelope; got: " + text);
        assertTrue(text.contains("\"capability\":\"lookup\""),
            "the envelope must name the missing capability; got: " + text);
    }

    @Test
    void invoke_requiredSlotResolved_invokesHandler() throws Exception {
        DirectRequiredDepBean bean = new DirectRequiredDepBean();
        MeshToolWrapper wrapper = directWrapperFor(bean, true);

        wrapper.updateDependency(0, new StubProxy(true));

        Object result = wrapper.invoke(Map.of("user_id", "bob"));

        assertTrue(bean.handlerRan.get(),
            "handler must run once the required dep resolves");
        assertNotNull(bean.receivedDep.get(), "resolved required proxy must be injected");
        assertFalse(result instanceof CallToolResult,
            "a resolved call must return the handler result, not a refusal envelope");
    }

    @Test
    void invoke_optionalSlotNull_invokesHandlerWithNull() throws Exception {
        DirectRequiredDepBean bean = new DirectRequiredDepBean();
        // Same signature, but the dep is declared OPTIONAL — null passthrough.
        MeshToolWrapper wrapper = directWrapperFor(bean, false);

        Object result = wrapper.invoke(Map.of("user_id", "carol"));

        assertTrue(bean.handlerRan.get(),
            "an optional dep must never gate a direct invoke even when null");
        assertNull(bean.receivedDep.get(),
            "the handler must observe null for the unresolved OPTIONAL dep");
        assertFalse(result instanceof CallToolResult,
            "an optional null dep must not produce a refusal envelope");
    }

    // ---- guard vs settle grace (issue #1273 review) -------------------------

    @AfterEach
    void resetSettleState() {
        MeshSettleState.resetForTests();
    }

    @Test
    void invoke_requiredDepLandsMidSettle_waitsThenInvokes() throws Exception {
        // Arm a live settle window so the guard's underlying buildFullArgs
        // BLOCKS on the slot latch (the guard is evaluated AFTER settle grace).
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("DirectRequiredDepBean.enrich:dep_0");

        DirectRequiredDepBean bean = new DirectRequiredDepBean();
        MeshToolWrapper wrapper = directWrapperFor(bean, true);

        // Land the required proxy mid-wait (mirrors a heartbeat resolving the
        // dep during the settle window).
        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            wrapper.updateDependency(0, new StubProxy(true));
        });
        resolver.start();

        Object result = wrapper.invoke(Map.of("user_id", "dave"));
        resolver.join(2000);

        assertTrue(bean.handlerRan.get(),
            "a required dep that lands within the settle window must NOT be refused — "
                + "the guard must wait out settle grace first (a fresh restart must "
                + "block-then-succeed, not burst-refuse)");
        assertNotNull(bean.receivedDep.get(), "the resolved proxy must be injected");
        assertFalse(result instanceof CallToolResult,
            "a mid-settle resolution must not produce a refusal envelope");
    }

    @Test
    void invoke_requiredDepDownAfterSettle_refuses() throws Exception {
        // Settled state (timeout=0) → no grace window → fail-fast refusal.
        MeshSettleState.resetForTests();
        DirectRequiredDepBean bean = new DirectRequiredDepBean();
        MeshToolWrapper wrapper = directWrapperFor(bean, true);

        Object result = wrapper.invoke(Map.of("user_id", "erin"));

        assertFalse(bean.handlerRan.get(),
            "a required dep still down AFTER settle must be refused");
        assertInstanceOf(CallToolResult.class, result);
        assertEquals(Boolean.TRUE, ((CallToolResult) result).isError());
        String text = ((TextContent) ((CallToolResult) result).content().get(0)).text();
        assertTrue(text.contains("\"capability\":\"lookup\""), text);
    }

    // ---- guard vs job-header path (issue #1273 review) ----------------------

    @Test
    void jobHeaderDispatch_requiredDepUnresolved_doesNotInvoke_returnsNull() throws Exception {
        // A task=true tool invoked with an X-Mesh-Job-Id header (cross-runtime
        // claim propagation). instanceId/registryUrl are NOT wired, so
        // canInjectController is false — the guard refuses-to-invoke and
        // returns null WITHOUT constructing an FFI JobController. This proves
        // the job-flavored path never emits a tool-error refusal and never
        // runs the handler; the FFI-backed lease release for the wired case
        // mirrors invokeForClaim (covered there / at integration level).
        RequiredDepBean bean = new RequiredDepBean();
        MeshToolWrapper wrapper = wrapperFor(bean, true); // task=true, required

        MeshSettleState.resetForTests(); // settled — no grace
        try {
            TraceContext.setPropagatedHeaders(Map.of("x-mesh-job-id", "job-123"));
            Object result = wrapper.invoke(Map.of("user_id", "frank"));

            assertNull(result,
                "the job-flavored guard must return null (job re-queues), not a "
                    + "tool-error refusal");
            assertFalse(bean.handlerRan.get(),
                "the handler MUST NOT run with an unresolved required dep on the job path");
        } finally {
            TraceContext.clearPropagatedHeaders();
        }
    }
}
