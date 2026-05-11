package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Process-local in-memory A2A task store (spec §4.8).
 *
 * <p>Holds task records for {@code tasks/send}, {@code tasks/get},
 * {@code tasks/cancel}, and the long-running paths. In Chunk 1A (sync only)
 * the store is still populated on every successful sync {@code tasks/send}
 * so {@code tasks/get} can return the cached terminal envelope until the
 * 300-second eviction window elapses (spec Appendix B item 5 — match Python
 * exactly for parity).
 *
 * <h2>Eviction</h2>
 *
 * <p>Entries are evicted {@value #TERMINAL_EVICTION_MILLIS} ms after the task
 * first enters a terminal state ({@code completed} / {@code failed} /
 * {@code canceled}). Eviction runs lazily on every store access — no
 * background sweeper is required (spec Appendix B item 5).
 *
 * <h2>Cross-replica semantics</h2>
 *
 * <p>The store is process-local: a {@code tasks/get} against a replica that
 * doesn't own the task returns "Unknown task id" per spec §4.4 / Appendix B
 * item 3. Chunk 1B (long-running) inherits this constraint; Chunk 1C
 * documents it.
 */
public class MeshA2ATaskStore {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ATaskStore.class);

    /**
     * Grace window in milliseconds before a terminal-state task is evicted
     * from the store. Matches Python's {@code _TERMINAL_GRACE_SECS = 300}
     * exactly for cross-runtime parity (spec Appendix B item 5).
     */
    public static final long TERMINAL_EVICTION_MILLIS = 300_000L;

    private final Map<String, TaskRecord> store = new ConcurrentHashMap<>();

    /**
     * Store the task record for {@code taskId}. Caller is responsible for
     * having checked for duplicates via {@link #contains(String)} when
     * uniqueness matters (spec §4.3 idempotency window).
     */
    public void put(String taskId, TaskRecord record) {
        sweepExpired();
        store.put(taskId, record);
    }

    /**
     * Return the record for {@code taskId}, or {@code null} when missing or
     * already evicted. Triggers a lazy sweep on each call.
     */
    public TaskRecord get(String taskId) {
        sweepExpired();
        return store.get(taskId);
    }

    /**
     * @return {@code true} when the store currently holds a record for
     *     {@code taskId} and that record has not been evicted by the lazy
     *     sweep.
     */
    public boolean contains(String taskId) {
        sweepExpired();
        return store.containsKey(taskId);
    }

    /**
     * @return current size (post-sweep). For diagnostics + tests.
     */
    public int size() {
        sweepExpired();
        return store.size();
    }

    /**
     * Lazy sweep: evict any record whose terminal-state timestamp is older
     * than {@link #TERMINAL_EVICTION_MILLIS}. Non-terminal records are
     * never evicted (long-running paths in Chunk 1B keep them alive across
     * arbitrary durations).
     */
    private void sweepExpired() {
        long now = System.currentTimeMillis();
        store.entrySet().removeIf(entry -> {
            Long terminalAt = entry.getValue().terminalAt();
            if (terminalAt == null) {
                return false;
            }
            if (now - terminalAt > TERMINAL_EVICTION_MILLIS) {
                log.debug("Evicting terminal A2A task {} ({}ms after terminal_at)",
                    entry.getKey(), now - terminalAt);
                return true;
            }
            return false;
        });
    }

    /**
     * Atomically mark a previously parked non-terminal record as terminal by
     * stamping {@link TaskRecord#terminalEnvelope()} + {@link TaskRecord#terminalAt()}.
     * No-op when the record is absent or already terminal (idempotent — spec §4.5
     * "Idempotent; best-effort"). Replaces the record so observers of subsequent
     * {@link #get(String)} calls see the cached terminal envelope.
     *
     * @return the new terminal record, or {@code null} when the task is unknown
     */
    public TaskRecord markTerminal(String taskId, Map<String, Object> terminalEnvelope) {
        // Atomically flip to terminal so concurrent callers (e.g. SSE
        // stream completion + tasks/cancel arriving simultaneously) cannot
        // race past the null/terminal-at check and clobber each other's
        // terminal envelope. First-write-wins is preserved: a record that
        // already has terminalAt set is returned unchanged.
        return store.computeIfPresent(taskId, (id, existing) -> {
            if (existing.terminalAt() != null) {
                return existing;
            }
            return new TaskRecord(
                existing.sessionId(),
                existing.requestMessage(),
                terminalEnvelope,
                System.currentTimeMillis(),
                existing.jobProxy()
            );
        });
    }

    /**
     * Cached A2A task envelope plus the metadata needed to keep it alive
     * during the 300s idempotency window.
     *
     * @param sessionId        the A2A session id (defaults to taskId per spec §4.2)
     * @param requestMessage   the originating request {@code message} object
     *                         (echoed into {@code result.history[]}); {@code null}
     *                         when the client omitted it
     * @param terminalEnvelope the full Task envelope cached for {@code tasks/get}
     *                         lookups; {@code null} for non-terminal records
     *                         (long-running paths set this on terminal transition)
     * @param terminalAt       monotonic timestamp (ms since epoch) when the
     *                         task first entered a terminal state, or
     *                         {@code null} when still in-flight
     * @param jobProxy         live consumer-side handle to the underlying mesh
     *                         job; {@code null} for sync (state=completed/failed)
     *                         records that never had a backing JobProxy
     */
    public record TaskRecord(
        String sessionId,
        Map<String, Object> requestMessage,
        Map<String, Object> terminalEnvelope,
        Long terminalAt,
        JobProxy jobProxy
    ) {
        public TaskRecord {
            // Defensive copies: callers should not be able to mutate the
            // stored envelope after handoff.
            if (requestMessage != null) {
                requestMessage = Collections.unmodifiableMap(new LinkedHashMap<>(requestMessage));
            }
            if (terminalEnvelope != null) {
                terminalEnvelope = Collections.unmodifiableMap(new LinkedHashMap<>(terminalEnvelope));
            }
        }

        /**
         * Convenience overload for sync records (no backing JobProxy). Preserves
         * the Chunk 1A constructor surface so existing call sites compile
         * unchanged.
         */
        public TaskRecord(
            String sessionId,
            Map<String, Object> requestMessage,
            Map<String, Object> terminalEnvelope,
            Long terminalAt
        ) {
            this(sessionId, requestMessage, terminalEnvelope, terminalAt, null);
        }
    }
}
