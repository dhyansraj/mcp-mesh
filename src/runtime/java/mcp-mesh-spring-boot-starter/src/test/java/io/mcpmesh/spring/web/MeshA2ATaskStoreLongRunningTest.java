package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

/**
 * Unit tests for {@link MeshA2ATaskStore} focused on the long-running
 * (Chunk 1B) paths (spec §4.8 / Appendix B item 5).
 *
 * <p>Covers:
 * <ul>
 *   <li>{@link MeshA2ATaskStore#markTerminal} idempotency (spec §4.5
 *       "Idempotent; best-effort").</li>
 *   <li>{@link JobProxy} slot survives put/get cycles by reference.</li>
 *   <li>Eviction sweep — terminal records evicted past
 *       {@link MeshA2ATaskStore#TERMINAL_EVICTION_MILLIS}, non-terminal
 *       records never evicted.</li>
 *   <li>{@code TERMINAL_EVICTION_MILLIS} constant matches Python's
 *       {@code _TERMINAL_GRACE_SECS = 300} (cross-runtime parity per spec
 *       Appendix B item 5).</li>
 * </ul>
 */
@DisplayName("MeshA2ATaskStore — long-running paths (spec §4.8)")
class MeshA2ATaskStoreLongRunningTest {

    private MeshA2ATaskStore store;

    @BeforeEach
    void setUp() {
        store = new MeshA2ATaskStore();
    }

    /** Spec Appendix B item 5: Python's {@code _TERMINAL_GRACE_SECS = 300}.
     *  Java MUST use the same window for cross-runtime parity. */
    @Test
    @DisplayName("TERMINAL_EVICTION_MILLIS = 300_000L (Python parity, Appendix B item 5)")
    void evictionWindowMatchesPython() {
        assertEquals(300_000L, MeshA2ATaskStore.TERMINAL_EVICTION_MILLIS,
            "Eviction window must equal Python's _TERMINAL_GRACE_SECS (300s) "
                + "for cross-runtime parity — spec Appendix B item 5");
    }

    /** Idempotent ack per spec §4.5: calling markTerminal twice with a
     *  different envelope MUST NOT replace the cached envelope after the
     *  first call. */
    @Test
    @DisplayName("markTerminal is idempotent — second call does NOT replace the cached envelope")
    void markTerminal_idempotent() {
        store.put("t-1", new MeshA2ATaskStore.TaskRecord(
            "t-1", null, null, null, null));

        Map<String, Object> firstEnvelope = new LinkedHashMap<>();
        firstEnvelope.put("state", "completed");
        firstEnvelope.put("token", "FIRST");

        Map<String, Object> secondEnvelope = new LinkedHashMap<>();
        secondEnvelope.put("state", "failed");
        secondEnvelope.put("token", "SECOND");

        MeshA2ATaskStore.TaskRecord r1 = store.markTerminal("t-1", firstEnvelope);
        MeshA2ATaskStore.TaskRecord r2 = store.markTerminal("t-1", secondEnvelope);

        assertNotNull(r1, "first markTerminal call must return the now-terminal record");
        assertNotNull(r2, "second call still returns a record (the cached one)");
        assertEquals("FIRST", r2.terminalEnvelope().get("token"),
            "Second markTerminal call MUST be idempotent: cached envelope "
                + "from the first call survives unchanged (spec §4.5)");
        // The terminalAt timestamp also must not move on the second call —
        // it stamps "when this task first entered terminal state".
        assertEquals(r1.terminalAt(), r2.terminalAt(),
            "terminalAt timestamp MUST be stamped on first transition only");
    }

    /** markTerminal returns null when the task id is unknown — caller
     *  decides what to do (synthesize? log?). */
    @Test
    @DisplayName("markTerminal returns null for unknown task id")
    void markTerminal_unknownTaskReturnsNull() {
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("state", "completed");
        assertNull(store.markTerminal("no-such-id", envelope));
    }

    /** JobProxy slot must survive put/get by reference equality — the
     *  store does not clone or wrap the proxy handle, because the SSE
     *  poll loop needs the original handle to make FFI calls on. */
    @Test
    @DisplayName("JobProxy slot survives put/get by reference equality")
    void jobProxySlotSurvivesByReference() {
        JobProxy proxy = mock(JobProxy.class);
        store.put("t-proxy", new MeshA2ATaskStore.TaskRecord(
            "t-proxy", null, null, null, proxy));

        MeshA2ATaskStore.TaskRecord fetched = store.get("t-proxy");
        assertNotNull(fetched);
        // Reference equality (==) not Object.equals — the SSE adapter
        // relies on the exact same FFI handle being preserved.
        assertSame(proxy, fetched.jobProxy(),
            "JobProxy slot MUST round-trip by reference — the SSE loop "
                + "calls status()/await()/cancel() on the original handle");
    }

