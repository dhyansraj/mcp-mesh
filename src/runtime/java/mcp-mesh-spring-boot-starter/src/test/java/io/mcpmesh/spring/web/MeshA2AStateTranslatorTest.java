package io.mcpmesh.spring.web;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link MeshA2AStateTranslator} (spec §7.2).
 *
 * <p>This is the boundary between the mesh job substrate (UK-spelled
 * {@code cancelled}) and A2A v1.0 (US-spelled {@code canceled}). The
 * translator must:
 * <ul>
 *   <li>map every mesh status to one of the four enumerated A2A states;</li>
 *   <li>translate {@code cancelled} → {@code canceled} (spec Appendix B item);</li>
 *   <li>never return an A2A state outside the enumerated set, even on
 *       unknown / null input (fall back to {@code working}).</li>
 * </ul>
 */
@DisplayName("MeshA2AStateTranslator — mesh status ↔ A2A state mapping (spec §7.2)")
class MeshA2AStateTranslatorTest {

    /**
     * Spec §7.2 mapping table — every mesh status must produce the
     * enumerated A2A state, including the UK→US "cancelled" → "canceled"
     * boundary explicitly called out in spec Appendix B.
     */
    @ParameterizedTest(name = "fromMesh(\"{0}\") = \"{1}\"")
    @CsvSource({
        "working,    working",
        "completed,  completed",
        "failed,     failed",
        "cancelled,  canceled",   // UK→US boundary — spec Appendix B item
        "canceled,   canceled"    // Already US-spelled (defensive identity)
    })
    void fromMesh_translatesAllKnownStatuses(String meshStatus, String expectedA2A) {
        assertEquals(expectedA2A, MeshA2AStateTranslator.fromMesh(meshStatus),
            "Mesh status '" + meshStatus + "' should map to A2A '" + expectedA2A + "'");
    }

    /** Spec §7.2: null input falls back to {@code working}. */
    @Test
    @DisplayName("fromMesh(null) falls back to 'working' (spec §7.2 default)")
    void fromMesh_nullFallsBackToWorking() {
        assertEquals("working", MeshA2AStateTranslator.fromMesh(null));
    }

    /** Spec §7.2: empty string treated as missing. */
    @Test
    @DisplayName("fromMesh(\"\") falls back to 'working' (spec §7.2 default)")
    void fromMesh_emptyFallsBackToWorking() {
        assertEquals("working", MeshA2AStateTranslator.fromMesh(""));
    }

    /** Spec §7.2: unknown mesh state falls back to working — never emit out-of-enum. */
    @ParameterizedTest(name = "fromMesh(\"{0}\") falls back to 'working'")
    @CsvSource({
        "pending",       // Mesh state we haven't mapped to A2A
        "running",       // Synonym for working in some runtimes — still fallback
        "cancelling",    // Mid-cancellation transitional state
        "unknown",
        "BANANA",        // Total garbage
        "WORKING"        // Wrong case — switch is case-sensitive
    })
    void fromMesh_unknownFallsBackToWorking(String unknownState) {
        assertEquals("working", MeshA2AStateTranslator.fromMesh(unknownState),
            "Unknown mesh status '" + unknownState + "' must fall back to 'working' "
                + "to preserve the spec §7.2 invariant: emitted state ∈ "
                + "{working, completed, failed, canceled}");
    }

    /** Constants must literally be the A2A v1.0 wire values. */
    @Test
    @DisplayName("A2A state constants match spec §7.1 exactly")
    void constants_matchSpec() {
        assertEquals("working", MeshA2AStateTranslator.A2A_WORKING);
        assertEquals("completed", MeshA2AStateTranslator.A2A_COMPLETED);
        assertEquals("failed", MeshA2AStateTranslator.A2A_FAILED);
        // The whole point: US spelling (no second 'l').
        assertEquals("canceled", MeshA2AStateTranslator.A2A_CANCELED);
        assertNotEquals("cancelled", MeshA2AStateTranslator.A2A_CANCELED,
            "A2A_CANCELED must be US-spelled 'canceled' (one 'l'), NOT UK 'cancelled'");
    }

    /** Spec §5.3: terminal states are the three end-of-task A2A states. */
    @Test
    @DisplayName("isTerminal returns true only for completed/failed/canceled")
    void isTerminal_recognisesAllThreeTerminalStates() {
        assertTrue(MeshA2AStateTranslator.isTerminal("completed"));
        assertTrue(MeshA2AStateTranslator.isTerminal("failed"));
        assertTrue(MeshA2AStateTranslator.isTerminal("canceled"));
    }

