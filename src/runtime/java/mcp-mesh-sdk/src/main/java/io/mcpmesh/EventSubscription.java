package io.mcpmesh;

import io.mcpmesh.core.MeshException;

import java.io.Closeable;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;

/**
 * Long-lived blocking iterator over events posted to a running job's
 * event log. Returned by
 * {@link MeshJobs#subscribeEvents(String, SubscribeOptions)}.
 *
 * <p>Each subscription manages its own cursor — multiple subscribers
 * can observe the same job's events independently without affecting
 * the producer's {@code recvEvent} consumption (the producer's cursor
 * is per-controller; the subscriber's cursor is per-subscription).
 *
 * <p>The iterator runs indefinitely until the caller breaks out of
 * the loop or {@link #close()} is invoked, or the underlying registry
 * raises {@link JobNotFoundException}. There is no automatic terminal-
 * state detection — use a synthetic event type (e.g.
 * {@code {"type":"ended"}}) posted by your application to signal
 * iteration end.
 *
 * <p>Mirrors:
 * <ul>
 *   <li>Python {@code mesh.jobs.subscribe_events} async generator</li>
 *   <li>TypeScript {@code mesh.jobs.subscribeEvents} async generator</li>
 * </ul>
 *
 * <p><b>Closeable contract</b>: implements {@link Closeable} so callers
 * can use try-with-resources. {@link #close()} flips an internal flag
 * that makes the next {@link #hasNext()} return {@code false} without
 * issuing another FFI long-poll, and drops this subscription's
 * {@link JobProxy} reference so the proxy's connection pool can be
 * reclaimed once no other subscribers hold it.
 *
 * <p><strong>Cancellation semantics:</strong> {@link #close()} flips a flag
 * that stops <em>future</em> FFI long-polls — it does NOT interrupt an
 * in-flight long-poll. If another thread is blocked inside the iterator's
 * next FFI call when {@code close()} is invoked, that call runs to its
 * natural {@code longPoll} budget (default 30 seconds) before the iterator
 * sees the close. This differs from Python's {@code asyncio.CancelledError}
 * which actually interrupts the awaited operation. Plumbing true
 * interruption through the FFI is out of scope for the present release.
 * Callers that need rapid shutdown should configure a short {@code longPoll}
 * (e.g. {@link SubscribeOptions.Builder#longPoll(Duration)} with a few
 * seconds) so the in-flight call drains quickly.
 *
 * <p><b>Thread-safety</b>: this class is NOT thread-safe. A single
 * subscription is intended to be consumed by a single thread (or one
 * thread at a time with external synchronisation). The cache reuse
 * in {@link MeshJobs#subscribeEvents} only shares the underlying
 * {@link JobProxy} across subscriptions — the iterator state
 * (buffer, cursor, closed flag) is per-instance.
 */
public final class EventSubscription implements Iterator<Map<String, Object>>, Closeable {

    private final JobProxy proxy;
    private final List<String> types;
    private final Duration longPoll;

    private final Deque<Map<String, Object>> buffer = new ArrayDeque<>();
    private long cursor;
    private volatile boolean closed = false;

    EventSubscription(JobProxy proxy, SubscribeOptions options) {
        this.proxy = proxy;
        this.types = options.types();
        this.longPoll = options.longPoll();
        this.cursor = options.after();
    }

    /**
     * Validate that a {@link Number} from the registry envelope is an
     * integer-valued long: not fractional, not a NaN/Infinity bridge.
     * Returns the long value on success.
     *
     * @throws MeshException if the value cannot be represented exactly
     *     as a long (e.g. {@code 1.5}, {@code NaN}, {@code Infinity}).
     */
    private static long requireIntegralLong(Number n, String fieldName, Object context) {
        // Long / Integer / Short / Byte / AtomicLong / AtomicInteger / BigInteger
        // are all integer-typed and round-trip exactly through longValue().
        // Float / Double / BigDecimal may carry a fractional component or
        // non-finite value that must NOT be silently truncated.
        double d = n.doubleValue();
        if (Double.isNaN(d) || Double.isInfinite(d)) {
            throw new MeshException(
                "subscribeEvents: registry returned non-finite '" + fieldName
                    + "' (" + d + "): " + context);
        }
        long asLong = n.longValue();
        // If the original is a fractional type, doubleValue() != longValue()
        // catches the truncation. Integer types round-trip exactly.
        if ((double) asLong != d) {
            throw new MeshException(
                "subscribeEvents: registry returned fractional '" + fieldName
                    + "' (" + n + "): " + context);
        }
        return asLong;
    }

