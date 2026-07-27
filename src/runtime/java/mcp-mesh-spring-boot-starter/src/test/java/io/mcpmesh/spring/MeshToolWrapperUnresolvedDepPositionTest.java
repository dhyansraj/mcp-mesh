package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Positional-injection safety property: an UNRESOLVED dependency must not
 * shift the other dependencies into the wrong parameter slots.
 *
 * <p>mcp-mesh injects dependencies positionally — {@code dependencies[i]}
 * pairs with the i-th dependency-typed parameter in declaration order. The
 * property pinned here is what makes that safe to ship:
 *
 * <blockquote>An unresolved dependency leaves ITS OWN slot null, and every
 * other dependency still lands in its own slot.</blockquote>
 *
 * <p>Without it, one provider going down would silently rewire every
 * downstream parameter (cap_c's proxy arriving as the {@code depB}
 * parameter) — a much worse failure than a null.
 *
 * <p>Cross-runtime seam — the same property is pinned by:
 * <ul>
 *   <li>Python: {@code test_12_dependency_injector.py ::
 *       TestUnifiedPositionalInjection ::
 *       test_unresolved_middle_dependency_does_not_shift} (+ the mixed
 *       MeshJob variant).</li>
 *   <li>TypeScript: {@code src/__tests__/unresolved-dep-no-shift.spec.ts}.</li>
 * </ul>
 *
 * <p>In Java the property holds by construction — {@code updateDependency}
 * writes {@code injectedDeps[depIndexToSlot[depIndex]]} (a fixed index map
 * built at wrapper construction) and {@code buildFullArgs} reads slot ordinal
 * {@code i} into {@code meshToolPositions.get(i)}. Neither step consults
 * resolution STATE, so an unresolved slot cannot compress the others. These
 * tests exercise that through the real invoke path (and through the
 * composite-key registry path the heartbeat events actually use) so a future
 * refactor that compacts the slot array fails here.
 */
class MeshToolWrapperUnresolvedDepPositionTest {

    /** Consumer with THREE McpMeshTool dependencies in declaration order. */
    public static class FanOutBean {
        final List<McpMeshTool<?>> received = new ArrayList<>();

        @MeshTool(capability = "fan_out", dependencies = {
            @Selector(capability = "cap_a"),
            @Selector(capability = "cap_b"),
            @Selector(capability = "cap_c")})
        public Object fanOut(
                @Param("user_id") String userId,
                McpMeshTool<String> depA,
                McpMeshTool<String> depB,
                McpMeshTool<String> depC) {
            received.clear();
            received.add(depA);
            received.add(depB);
            received.add(depC);
            return Map.of("user_id", userId);
        }
    }

    /**
     * Consumer mixing a MeshJob dependency with McpMeshTool dependencies —
     * the declared-index / slot-ordinal spaces skew here, so an unresolved
     * McpMeshTool in the middle is the sharpest form of the property.
     */
    public static class MixedBean {
        final List<Object> received = new ArrayList<>();

        @MeshTool(capability = "mixed", dependencies = {
            @Selector(capability = "run_workflow"),
            @Selector(capability = "missing_tool"),
            @Selector(capability = "cap_c")})
        public Object mixed(
                @Param("user_id") String userId,
                MeshJob job,                  // declared index 0
                McpMeshTool<String> missing,  // declared index 1 — unresolved
                McpMeshTool<String> present) { // declared index 2
            received.clear();
            received.add(job);
            received.add(missing);
            received.add(present);
            return Map.of("user_id", userId);
        }
    }

