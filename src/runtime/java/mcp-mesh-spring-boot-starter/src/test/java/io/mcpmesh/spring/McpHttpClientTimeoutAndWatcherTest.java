package io.mcpmesh.spring;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 LOW coverage for {@link McpHttpClient}:
 *
 * <ul>
 *   <li>Job-cancel watcher subscribe race: a token that fires concurrently
 *       with a new call's subscribe previously left the cancel runnable
 *       never-invoked (CopyOnWriteArrayList iteration snapshot) — the call
 *       ran to its read timeout. subscribe() after a GENUINE cancel must run
 *       immediately; a natural-end wake must never run subscribers (it would
 *       cancel healthy in-flight calls — review follow-up).</li>
 *   <li>X-Mesh-Timeout parse asymmetry: outbound parsed with
 *       {@code Integer.parseInt} + empty catch while inbound parses double.
 *       Outbound now parses double (fractional budgets survive) and logs on
 *       failure.</li>
 * </ul>
 */
@DisplayName("McpHttpClient — timeout parse + cancel-watcher race (issue #1164 LOW)")
class McpHttpClientTimeoutAndWatcherTest {

    // ── JobCancelWatcher fire/subscribe contract ────────────────────────────

    @Test
    @DisplayName("subscribe AFTER a genuine cancel fired runs the runnable immediately")
    void subscribeAfterFireRunsImmediately() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        watcher.fireSubscribers(); // genuine cancel fired before the call subscribed

        watcher.subscribe(ran::incrementAndGet);
        assertEquals(1, ran.get(),
            "late subscriber must run immediately — otherwise the in-flight call "
                + "runs to its read timeout despite the job being cancelled");
    }

    @Test
    @DisplayName("natural job end discards subscribers WITHOUT running them")
    void naturalEndDoesNotRunSubscribers() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        watcher.subscribe(ran::incrementAndGet);
        watcher.completeNaturally(); // job finished without cancel

        assertEquals(0, ran.get(),
            "a natural-end wake must not abort still-in-flight outbound calls — "
                + "they belong to async work that legitimately outlives the handler");
    }

    @Test
    @DisplayName("subscribe AFTER a natural-end wake is a no-op (healthy late call proceeds)")
    void subscribeAfterNaturalEndDoesNotRun() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        watcher.completeNaturally();

        watcher.subscribe(ran::incrementAndGet);
        assertEquals(0, ran.get(),
            "a call subscribing in the natural-end wake → watcher-removal window must "
                + "NOT be cancelled — the job completed normally (#1164 review: the "
                + "failure mode must never flip from 'slow' to 'kills a healthy call')");
    }

    @Test
    @DisplayName("subscribe BEFORE fire runs on fire (and only once)")
    void subscribeBeforeFireRunsOnFire() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        watcher.subscribe(ran::incrementAndGet);
        assertEquals(0, ran.get(), "must not run before the token fires");

        watcher.fireSubscribers();
        assertEquals(1, ran.get(), "must run exactly once on fire");
    }

    @Test
    @DisplayName("unsubscribed runnable does not run on fire")
    void unsubscribePreventsRun() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        Runnable r = ran::incrementAndGet;
        watcher.subscribe(r);
        watcher.unsubscribe(r);

        watcher.fireSubscribers();
        assertEquals(0, ran.get());
    }

    @Test
    @DisplayName("a throwing subscriber does not prevent the others from running")
    void throwingSubscriberIsIsolated() {
        McpHttpClient.JobCancelWatcher watcher = new McpHttpClient.JobCancelWatcher();
        AtomicInteger ran = new AtomicInteger();

        watcher.subscribe(() -> { throw new IllegalStateException("boom"); });
        watcher.subscribe(ran::incrementAndGet);

        watcher.fireSubscribers();
        assertEquals(1, ran.get());
    }

    // ── X-Mesh-Timeout / MCP_MESH_CALL_TIMEOUT parsing ──────────────────────

    @Test
    @DisplayName("integer timeout values parse as before")
    void integerTimeoutParses() {
        assertEquals(120, McpHttpClient.parseTimeoutSecs("120", "test", 300));
        assertEquals(1, McpHttpClient.parseTimeoutSecs("1", "test", 300));
    }

    @Test
    @DisplayName("fractional timeout values parse (like the inbound double-parse path)")
    void fractionalTimeoutParses() {
        // Round, don't truncate — matches MeshToolWrapper's inbound semantics.
        assertEquals(3, McpHttpClient.parseTimeoutSecs("2.5", "test", 300));
        // Sub-second budgets clamp to the 1s floor instead of collapsing to 0.
        assertEquals(1, McpHttpClient.parseTimeoutSecs("0.4", "test", 300));
    }

    @Test
    @DisplayName("absent / invalid / non-positive values fall back to the default")
    void invalidTimeoutFallsBack() {
        assertEquals(300, McpHttpClient.parseTimeoutSecs(null, "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("  ", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("abc", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("-1", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("0", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("NaN", "test", 300));
        assertEquals(300, McpHttpClient.parseTimeoutSecs("Infinity", "test", 300));
    }
}