    /** isTerminal is strict: working and unknowns are NOT terminal. */
    @Test
    @DisplayName("isTerminal returns false for working / null / unknown / UK 'cancelled'")
    void isTerminal_rejectsNonTerminalAndUkSpelling() {
        assertFalse(MeshA2AStateTranslator.isTerminal("working"));
        assertFalse(MeshA2AStateTranslator.isTerminal(null));
        assertFalse(MeshA2AStateTranslator.isTerminal(""));
        assertFalse(MeshA2AStateTranslator.isTerminal("submitted"));
        // isTerminal operates on A2A states (US spelling); UK 'cancelled'
        // is NOT a valid A2A state and must not be recognised here. The
        // mesh-side check is via isMeshTerminal.
        assertFalse(MeshA2AStateTranslator.isTerminal("cancelled"),
            "isTerminal checks A2A states — UK 'cancelled' must NOT match");
    }

    /** isMeshTerminal accepts BOTH UK + US spellings because the mesh
     *  substrate emits UK and the normalizer might already have translated. */
    @Test
    @DisplayName("isMeshTerminal accepts both UK ('cancelled') and US ('canceled')")
    void isMeshTerminal_acceptsBothSpellings() {
        assertTrue(MeshA2AStateTranslator.isMeshTerminal("completed"));
        assertTrue(MeshA2AStateTranslator.isMeshTerminal("failed"));
        assertTrue(MeshA2AStateTranslator.isMeshTerminal("cancelled"));  // UK
        assertTrue(MeshA2AStateTranslator.isMeshTerminal("canceled"));   // US
        assertFalse(MeshA2AStateTranslator.isMeshTerminal("working"));
        assertFalse(MeshA2AStateTranslator.isMeshTerminal(null));
        assertFalse(MeshA2AStateTranslator.isMeshTerminal("pending"));
    }

    /** meshStatusOf reads the 'status' key from a {@code JobProxy.status()} payload. */
    @Test
    @DisplayName("meshStatusOf extracts 'status' field from JobProxy status payload")
    void meshStatusOf_extractsStatusField() {
        Map<String, Object> payload = new HashMap<>();
        payload.put("status", "working");
        payload.put("progress", 0.5);
        assertEquals("working", MeshA2AStateTranslator.meshStatusOf(payload));
    }

    /** meshStatusOf returns null when the payload has no status key — caller
     *  then defaults to A2A 'working' via fromMesh(null). */
    @Test
    @DisplayName("meshStatusOf returns null for null / empty / missing 'status' key")
    void meshStatusOf_returnsNullWhenAbsent() {
        assertNull(MeshA2AStateTranslator.meshStatusOf(null));
        assertNull(MeshA2AStateTranslator.meshStatusOf(new HashMap<>()));
        Map<String, Object> noStatus = new HashMap<>();
        noStatus.put("progress", 0.5);
        assertNull(MeshA2AStateTranslator.meshStatusOf(noStatus));
    }

    /** meshStatusOf coerces non-string status values via toString — defensive
     *  against runtimes that emit an enum or symbol. */
    @Test
    @DisplayName("meshStatusOf coerces non-string status values via toString()")
    void meshStatusOf_coercesNonString() {
        Map<String, Object> payload = new HashMap<>();
        payload.put("status", 42); // Unexpected, but don't crash.
        assertEquals("42", MeshA2AStateTranslator.meshStatusOf(payload));
    }

    /** End-to-end: meshStatusOf + fromMesh chained — the canonical
     *  consumer flow inside the dispatcher. */
    @Test
    @DisplayName("Pipeline: meshStatusOf + fromMesh handles UK 'cancelled' end-to-end")
    void pipeline_cancelledMeshStatusBecomesCanceledA2AState() {
        Map<String, Object> meshPayload = new HashMap<>();
        meshPayload.put("status", "cancelled");  // UK from mesh substrate
        String meshState = MeshA2AStateTranslator.meshStatusOf(meshPayload);
        String a2aState = MeshA2AStateTranslator.fromMesh(meshState);
        assertEquals("canceled", a2aState,
            "End-to-end pipeline must translate UK 'cancelled' to US 'canceled' "
                + "at the producer boundary (spec Appendix B)");
    }
}
