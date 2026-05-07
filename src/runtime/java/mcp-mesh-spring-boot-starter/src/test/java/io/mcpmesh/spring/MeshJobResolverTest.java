package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Flow;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Cross-SDK contract tests for the MeshJob DDDI resolver. Mirrors:
 * <ul>
 *   <li>Python {@code tests/test_resolver_meshjob.py}</li>
 *   <li>TypeScript {@code __tests__/resolver-meshjob.spec.ts}</li>
 * </ul>
 *
 * <p>Each scenario number below maps to {@code MESHJOB_DDDI_CONTRACT.md} →
 * "Equivalence across SDKs" checklist. If a test fails, the resolver
 * implementation has diverged from the contract — fix the resolver, not
 * the test.
 */
class MeshJobResolverTest {

    // ---- Test fixtures (one method per scenario) ----------------------------
    //
    // Java's reflective resolver works against actual method signatures, so
    // each scenario gets a tiny method with the corresponding parameter shape.
    // The bodies are throwaway — only the signatures matter.

    @SuppressWarnings("unused")
    static class Fixtures {
        // Scenario 1: MeshTool only
        public void scenario1_meshToolOnly(
            String userArg,
            McpMeshTool<String> dep
        ) {}

        // Scenario 2: MeshJob only
        public void scenario2_meshJobOnly(
            String userArg,
            MeshJob job
        ) {}

        // Scenario 3: both, MeshJob in the middle
        public void scenario3_both_meshJobMiddle(
            String userId,
            McpMeshTool<String> weather,
            MeshJob job,
            McpMeshTool<String> flights
        ) {}

        // Scenario 4: neither
        public void scenario4_neither(
            String userArg,
            int count
        ) {}

        // Scenario 5: MeshJob trailing
        public void scenario5_meshJobTrailing(
            String userArg,
            McpMeshTool<String> dep,
            MeshJob job
        ) {}

        // Scenario 6: multiple MeshJob → must reject
        public void scenario6_multipleMeshJob(
            String userArg,
            MeshJob job1,
            MeshJob job2
        ) {}

        // Bonus: zero parameters at all
        public void scenarioZero_noParams() {}

        // Bonus: a CompletableFuture-returning method (just to make sure
        // return-type oddities don't trip the resolver — it only inspects
        // parameters).
        public CompletableFuture<Map<String, Object>> scenarioBonus_async(
            String userArg,
            MeshJob job,
            McpMeshTool<Flow.Publisher<String>> stream
        ) {
            return CompletableFuture.completedFuture(Map.of());
        }
    }