    /** Available stub proxy that reports the capability it is bound to. */
    static class StubProxy implements McpMeshTool<String> {
        private final String capability;
        StubProxy(String capability) { this.capability = capability; }
        @Override public String call() { return capability; }
        @Override public String call(Map<String, Object> params) { return capability; }
        @Override public String call(Object... args) { return capability; }
        @Override public CompletableFuture<String> callAsync() { return CompletableFuture.completedFuture(capability); }
        @Override public CompletableFuture<String> callAsync(Map<String, Object> params) { return CompletableFuture.completedFuture(capability); }
        @Override public CompletableFuture<String> callAsync(Object... keyValuePairs) { return CompletableFuture.completedFuture(capability); }
        @Override public String getCapability() { return capability; }
        @Override public String getEndpoint() { return "http://" + capability; }
        @Override public String getFunctionName() { return capability; }
        @Override public boolean isAvailable() { return true; }
    }

    private static String capabilityOf(Object dep) {
        return dep == null ? null : ((McpMeshTool<?>) dep).getCapability();
    }

    private static MeshToolWrapper fanOutWrapper(FanOutBean bean) throws Exception {
        Method m = FanOutBean.class.getMethod("fanOut",
            String.class, McpMeshTool.class, McpMeshTool.class, McpMeshTool.class);
        return new MeshToolWrapper(
            "FanOutBean.fanOut",
            "fan_out",
            "test",
            bean,
            m,
            List.of("cap_a", "cap_b", "cap_c"),
            JsonMapper.builder().build());
    }

    private static MeshToolWrapper mixedWrapper(MixedBean bean) throws Exception {
        Method m = MixedBean.class.getMethod("mixed",
            String.class, MeshJob.class, McpMeshTool.class, McpMeshTool.class);
        return new MeshToolWrapper(
            "MixedBean.mixed",
            "mixed",
            "test",
            bean,
            m,
            List.of("run_workflow", "missing_tool", "cap_c"),
            JsonMapper.builder().build());
    }

    // ---- the property -------------------------------------------------------

    @Test
    void unresolvedMiddleDependency_doesNotShift() throws Exception {
        FanOutBean bean = new FanOutBean();
        MeshToolWrapper wrapper = fanOutWrapper(bean);

        // Resolve ONLY dependency 0 and dependency 2. Dependency 1 (cap_b)
        // never resolves — the exact "provider went down" shape.
        wrapper.updateDependency(0, new StubProxy("cap_a"));
        wrapper.updateDependency(2, new StubProxy("cap_c"));

        Object result = wrapper.invoke(Map.of("user_id", "alice"));

        assertFalse(result instanceof io.modelcontextprotocol.spec.McpSchema.CallToolResult,
            "optional unresolved deps must not produce a refusal envelope");
        assertEquals(3, bean.received.size(),
            "every declared dependency slot must be materialised — the array is "
                + "never compacted");
        assertEquals("cap_a", capabilityOf(bean.received.get(0)),
            "position 0 must keep its own proxy");
        assertNull(bean.received.get(1),
            "the UNRESOLVED dependency must leave its OWN slot null — it must not "
                + "slide up and consume cap_c's proxy");
        assertEquals("cap_c", capabilityOf(bean.received.get(2)),
            "position 2 must still receive cap_c, not shift down to position 1");
    }

    @Test
    void unresolvedLeadingAndTrailingDependencies_holdTheirOwnSlots() throws Exception {
        FanOutBean bean = new FanOutBean();
        MeshToolWrapper wrapper = fanOutWrapper(bean);

        // Only the MIDDLE dependency resolves.
        wrapper.updateDependency(1, new StubProxy("cap_b"));

        wrapper.invoke(Map.of("user_id", "bob"));

        assertNull(bean.received.get(0), "unresolved leading dep must stay null in slot 0");
        assertEquals("cap_b", capabilityOf(bean.received.get(1)),
            "the single resolved dep must land in ITS slot (1), not slot 0");
        assertNull(bean.received.get(2), "unresolved trailing dep must stay null in slot 2");
    }