    /**
     * Block until at least one event is available, the registry
     * returns an empty page that doesn't advance our cursor (which we
     * loop past by issuing another long-poll), or this subscription
     * is closed. Returns {@code false} only after {@link #close()}
     * — the registry side never signals "no more events" because the
     * event channel is an append-only log.
     *
     * @throws JobNotFoundException if the job has been reaped from
     *                              the registry (404 on
     *                              {@code GET /jobs/{id}/events})
     * @throws MeshException        for transport errors after retry
     *                              exhaustion, or malformed events
     *                              (e.g. missing or non-integer
     *                              {@code seq} in the registry
     *                              response)
     */
    @Override
    @SuppressWarnings("unchecked")
    public boolean hasNext() {
        if (!buffer.isEmpty()) {
            return true;
        }
        // Loop past empty pages — the registry may scan a server-side
        // types filter and advance `next_after` without yielding any
        // events; we follow the watermark and poll again. Closing
        // breaks the loop.
        while (!closed) {
            Map<String, Object> envelope = proxy.listEvents(cursor, types, longPoll);
            Object eventsRaw = envelope.get("events");
            Object nextAfterRaw = envelope.get("next_after");
            if (!(eventsRaw instanceof List<?> eventsList)) {
                throw new MeshException(
                    "subscribeEvents: registry envelope missing 'events' array: " + envelope);
            }
            for (Object item : eventsList) {
                if (!(item instanceof Map<?, ?> mapRaw)) {
                    throw new MeshException(
                        "subscribeEvents: registry returned non-object event: " + item);
                }
                Map<String, Object> event = (Map<String, Object>) mapRaw;
                Object seqRaw = event.get("seq");
                // Reject Boolean explicitly because Boolean is NOT a
                // Number subclass on Java BUT autoboxing of a `bool`
                // primitive on the wire could in theory surface as
                // Boolean via Jackson — defensive-depth check
                // mirroring Python's `type(seq) is not int` and TS's
                // explicit `typeof seq === "boolean"` reject branch.
                if (seqRaw instanceof Boolean) {
                    throw new MeshException(
                        "subscribeEvents: registry returned event with boolean 'seq': " + event);
                }
                if (!(seqRaw instanceof Number seqNum)) {
                    throw new MeshException(
                        "subscribeEvents: registry returned event without integer 'seq': " + event);
                }
                long seq = requireIntegralLong(seqNum, "seq", event);
                if (seq > cursor) {
                    cursor = seq;
                }
                // listEvents returns ascending-seq; cursor advance
                // before buffer-push ensures correctness across
                // consumer cancellation (close() between events).
                buffer.addLast(event);
            }
            // Empty pages (or pages filtered by `types` server-side)
            // still advance the cursor via the registry-supplied
            // watermark, so subsequent polls don't re-scan the same
            // filtered range. Mirrors Python's `cursor = max(cursor,
            // next_after)` after the per-event loop.
            if (nextAfterRaw instanceof Number nextAfterNum) {
                long nextAfter = requireIntegralLong(nextAfterNum, "next_after", nextAfterRaw);
                if (nextAfter > cursor) {
                    cursor = nextAfter;
                }
            }
            if (!buffer.isEmpty()) {
                return true;
            }
            // Empty page AND closed — bail. The empty-page-then-poll-
            // again loop is what gives the iterator its long-lived
            // semantics; we only exit on explicit close() or a typed
            // registry exception thrown from listEvents above.
        }
        return false;
    }

    /**
     * Return the next event from the buffer. Each event has the
     * shape {@code {seq, type, payload, trace_context, posted_by,
     * created_at, job_id}}.
     *
     * @throws NoSuchElementException if the subscription is closed
     *                                and no buffered events remain
     */
    @Override
    public Map<String, Object> next() {
        if (buffer.isEmpty() && !hasNext()) {
            throw new NoSuchElementException(
                "EventSubscription is closed and no buffered events remain");
        }
        return buffer.pollFirst();
    }

    /**
     * Stop issuing new FFI long-polls. Idempotent. Subsequent
     * {@link #hasNext()} calls return {@code false} (after draining
     * any buffered events); {@link #next()} throws
     * {@link NoSuchElementException}.
     *
     * <p>Does NOT close the underlying {@link JobProxy} — that proxy
     * is cached by {@link MeshJobs} and may be shared across
     * subscriptions or with {@link MeshJobs#postEvent(String, String, Map)}
     * callers. Dropping the iterator's strong reference is sufficient
     * for cleanup; the cache's LRU eviction handles proxy lifecycle.
     */
    @Override
    public void close() {
        closed = true;
    }

    /** Whether {@link #close()} has been invoked. Test-only. */
    boolean isClosedForTest() {
        return closed;
    }

    /** Current cursor position. Test-only. */
    long cursorForTest() {
        return cursor;
    }
}
