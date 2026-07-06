package io.mcpmesh;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the WAVE 2c cursor-resume serialization seam (issue #1277) —
 * {@link JobController#serializeRecvCursor(Map)}. This is the exact JSON-object
 * string handed to the native {@code mesh_job_controller_new_with_resume} entry
 * point, so it stays below the FFI boundary (no live registry / native handle
 * needed — the full resume round-trip is a Wave-3 integration UC).
 *
 * <p>Contract: a well-formed cursor becomes {@code {"key": seq, ...}}; a
 * null/empty/non-integer cursor becomes {@code null} (native "no seed" ⇒
 * replay-from-0). Serialization never throws — resume is best-effort, a bad
 * cursor silently degrades to replay-from-0.
 */
class JobControllerResumeCursorTest {

    @Test
    void serializeRecvCursor_buildsJsonObjectOfSeqs() {
        Map<String, Object> cursor = new LinkedHashMap<>();
        cursor.put("answer", 3);
        cursor.put("signal", 7L);
        String json = JobController.serializeRecvCursor(cursor);
        assertNotNull(json);
        // Order-preserving LinkedHashMap → deterministic JSON.
        assertEquals("{\"answer\":3,\"signal\":7}", json);
    }

    @Test
    void serializeRecvCursor_singleKey() {
        String json = JobController.serializeRecvCursor(Map.of("answer", 42));
        assertEquals("{\"answer\":42}", json);
    }

    @Test
    void serializeRecvCursor_nullOrEmpty_returnsNull() {
        assertNull(JobController.serializeRecvCursor(null),
            "null cursor ⇒ no seed (replay-from-0)");
        assertNull(JobController.serializeRecvCursor(Map.of()),
            "empty cursor ⇒ no seed (replay-from-0)");
    }

    @Test
    void serializeRecvCursor_nonIntegerValues_filteredOut() {
        Map<String, Object> cursor = new LinkedHashMap<>();
        cursor.put("answer", 5);
        cursor.put("bogus", "not-a-number");
        cursor.put("nullish", null);
        String json = JobController.serializeRecvCursor(cursor);
        // Only the integer-valued entry survives.
        assertEquals("{\"answer\":5}", json);
    }

    @Test
    void serializeRecvCursor_allNonInteger_returnsNull() {
        Map<String, Object> cursor = new LinkedHashMap<>();
        cursor.put("a", "x");
        cursor.put("b", null);
        assertNull(JobController.serializeRecvCursor(cursor),
            "a cursor with no integer seqs ⇒ no seed (replay-from-0)");
    }

    @Test
    void serializeRecvCursor_mixedMap_keepsOnlyNonNegativeIntegers() {
        // Shared cross-runtime mixed-map contract (Python/TS/Java identical):
        // only "a":4 survives — negatives, fractions, and non-numbers drop.
        Map<String, Object> cursor = new LinkedHashMap<>();
        cursor.put("a", 4);        // non-negative int  → keep
        cursor.put("b", -1);       // negative int      → drop
        cursor.put("c", 2.5d);     // fractional Double → drop (NO truncation)
        cursor.put("d", "x");      // non-number        → drop
        String json = JobController.serializeRecvCursor(cursor);
        assertEquals("{\"a\":4}", json);
    }

    @Test
    void serializeRecvCursor_fractionalNotTruncated() {
        // A lone fractional value must NOT longValue()-truncate to 2 — it is
        // rejected, leaving no surviving entry ⇒ null (replay-from-0).
        assertNull(JobController.serializeRecvCursor(Map.of("work", 2.5d)),
            "fractional Double must be rejected, never truncated");
    }

    @Test
    void serializeRecvCursor_negativeDropped() {
        assertNull(JobController.serializeRecvCursor(Map.of("work", -1)),
            "negative seq ⇒ dropped ⇒ no seed");
    }

    @Test
    void serializeRecvCursor_zeroIsKept() {
        assertEquals("{\"work\":0}", JobController.serializeRecvCursor(Map.of("work", 0)));
    }

    @Test
    void openWithResume_validatesRequiredArgs() {
        Map<String, Object> cursor = Map.of("answer", 1);
        assertThrows(IllegalArgumentException.class,
            () -> JobController.openWithResume(null, "inst", "http://x", null, cursor));
        assertThrows(IllegalArgumentException.class,
            () -> JobController.openWithResume("job", "", "http://x", null, cursor));
        assertThrows(IllegalArgumentException.class,
            () -> JobController.openWithResume("job", "inst", null, null, cursor));
    }
}
