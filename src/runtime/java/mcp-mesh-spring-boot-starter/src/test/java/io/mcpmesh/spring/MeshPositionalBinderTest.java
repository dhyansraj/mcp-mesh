package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Pins the positional pairing rule extracted from {@link MeshToolWrapper}
 * (issue #1401 PR 0): the Nth declared dependency binds to the Nth injectable
 * parameter in signature order, a {@code MeshJob} slot consumes a declared
 * index without owning a proxy slot, and surplus on either side maps to -1
 * rather than shifting anything.
 *
 * <p>The end-to-end consequence of the same rule — that an unresolved
 * dependency holds its own slot — is pinned by
 * {@link MeshToolWrapperUnresolvedDepPositionTest} through the real invoke
 * path.
 */
class MeshPositionalBinderTest {

    @SuppressWarnings("unused")
    static class Shapes {
        public void none(@Param("a") String a) {}

        public void threeProxies(@Param("a") String a, McpMeshTool<String> d0,
                                 McpMeshTool<String> d1, McpMeshTool<String> d2) {}

        public void jobFirst(@Param("a") String a, MeshJob job,
                             McpMeshTool<String> d1, McpMeshTool<String> d2) {}

        public void jobMiddle(@Param("a") String a, McpMeshTool<String> d0,
                              MeshJob job, McpMeshTool<String> d2) {}

        public void llmInterleaved(@Param("a") String a, McpMeshTool<String> d0,
                                   MeshLlmAgent llm, McpMeshTool<String> d1) {}
    }

    private static Method method(String name, Class<?>... types) throws Exception {
        return Shapes.class.getMethod(name, types);
    }

    private static MeshPositionalBinder.Binding bind(
            Method m, List<Integer> proxies, Integer job, List<String> caps) {
        return MeshPositionalBinder.bind(
            m, MeshPositionalBinder.slots(proxies, job), caps, caps.size());
    }

    @Test
    void noDependencies_producesEmptyTables() throws Exception {
        MeshPositionalBinder.Binding b =
            bind(method("none", String.class), List.of(), null, List.of());

        assertArrayEquals(new int[0], b.depIndexToSlot());
        assertArrayEquals(new int[0], b.slotToDepIndex());
        assertEquals(-1, b.jobDepIndex());
        assertEquals(0, b.proxySlotCount());
    }

    @Test
    void nthDependencyBindsNthInjectableParameter() throws Exception {
        MeshPositionalBinder.Binding b = bind(
            method("threeProxies", String.class, McpMeshTool.class,
                McpMeshTool.class, McpMeshTool.class),
            List.of(1, 2, 3), null, List.of("cap_a", "cap_b", "cap_c"));

        assertArrayEquals(new int[]{0, 1, 2}, b.depIndexToSlot());
        assertArrayEquals(new int[]{0, 1, 2}, b.slotToDepIndex());
        assertEquals(List.of(1, 2, 3), b.slotPositions(),
            "slots are reported in signature order");
    }

    @Test
    void nonInjectableParametersAreNotSlots() throws Exception {
        // A MeshLlmAgent parameter lives in its own index space — it must not
        // consume a declared dependency index or displace a proxy slot.
        MeshPositionalBinder.Binding b = bind(
            method("llmInterleaved", String.class, McpMeshTool.class,
                MeshLlmAgent.class, McpMeshTool.class),
            List.of(1, 3), null, List.of("cap_a", "cap_b"));

        assertArrayEquals(new int[]{0, 1}, b.depIndexToSlot());
        assertArrayEquals(new int[]{0, 1}, b.slotToDepIndex());
        assertEquals(List.of(1, 3), b.slotPositions());
    }

    @Test
    void meshJobSlotConsumesADeclaredIndexButOwnsNoProxySlot() throws Exception {
        MeshPositionalBinder.Binding b = bind(
            method("jobFirst", String.class, MeshJob.class,
                McpMeshTool.class, McpMeshTool.class),
            List.of(2, 3), 1, List.of("job_cap", "cap_b", "cap_c"));

        assertEquals(0, b.jobDepIndex(), "the leading declared dep pairs with the job slot");
        assertArrayEquals(new int[]{-1, 0, 1}, b.depIndexToSlot(),
            "declared index 0 is job-backed; cap_b/cap_c skew down one slot");
        assertArrayEquals(new int[]{1, 2}, b.slotToDepIndex());
    }

    @Test
    void meshJobInterleaved_skewsOnlyTheSlotsAfterIt() throws Exception {
        MeshPositionalBinder.Binding b = bind(
            method("jobMiddle", String.class, McpMeshTool.class,
                MeshJob.class, McpMeshTool.class),
            List.of(1, 3), 2, List.of("cap_a", "job_cap", "cap_c"));

        assertEquals(1, b.jobDepIndex());
        assertArrayEquals(new int[]{0, -1, 1}, b.depIndexToSlot());
        assertArrayEquals(new int[]{0, 2}, b.slotToDepIndex());
    }

    @Test
    void excessDeclaredDependencies_mapToMinusOne() throws Exception {
        MeshPositionalBinder.Binding b = bind(
            method("threeProxies", String.class, McpMeshTool.class,
                McpMeshTool.class, McpMeshTool.class),
            List.of(1, 2, 3), null, List.of("a", "b", "c", "d", "e"));

        assertArrayEquals(new int[]{0, 1, 2, -1, -1}, b.depIndexToSlot(),
            "declared deps beyond the available slots are dropped, not reassigned");
        assertArrayEquals(new int[]{0, 1, 2}, b.slotToDepIndex());
    }

    @Test
    void excessInjectableSlots_mapToMinusOne() throws Exception {
        MeshPositionalBinder.Binding b = bind(
            method("threeProxies", String.class, McpMeshTool.class,
                McpMeshTool.class, McpMeshTool.class),
            List.of(1, 2, 3), null, List.of("a"));

        assertArrayEquals(new int[]{0}, b.depIndexToSlot());
        assertArrayEquals(new int[]{0, -1, -1}, b.slotToDepIndex(),
            "unbacked slots keep their ordinal — they receive null, they do not compact");
    }

    @Test
    void nonPairableSuffix_neverReachesASlot() throws Exception {
        // @MeshService view edges are appended after the explicit @Selector
        // deps and are bound by other means; they must never claim a slot.
        MeshPositionalBinder.Binding b = MeshPositionalBinder.bind(
            method("threeProxies", String.class, McpMeshTool.class,
                McpMeshTool.class, McpMeshTool.class),
            MeshPositionalBinder.slots(List.of(1, 2, 3), null),
            List.of("a", "view_x", "view_y"),
            1);

        assertArrayEquals(new int[]{0, -1, -1}, b.depIndexToSlot());
        assertArrayEquals(new int[]{0, -1, -1}, b.slotToDepIndex());
        assertTrue(b.describe().contains("further declared dependencies are bound by other means"));
    }

    @Test
    void describe_namesBothIndexSpacesAndEverySurplus() throws Exception {
        String text = MeshPositionalBinder.bind(
            method("jobMiddle", String.class, McpMeshTool.class,
                MeshJob.class, McpMeshTool.class),
            MeshPositionalBinder.slots(List.of(1, 3), 2),
            List.of("cap_a", "job_cap", "cap_c", "cap_d"),
            4).describe();

        assertTrue(text.contains("dependency[0] 'cap_a' -> parameter 1"), text);
        assertTrue(text.contains("[proxy slot 0]"), text);
        assertTrue(text.contains("dependency[1] 'job_cap' -> parameter 2"), text);
        assertTrue(text.contains("[job slot]"), text);
        assertTrue(text.contains("dependency[2] 'cap_c' -> parameter 3"), text);
        assertTrue(text.contains("[proxy slot 1]"), text);
        assertTrue(text.contains("dependency[3] 'cap_d' -> (no injectable parameter — dropped)"), text);
    }

    @Test
    void slotsAreOrderedBySignaturePosition_regardlessOfInputOrder() throws Exception {
        Method m = method("jobMiddle", String.class, McpMeshTool.class,
            MeshJob.class, McpMeshTool.class);

        MeshPositionalBinder.Binding shuffled = MeshPositionalBinder.bind(m, List.of(
            new MeshPositionalBinder.Slot(3, MeshPositionalBinder.SlotRole.PROXY),
            new MeshPositionalBinder.Slot(2, MeshPositionalBinder.SlotRole.JOB),
            new MeshPositionalBinder.Slot(1, MeshPositionalBinder.SlotRole.PROXY)),
            List.of("cap_a", "job_cap", "cap_c"), 3);

        assertEquals(List.of(1, 2, 3), shuffled.slotPositions());
        assertArrayEquals(new int[]{0, -1, 1}, shuffled.depIndexToSlot());
        assertEquals(1, shuffled.jobDepIndex());
    }

    @Test
    void duplicateSlotPosition_isRejected() throws Exception {
        Method m = method("threeProxies", String.class, McpMeshTool.class,
            McpMeshTool.class, McpMeshTool.class);

        assertThrows(IllegalArgumentException.class, () -> MeshPositionalBinder.bind(m, List.of(
            new MeshPositionalBinder.Slot(1, MeshPositionalBinder.SlotRole.PROXY),
            new MeshPositionalBinder.Slot(1, MeshPositionalBinder.SlotRole.JOB)),
            List.of("a", "b"), 2));
    }

    @Test
    void multipleJobSlots_areRejected() throws Exception {
        Method m = method("threeProxies", String.class, McpMeshTool.class,
            McpMeshTool.class, McpMeshTool.class);

        assertThrows(IllegalArgumentException.class, () -> MeshPositionalBinder.bind(m, List.of(
            new MeshPositionalBinder.Slot(1, MeshPositionalBinder.SlotRole.JOB),
            new MeshPositionalBinder.Slot(2, MeshPositionalBinder.SlotRole.JOB)),
            List.of("a", "b"), 2));
    }
}
