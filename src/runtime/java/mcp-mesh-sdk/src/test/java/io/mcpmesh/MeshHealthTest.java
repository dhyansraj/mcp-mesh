package io.mcpmesh;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * {@link MeshHealth} construction rules (issue #1474).
 *
 * <p>{@link MeshHealth#degraded} is deprecated (issue #1515) and still under
 * test on purpose: the deprecation promises source compatibility until 4.0, so
 * the factory has to keep constructing exactly what it always did. The
 * suppression is what keeps that promise visible instead of drowning the build
 * in notices about a call this class exists to make.
 */
@SuppressWarnings("deprecation")
class MeshHealthTest {

    @Test
    void factoriesCarryTheRequestedStatus() {
        assertEquals(MeshHealthStatus.HEALTHY, MeshHealth.healthy().status());
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealth.degraded("slow").status());
        assertEquals(MeshHealthStatus.UNHEALTHY, MeshHealth.unhealthy("down").status());
        assertEquals(List.of("down"), MeshHealth.unhealthy("down").errors());
    }

    @Test
    void aNullErrorMessageDoesNotStopTheAgentBeingWithdrawn() {
        // List.of(errors) raised a NullPointerException OUT of the health
        // check, which the runtime then recorded as DEGRADED — so an agent that
        // explicitly declared itself unable to serve kept heartbeating. The
        // STATUS is what routing depends on; a missing error string is
        // cosmetic and must not change it.
        MeshHealth health = MeshHealth.unhealthy((String) null);

        assertEquals(MeshHealthStatus.UNHEALTHY, health.status());
        assertTrue(health.errors().isEmpty());
    }

    @Test
    void nullsAreDroppedFromEveryFactory() {
        assertEquals(List.of("real"), MeshHealth.unhealthy(null, "real", null).errors());
        assertEquals(MeshHealthStatus.UNHEALTHY,
            MeshHealth.unhealthy(null, "real", null).status());

        assertEquals(List.of("real"), MeshHealth.degraded(null, "real").errors());
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealth.degraded((String) null).status());

        assertEquals(List.of("real"), MeshHealth.of("unhealthy", null, "real").errors());
        assertEquals(MeshHealthStatus.UNHEALTHY, MeshHealth.of("unhealthy", (String) null).status());
    }

    @Test
    void aNullVarargsArrayIsTreatedAsNoErrors() {
        assertEquals(MeshHealthStatus.UNHEALTHY, MeshHealth.unhealthy((String[]) null).status());
        assertTrue(MeshHealth.unhealthy((String[]) null).errors().isEmpty());
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealth.degraded((String[]) null).status());
    }

    @Test
    void theCanonicalConstructorAlsoToleratesNullErrors() {
        // Every other path (withError, a direct `new MeshHealth(...)` from the
        // runtime) funnels through the compact constructor.
        List<String> withNulls = new ArrayList<>(Arrays.asList("a", null, "b"));
        MeshHealth health = new MeshHealth(MeshHealthStatus.UNHEALTHY, null, withNulls);

        assertEquals(List.of("a", "b"), health.errors());
        assertEquals(MeshHealthStatus.UNHEALTHY, health.status());
        assertDoesNotThrow(() -> MeshHealth.healthy().withError(null));
    }

    @Test
    void nullChecksAndErrorsBecomeEmptyNotNull() {
        MeshHealth health = new MeshHealth(MeshHealthStatus.HEALTHY, null, null);

        assertNotNull(health.checks());
        assertNotNull(health.errors());
        assertTrue(health.checks().isEmpty());
        assertTrue(health.errors().isEmpty());
    }

    @Test
    void statusIsStillRequired() {
        // The one thing that must never be guessed.
        assertThrows(NullPointerException.class,
            () -> new MeshHealth(null, Map.of(), List.of()));
    }

    @Test
    void withersReturnCopiesAndDoNotMutate() {
        MeshHealth base = MeshHealth.healthy();
        MeshHealth extended = base.withCheck("a", true).withError("boom");

        assertTrue(base.checks().isEmpty());
        assertTrue(base.errors().isEmpty());
        assertEquals(Map.of("a", true), extended.checks());
        assertEquals(List.of("boom"), extended.errors());
        assertEquals(MeshHealthStatus.HEALTHY, extended.status());
    }

    @Test
    void checksAreDefensivelyCopiedAndImmutable() {
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("a", true);
        MeshHealth health = new MeshHealth(MeshHealthStatus.HEALTHY, source, null);

        source.put("b", false);
        assertEquals(Map.of("a", true), health.checks(), "must not alias the caller's map");
        assertThrows(UnsupportedOperationException.class, () -> health.checks().put("c", 1));
    }

    @Test
    void unknownWireStatusIsDegradedNotUnhealthy() {
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealth.of("mostly fine").status());
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealthStatus.fromWire(null));
        assertEquals(MeshHealthStatus.UNHEALTHY, MeshHealthStatus.fromWire(" UNHEALTHY "));
        assertEquals("unhealthy", MeshHealthStatus.UNHEALTHY.wireValue());
    }

    // The verdict is the same DEGRADED either way; what differs is whether the
    // runtime can tell it assigned it. `fromWire` folds the two together, so
    // `of()` parses instead — otherwise `MeshHealth.of(vendorStatus)` with an
    // unreadable string warns the author about MeshHealth.degraded(), an API
    // they never called (issue #1515).
    @Test
    void anUnreadableStatusIsMarkedAsTheRuntimesOwnVerdict() {
        MeshHealth health = MeshHealth.of("mostly fine", "vendor said so");

        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        assertTrue(health.isUnreadableStatus());
        assertEquals(false, health.checks().get(MeshHealth.UNREADABLE_STATUS_CHECK));
        // The caller's own reasons survive; the parse failure is appended.
        assertEquals(List.of("vendor said so", "Unrecognized health status: mostly fine"),
            health.errors());

        assertTrue(MeshHealth.of(null).isUnreadableStatus());
        assertNull(MeshHealthStatus.parseWire("mostly fine"));
        assertNull(MeshHealthStatus.parseWire(null));
    }

    @Test
    void aReadableStatusIsNotMarked() {
        assertFalse(MeshHealth.of(" DeGrAdEd ").isUnreadableStatus());
        assertEquals(MeshHealthStatus.DEGRADED, MeshHealth.of(" DeGrAdEd ").status());
        assertFalse(MeshHealth.of("healthy").isUnreadableStatus());
        assertFalse(MeshHealth.unhealthy("down").isUnreadableStatus());
        assertFalse(MeshHealth.degraded("slow").isUnreadableStatus());
        assertTrue(MeshHealth.of("mostly fine").checks().containsKey(
            MeshHealth.UNREADABLE_STATUS_CHECK));
        assertTrue(MeshHealth.of("healthy").checks().isEmpty());
    }

    @Test
    void isServingTracksTheHeartbeatRule() {
        assertTrue(MeshHealth.healthy().isServing());
        assertTrue(MeshHealth.degraded("slow").isServing());
        assertFalse(MeshHealth.unhealthy("down").isServing());
    }
}