    private static Method find(String name) {
        for (Method m : Fixtures.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("Fixture method not found: " + name);
    }

    // ---- Contract tests -----------------------------------------------------

    @Test
    void scenario1_meshToolOnly_unchangedFromPriorBehavior() {
        // Method with McpMeshTool only → unchanged from prior behavior:
        // one mesh tool dep at signature position 1, no mesh job param.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenario1_meshToolOnly"));
        assertEquals(2, r.totalParameterCount());
        assertEquals(1, r.meshToolCount());
        assertEquals(1, r.meshToolPositions().get(0));
        assertFalse(r.hasMeshJob());
        assertTrue(r.meshJobParamIndex().isEmpty());
    }

    @Test
    void scenario2_meshJobOnly_zeroToolsJobIndexRecorded() {
        // Method with MeshJob only → MeshTool count = 0, MeshJob index recorded.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenario2_meshJobOnly"));
        assertEquals(2, r.totalParameterCount());
        assertEquals(0, r.meshToolCount());
        assertTrue(r.hasMeshJob());
        assertEquals(1, r.meshJobParamIndex().orElseThrow());
    }

    @Test
    void scenario3_both_meshJobInMiddle_meshToolPositionsCorrect() {
        // Method with both, MeshJob in middle → MeshTool positions correct
        // (skip MeshJob; positional counter for MeshTool unaffected by it).
        MeshJobResolver.Resolved r =
            MeshJobResolver.resolve(find("scenario3_both_meshJobMiddle"));
        assertEquals(4, r.totalParameterCount());
        assertEquals(2, r.meshToolCount(), "should pick up both MeshTool deps");
        // MeshTool[0] is at signature position 1 (weather); MeshTool[1] is at
        // signature position 3 (flights, NOT 2 — MeshJob at pos 2 is skipped).
        assertEquals(1, r.meshToolPositions().get(0), "first MeshTool at sig pos 1");
        assertEquals(3, r.meshToolPositions().get(1),
            "second MeshTool at sig pos 3 (NOT 2 — MeshJob skipped per contract)");
        assertTrue(r.hasMeshJob());
        assertEquals(2, r.meshJobParamIndex().orElseThrow(),
            "MeshJob recorded at signature position 2");
    }

    @Test
    void scenario4_neither_noDddiMetadata() {
        // Method with neither → no DDDI metadata.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenario4_neither"));
        assertEquals(2, r.totalParameterCount());
        assertEquals(0, r.meshToolCount());
        assertFalse(r.hasMeshJob());
    }

    @Test
    void scenario5_meshJobTrailing_indexAtLastPosition() {
        // Method with MeshJob trailing → meshJobParamIndex = last sig position.
        MeshJobResolver.Resolved r =
            MeshJobResolver.resolve(find("scenario5_meshJobTrailing"));
        assertEquals(3, r.totalParameterCount());
        assertEquals(1, r.meshToolCount(), "MeshTool at signature position 1");
        assertEquals(1, r.meshToolPositions().get(0));
        assertTrue(r.hasMeshJob());
        assertEquals(2, r.meshJobParamIndex().orElseThrow(),
            "MeshJob at last position (sig pos 2)");
    }

    @Test
    void scenario6_multipleMeshJob_throwsAtResolveTime() {
        // Method with two MeshJob params → throws IllegalStateException
        // at resolve time (per contract: "Disallowed in Phase 1").
        Method m = find("scenario6_multipleMeshJob");
        IllegalStateException ex = assertThrows(
            IllegalStateException.class,
            () -> MeshJobResolver.resolve(m)
        );
        // Error message must reference the method name AND mention that
        // a tool may declare at most one MeshJob — same as the contract's
        // mandated wording.
        assertTrue(ex.getMessage().contains("scenario6_multipleMeshJob"),
            "error must reference the offending method, was: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("at most one MeshJob"),
            "error must surface the contract clause, was: " + ex.getMessage());
        // Both colliding positions should be mentioned so users can find
        // the second occurrence — matches the Python error format.
        assertTrue(ex.getMessage().contains("1") && ex.getMessage().contains("2"),
            "error should mention both positions (1 and 2), was: " + ex.getMessage());
    }

    @Test
    void zeroParameters_isHandledCleanly() {
        // Edge case: methods with no params at all should not blow up.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenarioZero_noParams"));
        assertEquals(0, r.totalParameterCount());
        assertEquals(0, r.meshToolCount());
        assertFalse(r.hasMeshJob());
    }

    @Test
    void resolverInspectsParametersOnly_returnTypeIrrelevant() {
        // Make sure CompletableFuture / Flow.Publisher returns don't confuse
        // the resolver — a regression here would mean the resolver was
        // accidentally peeking at the return-type generic args.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenarioBonus_async"));
        assertEquals(3, r.totalParameterCount());
        assertEquals(1, r.meshToolCount());
        assertEquals(2, r.meshToolPositions().get(0),
            "MeshTool at sig pos 2 (after String + MeshJob)");
        assertTrue(r.hasMeshJob());
        assertEquals(1, r.meshJobParamIndex().orElseThrow());
    }

    @Test
    void nullMethod_throwsIllegalArgument() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobResolver.resolve(null));
    }

    @Test
    void resolved_meshToolPositions_isImmutable() {
        // Defensive copy in the Resolved canonical constructor — callers
        // mutating the returned list must NOT affect the resolver's result.
        MeshJobResolver.Resolved r = MeshJobResolver.resolve(find("scenario1_meshToolOnly"));
        assertThrows(UnsupportedOperationException.class,
            () -> r.meshToolPositions().add(99));
    }
}
