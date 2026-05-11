package io.mcpmesh.spring.web;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Timing-related assertions for {@link MeshA2ASseDispatcher} (spec §4.6
 * poll cadence, spec §5.1 keepalive interval).
 *
 * <h2>Status: constants-only assertions for now</h2>
 *
 * <p>The exact poll cadence (1s) and keepalive interval (15s) are encoded
 * as {@code public static final long} constants on {@link MeshA2ASseDispatcher}.
 * Asserting wall-clock <em>behavior</em> would require either:
 * <ol>
 *   <li>Standing up a real 15-second sleep — flaky and slow for a unit
 *       test suite that targets sub-second runs;</li>
 *   <li>Injecting a {@link java.time.Clock} or a sleep abstraction into
 *       the dispatcher — a small but production-touching refactor.</li>
 * </ol>
 *
 * <p>This chunk is "verify, don't modify" per task spec. We therefore
 * assert that the constants match the canonical values from the spec
 * here, and observe the qualitative behavior (only-on-change emission,
 * disconnect-safe loop exit) in {@link MeshA2ASseDispatcherStreamTest}.
 *
 * <h3>Follow-up</h3>
 *
 * <p>If we want wall-clock timing assertions in CI, the smallest
 * production change is to extract a package-private
 * {@code Clock + Sleeper} pair on {@link MeshA2ASseDispatcher} that
 * defaults to {@code Clock.systemUTC()} + {@code Thread::sleep}. Tests
 * could then inject a fake clock + count-based sleeper. Tracked
 * separately (Chunk 1C follow-up issue).
 */
@DisplayName("MeshA2ASseDispatcher — timing constants (spec §4.6 / §5.1)")
class MeshA2ASseDispatcherTimingTest {

    /** Spec §4.6 sequence diagram: producer polls JobProxy.status every 1s. */
    @Test
    @DisplayName("POLL_INTERVAL_MILLIS = 1000L (spec §4.6 sequence diagram)")
    void pollCadenceConstant() {
        assertEquals(1000L, MeshA2ASseDispatcher.POLL_INTERVAL_MILLIS,
            "Spec §4.6 sequence diagram specifies a 1-second poll cadence — "
                + "MUST match for cross-runtime parity with Python's _STATUS_POLL_SECS = 1");
    }

    /** Spec §5.1: SSE comment frames emitted every 15s of inactivity. */
    @Test
    @DisplayName("KEEPALIVE_MILLIS = 15_000L (spec §5.1)")
    void keepaliveIntervalConstant() {
        assertEquals(15_000L, MeshA2ASseDispatcher.KEEPALIVE_MILLIS,
            "Spec §5.1 specifies 15s keepalive interval — MUST match for parity "
                + "with Python's _SSE_KEEPALIVE_SECS = 15");
    }

    /** Defensive max-stream cap — production cuts streams off after 1h. */
    @Test
    @DisplayName("MAX_STREAM_MILLIS = 1 hour (defensive cap)")
    void maxStreamCapConstant() {
        assertEquals(60L * 60_000L, MeshA2ASseDispatcher.MAX_STREAM_MILLIS,
            "Defensive 1-hour cap protects a worker thread from being pinned "
                + "indefinitely by a stuck job");
    }
}