    @Test
    void dependencyGoingUnavailable_nullsOnlyItsOwnSlot() throws Exception {
        FanOutBean bean = new FanOutBean();
        MeshToolWrapper wrapper = fanOutWrapper(bean);

        wrapper.updateDependency(0, new StubProxy("cap_a"));
        wrapper.updateDependency(1, new StubProxy("cap_b"));
        wrapper.updateDependency(2, new StubProxy("cap_c"));

        wrapper.invoke(Map.of("user_id", "carol"));
        assertEquals(List.of("cap_a", "cap_b", "cap_c"),
            bean.received.stream().map(MeshToolWrapperUnresolvedDepPositionTest::capabilityOf).toList(),
            "baseline: all three resolved deps land in declaration order");

        // The middle provider drops out (dependency_unavailable → null proxy).
        wrapper.updateDependency(1, null);
        wrapper.invoke(Map.of("user_id", "carol"));

        assertEquals("cap_a", capabilityOf(bean.received.get(0)));
        assertNull(bean.received.get(1),
            "the dropped dependency nulls its own slot only");
        assertEquals("cap_c", capabilityOf(bean.received.get(2)),
            "the surviving trailing dependency must NOT shift into the freed slot");
    }

    @Test
    void unresolvedMiddleDependency_doesNotShift_viaRegistryCompositeKey() throws Exception {
        // The heartbeat path applies resolutions through
        // MeshToolWrapperRegistry with a `funcId:dep_N` composite key. Pin the
        // property on that path too — the key carries the declared index, so a
        // gap must survive the parse.
        FanOutBean bean = new FanOutBean();
        MeshToolWrapper wrapper = fanOutWrapper(bean);

        MeshToolWrapperRegistry registry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory(new McpHttpClient()));
        registry.registerWrapper(wrapper);

        registry.updateDependency(
            MeshToolWrapperRegistry.buildDependencyKey("FanOutBean.fanOut", 0),
            "http://provider-a:9001", "fn_a", "agent-a");
        // dep_1 is deliberately never applied.
        registry.updateDependency(
            MeshToolWrapperRegistry.buildDependencyKey("FanOutBean.fanOut", 2),
            "http://provider-c:9003", "fn_c", "agent-c");

        wrapper.invoke(Map.of("user_id", "dave"));

        assertNotNull(bean.received.get(0));
        assertEquals("http://provider-a:9001", bean.received.get(0).getEndpoint(),
            "slot 0 must hold the dep_0 proxy");
        assertNull(bean.received.get(1),
            "the never-applied dep_1 must leave its own slot null");
        assertNotNull(bean.received.get(2),
            "slot 2 must be populated — the gap at dep_1 must not compact it away");
        assertEquals("http://provider-c:9003", bean.received.get(2).getEndpoint(),
            "slot 2 must hold the dep_2 proxy, not dep_0's or a shifted one");
    }

    @Test
    void unresolvedMeshToolBesideMeshJob_doesNotShift() throws Exception {
        // Declared-index → slot-ordinal skew: with a MeshJob at declared index
        // 0, "missing_tool" is declared index 1 / slot 0 and "cap_c" is
        // declared index 2 / slot 1. Resolving ONLY cap_c must fill the
        // `present` parameter — never the `missing` one.
        MixedBean bean = new MixedBean();
        MeshToolWrapper wrapper = mixedWrapper(bean);

        wrapper.updateDependency(2, new StubProxy("cap_c"));

        wrapper.invoke(Map.of("user_id", "erin"));

        // No consumer-side submitter is wired in this unit context (staying
        // below the FFI boundary), so the MeshJob slot is null — the point is
        // that it is the JOB parameter that is null, not a shifted proxy.
        assertNull(bean.received.get(0),
            "the MeshJob slot must stay its own slot (no submitter wired here)");
        assertNull(bean.received.get(1),
            "the unresolved McpMeshTool must leave its own slot null");
        assertEquals("cap_c", capabilityOf(bean.received.get(2)),
            "cap_c must land in ITS parameter — not shift into the unresolved "
                + "'missing_tool' slot");
    }
}