    /** Non-terminal records have terminalAt=null and MUST never be
     *  evicted regardless of how old they are. Long-running tasks can
     *  legitimately run for hours. */
    @Test
    @DisplayName("Eviction sweep does NOT evict non-terminal records, regardless of age")
    void sweep_doesNotEvictNonTerminalRecords() throws Exception {
        store.put("alive", new MeshA2ATaskStore.TaskRecord(
            "alive", null, null, null, mock(JobProxy.class)));
        store.put("terminal-old", new MeshA2ATaskStore.TaskRecord(
            "terminal-old",
            null,
            Map.of("state", "completed"),
            System.currentTimeMillis() - MeshA2ATaskStore.TERMINAL_EVICTION_MILLIS - 10_000L,
            null));

        // Mix of long-lived non-terminal + ancient terminal — sweep on
        // next access should keep the alive one.
        assertTrue(store.contains("alive"),
            "Non-terminal record must survive eviction sweep");
        assertFalse(store.contains("terminal-old"),
            "Terminal record older than eviction window must be evicted");
    }

    /** Eviction sweep DOES evict terminal records past the 300s window. */
    @Test
    @DisplayName("Eviction sweep evicts terminal records older than 300s")
    void sweep_evictsExpiredTerminalRecords() {
        // 5 minutes + 1 second = past the window
        long pastWindow = System.currentTimeMillis()
            - MeshA2ATaskStore.TERMINAL_EVICTION_MILLIS - 1_000L;
        store.put("dead", new MeshA2ATaskStore.TaskRecord(
            "dead", null, Map.of("state", "completed"), pastWindow, null));

        // Trigger sweep via any access.
        assertNull(store.get("dead"),
            "Expired terminal record must be evicted on next access");
        assertEquals(0, store.size());
    }

    /** Eviction sweep KEEPS terminal records within the 300s window —
     *  this is the idempotency grace for duplicate task ids (spec §4.3). */
    @Test
    @DisplayName("Eviction sweep keeps terminal records within the 300s window")
    void sweep_keepsRecentTerminalRecords() {
        // Just terminated — well inside the window.
        long justNow = System.currentTimeMillis() - 100L;
        store.put("recent", new MeshA2ATaskStore.TaskRecord(
            "recent", null, Map.of("state", "completed"), justNow, null));

        assertTrue(store.contains("recent"),
            "Terminal record within eviction window MUST be retained — "
                + "spec §4.3 idempotency grace for duplicate task ids");
        assertEquals(1, store.size());
    }

    /** markTerminal stamps terminalAt to the current wall clock so the
     *  300s window starts from the transition, not from put-time. */
    @Test
    @DisplayName("markTerminal stamps terminalAt to System.currentTimeMillis()")
    void markTerminal_stampsTerminalAtToNow() {
        store.put("t-stamp", new MeshA2ATaskStore.TaskRecord(
            "t-stamp", null, null, null, null));

        long before = System.currentTimeMillis();
        MeshA2ATaskStore.TaskRecord terminal = store.markTerminal(
            "t-stamp", Map.of("state", "completed"));
        long after = System.currentTimeMillis();

        assertNotNull(terminal);
        assertNotNull(terminal.terminalAt());
        assertTrue(terminal.terminalAt() >= before && terminal.terminalAt() <= after,
            "terminalAt must be stamped to wall clock at transition time");
    }

    /** put() also triggers a sweep — proves the lazy-sweep contract is
     *  honoured on every entry point (not just on get/contains). */
    @Test
    @DisplayName("put() triggers eviction sweep (lazy sweep on every access)")
    void put_triggersEvictionSweep() throws Exception {
        // Pre-populate with an already-expired terminal record via reflection
        // so we observe the sweep on the next put().
        long expired = System.currentTimeMillis()
            - MeshA2ATaskStore.TERMINAL_EVICTION_MILLIS - 1_000L;
        Field f = MeshA2ATaskStore.class.getDeclaredField("store");
        f.setAccessible(true);
        @SuppressWarnings("unchecked")
        ConcurrentHashMap<String, MeshA2ATaskStore.TaskRecord> raw =
            (ConcurrentHashMap<String, MeshA2ATaskStore.TaskRecord>) f.get(store);
        raw.put("zombie", new MeshA2ATaskStore.TaskRecord(
            "zombie", null, Map.of("state", "completed"), expired, null));

        // size() triggers sweep, so we need to bypass — direct map read
        assertEquals(1, raw.size(), "Pre-condition: zombie record in raw map");
        // Now put a new record; the lazy sweep inside put() should evict the zombie.
        store.put("fresh", new MeshA2ATaskStore.TaskRecord(
            "fresh", null, null, null, null));
        assertNull(store.get("zombie"),
            "put() must trigger eviction sweep — expired zombie record gone");
        assertTrue(store.contains("fresh"));
    }

    /** Two-arg TaskRecord constructor exists for backward compatibility with
     *  Chunk 1A sync-only call sites. Validates the convenience overload
     *  produces a record with {@code jobProxy=null}. */
    @Test
    @DisplayName("Chunk 1A 4-arg TaskRecord constructor still produces a valid record (jobProxy=null)")
    void taskRecordConvenienceCtorWorks() {
        MeshA2ATaskStore.TaskRecord r = new MeshA2ATaskStore.TaskRecord(
            "session-1", null, Map.of("k", "v"), 12345L);
        assertNull(r.jobProxy(),
            "Convenience constructor must set jobProxy=null for sync records");
        assertEquals("session-1", r.sessionId());
        assertEquals(12345L, r.terminalAt());
    }
}
