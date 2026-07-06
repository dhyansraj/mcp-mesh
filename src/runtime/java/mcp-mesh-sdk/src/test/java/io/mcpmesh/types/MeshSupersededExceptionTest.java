package io.mcpmesh.types;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1278 — typed supersession signal.
 *
 * <p>Covers the pure (no-FFI, no-HTTP) contract of {@link MeshSupersededException}:
 * the reserved marker string, the optional {@code detail} accessor, and the
 * defensive {@link MeshSupersededException#fromEnvelope} recognize parse — the
 * exact byte-shape and classification the consumer proxies rely on. Mirrors the
 * Python reference's {@code parse_superseded_envelope} unit tests.
 */
class MeshSupersededExceptionTest {

    @Test
    void marker_isTheCanonicalClaimSupersededString() {
        // Reused verbatim from the job path (Go ent_service_jobs.go / Rust
        // CLAIM_SUPERSEDED_REASON) — one string end-to-end.
        assertEquals("claim_superseded", MeshSupersededException.CLAIM_SUPERSEDED_MARKER);
    }

    @Test
    void detailAccessor_carriesDetail_orNull() {
        assertEquals("stale", new MeshSupersededException("stale").getDetail());
        assertNull(new MeshSupersededException(null).getDetail());
    }

    // ---- fromEnvelope: recognizes the reserved envelope ---------------------

    @Test
    void fromEnvelope_noDetail_recognized_detailNull() {
        MeshSupersededException e =
            MeshSupersededException.fromEnvelope("{\"error\":\"claim_superseded\"}");
        assertNotNull(e, "the reserved envelope must be recognized");
        assertNull(e.getDetail(), "an absent detail must surface as null");
    }

    @Test
    void fromEnvelope_withDetail_recognized_detailCarried() {
        MeshSupersededException e = MeshSupersededException.fromEnvelope(
            "{\"error\":\"claim_superseded\",\"detail\":\"stale\"}");
        assertNotNull(e);
        assertEquals("stale", e.getDetail(),
            "the detail string must be carried onto the typed signal");
    }

    // ---- fromEnvelope: defensive fall-through -------------------------------

    @Test
    void fromEnvelope_nonJson_returnsNull() {
        assertNull(MeshSupersededException.fromEnvelope("not json"),
            "a non-JSON body must fall through to generic handling");
    }

    @Test
    void fromEnvelope_null_returnsNull() {
        assertNull(MeshSupersededException.fromEnvelope(null));
    }

    @Test
    void fromEnvelope_jsonButNotObject_returnsNull() {
        // A bare JSON string "claim_superseded" is valid JSON but NOT an object.
        assertNull(MeshSupersededException.fromEnvelope("\"claim_superseded\""),
            "a non-object JSON body must not be classified");
        assertNull(MeshSupersededException.fromEnvelope("[\"claim_superseded\"]"));
    }

    @Test
    void fromEnvelope_wrongMarker_returnsNull() {
        // dependency_unavailable (issue #1273) must NOT be misclassified.
        assertNull(MeshSupersededException.fromEnvelope(
            "{\"error\":\"dependency_unavailable\",\"capability\":\"lookup\"}"),
            "a dependency_unavailable envelope must be left alone");
    }

    @Test
    void fromEnvelope_nonStringDetail_treatedAsAbsent() {
        MeshSupersededException e = MeshSupersededException.fromEnvelope(
            "{\"error\":\"claim_superseded\",\"detail\":42}");
        assertNotNull(e, "the marker still classifies even with a bad detail");
        assertNull(e.getDetail(), "a non-string detail must be treated as absent");
    }
}
