package io.mcpmesh;

import io.mcpmesh.core.MeshException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.Closeable;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Deque;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.locks.ReentrantReadWriteLock;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link MeshJobs#subscribeEvents(String, SubscribeOptions)}
 * + {@link EventSubscription}. Mirrors the Python {@code jobs_test.py}
 * subscribe-events coverage and TypeScript {@code jobs.spec.ts}
 * {@code subscribeEvents} suite.
 *
 * <p>The FFI long-poll round trip (envelope parse → cursor advance →
 * yield) is exercised in the integration suite
 * (uc23_meshjob_java/tc27_subscribe_events_streams_observer_pattern_java)
 * because it needs a live registry + Rust core.
 *
 * <p>The {@link EventSubscription} class is package-private to allow
 * direct construction with a stub {@link JobProxy} would require
 * mocking the JNR-FFI surface — not a pattern this codebase uses.
 * Instead we exercise the iterator's buffer/cursor/closed state via
 * reflection into the package-private constructor + buffer field,
 * which lets us cover the non-FFI code paths (Closeable contract,
 * malformed-payload rejection) without a live registry.
 */
class MeshJobsSubscribeEventsTest {

    private static final String FAKE_REGISTRY = "http://localhost:0/no-such";

    @BeforeEach
    void clearCache() {
        MeshJobs.clearProxyCacheForTest();
    }

    @AfterEach
    void clearCacheAfter() {
        MeshJobs.clearProxyCacheForTest();
    }

    // -----------------------------------------------------------------
    // Surface-shape tests — pin the public API one-to-one with Python/TS
    // -----------------------------------------------------------------

    @Test
    void subscribeEvents_hasExpectedSignature() throws NoSuchMethodException {
        Method m = MeshJobs.class.getMethod("subscribeEvents", String.class, SubscribeOptions.class);
        assertEquals(EventSubscription.class, m.getReturnType());
        assertTrue(java.lang.reflect.Modifier.isPublic(m.getModifiers()));
        assertTrue(java.lang.reflect.Modifier.isStatic(m.getModifiers()),
            "subscribeEvents must be a static helper");
        assertEquals(0, m.getExceptionTypes().length,
            "subscribeEvents must not declare checked exceptions");
    }

    @Test
    void subscribeEvents_convenienceOverloadExists() throws NoSuchMethodException {
        Method m = MeshJobs.class.getMethod("subscribeEvents", String.class);
        assertEquals(EventSubscription.class, m.getReturnType());
        assertTrue(java.lang.reflect.Modifier.isStatic(m.getModifiers()));
    }

    @Test
    void eventSubscription_implementsCloseableIterator() {
        assertTrue(Closeable.class.isAssignableFrom(EventSubscription.class),
            "EventSubscription must be Closeable for try-with-resources support");
        assertTrue(Iterator.class.isAssignableFrom(EventSubscription.class),
            "EventSubscription must be Iterator<Map<String,Object>>");
    }

    @Test
    void subscribeOptions_defaultsMatchPythonAndTs() {
        SubscribeOptions opts = SubscribeOptions.defaults();
        assertNull(opts.types(), "default types must be null (≡ all types)");
        assertEquals(0L, opts.after(), "default after cursor must be 0");
        assertEquals(Duration.ofSeconds(30), opts.longPoll(),
            "default long-poll must be 30s (matches Python's long_poll_secs=30.0)");
    }

    @Test
    void subscribeOptions_builderRoundTrips() {
        SubscribeOptions opts = SubscribeOptions.builder()
            .types(List.of("progress", "result"))
            .after(42L)
            .longPoll(Duration.ofSeconds(5))
            .build();
        assertEquals(List.of("progress", "result"), opts.types());
        assertEquals(42L, opts.after());
        assertEquals(Duration.ofSeconds(5), opts.longPoll());
    }

    @Test
    void subscribeOptions_typesAreImmutable() {
        // Caller mutation after build() must NOT affect the captured
        // filter list — defensive copy on the builder side.
        java.util.ArrayList<String> mutable = new java.util.ArrayList<>(List.of("a", "b"));
        SubscribeOptions opts = SubscribeOptions.builder().types(mutable).build();
        mutable.add("c");
        assertEquals(List.of("a", "b"), opts.types(),
            "caller's later mutation must not affect the SubscribeOptions");
        // Returned list is itself immutable.
        assertThrows(UnsupportedOperationException.class,
            () -> opts.types().add("d"));
    }

    // -----------------------------------------------------------------
    // Argument validation (no FFI involvement)
    // -----------------------------------------------------------------

    @Test
    void subscribeEvents_rejectsNullJobId() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.subscribeEvents(null, SubscribeOptions.defaults()));
        assertTrue(e.getMessage().toLowerCase().contains("jobid"),
            "error should mention jobId; got: " + e.getMessage());
    }

    @Test
    void subscribeEvents_rejectsEmptyJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.subscribeEvents("", SubscribeOptions.defaults()));
    }

    @Test
    void subscribeEvents_nullOptionsCoercesToDefaults() {
        // Null options must NOT NPE — it should be coerced to
        // SubscribeOptions.defaults(). This requires MCP_MESH_REGISTRY_URL
        // to be unset/empty (so we never construct a real JobProxy),
        // OR to be set (proxy construction is harmless without an HTTP
        // call). We assert no NPE bubbles out from the arg-coercion step.
        String existing = System.getenv("MCP_MESH_REGISTRY_URL");
        if (existing == null || existing.isEmpty()) {
            // Will fail at resolveRegistryUrl with MeshException — that's
            // the expected path; the test passes if we get there without
            // an NPE from the null options handling.
            MeshException e = assertThrows(MeshException.class,
                () -> MeshJobs.subscribeEvents("j-1", null));
            assertTrue(e.getMessage().contains("MCP_MESH_REGISTRY_URL"));
        } else {
            // Registry env IS set — construction is harmless (no HTTP).
            // We still expect not-an-NPE.
            try (EventSubscription sub = MeshJobs.subscribeEvents("j-1", null)) {
                assertNotNull(sub);
            }
        }
    }

    // -----------------------------------------------------------------
    // Closeable contract — exercises the close() / hasNext() interaction
    // without touching the FFI surface. We construct an EventSubscription
    // via the package-private ctor with a real (but unused) JobProxy and
    // pre-populate its buffer through reflection — only the close() →
    // hasNext()=false transition is asserted here.
    // -----------------------------------------------------------------

    @Test
    @SuppressWarnings("unchecked")
    void close_makesHasNextReturnFalseAfterBufferDrained() throws Exception {
        EventSubscription sub = constructStubSubscription();
        Deque<Map<String, Object>> buffer = bufferField(sub);
        Map<String, Object> e1 = makeEvent(1L, "progress");
        Map<String, Object> e2 = makeEvent(2L, "result");
        buffer.addLast(e1);
        buffer.addLast(e2);

        assertTrue(sub.hasNext());
        assertEquals(e1, sub.next());
        assertTrue(sub.hasNext());
        assertEquals(e2, sub.next());

        // Buffer drained; close() must short-circuit the next
        // long-poll path so hasNext() returns false rather than
        // attempting an FFI call against the stub proxy.
        sub.close();
        assertFalse(sub.hasNext(),
            "hasNext() after close() must return false without issuing a long-poll");
        assertTrue(sub.isClosedForTest());
    }

    @Test
    void close_isIdempotent() throws Exception {
        EventSubscription sub = constructStubSubscription();
        sub.close();
        sub.close(); // must not throw
        assertTrue(sub.isClosedForTest());
    }

    @Test
    void next_afterCloseThrowsNoSuchElement() throws Exception {
        EventSubscription sub = constructStubSubscription();
        sub.close();
        assertThrows(NoSuchElementException.class, sub::next);
    }

    @Test
    void next_drainsBufferEvenAfterClose() throws Exception {
        // Closing the subscription does NOT discard already-buffered
        // events — the caller can still drain the buffer; only NEW
        // long-polls are suppressed.
        EventSubscription sub = constructStubSubscription();
        Deque<Map<String, Object>> buffer = bufferField(sub);
        Map<String, Object> e1 = makeEvent(1L, "x");
        buffer.addLast(e1);
        sub.close();
        // Buffered event is still returnable.
        assertTrue(sub.hasNext(),
            "buffered events must remain visible to next() after close()");
        assertEquals(e1, sub.next());
        // Now the buffer is empty AND closed.
        assertFalse(sub.hasNext());
    }

    // -----------------------------------------------------------------
    // LRU cache reuse — MeshJobs.subscribeEvents shares the existing
    // proxyCache with postEvent (no second cache).
    // -----------------------------------------------------------------

    @Test
    void subscribeEvents_reusesLruProxyCache() {
        // Construct two subscriptions for the same jobId; both must
        // be backed by the SAME underlying JobProxy (cache hit on the
        // second call). We reach the cache via getOrCreateProxy
        // directly so we don't need MCP_MESH_REGISTRY_URL to be set —
        // that env path is exercised by the integration test.
        JobProxy a = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-shared");
        JobProxy b = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-shared");
        assertSame(a, b,
            "subscribeEvents must share the existing LRU cache with postEvent");
        assertEquals(1, MeshJobs.cacheSizeForTest(),
            "cache must hold a single entry for the shared (registry, job) key");
    }

    // -----------------------------------------------------------------
    // Builder validation
    // -----------------------------------------------------------------

    @Test
    void subscribeOptions_builderRejectsNegativeAfter() {
        // The registry can't translate a negative cursor into a valid
        // `seq > after` query — fail fast at the builder rather than
        // surface a confusing MeshException at long-poll time. Mirror
        // of the Python `after: int >= 0` constraint.
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> SubscribeOptions.builder().after(-1L));
        assertTrue(e.getMessage().toLowerCase().contains("non-negative"),
            "error message must say non-negative; got: " + e.getMessage());
        assertTrue(e.getMessage().contains("-1"),
            "error message should include the offending value; got: " + e.getMessage());
    }

    @Test
    void subscribeOptions_builderAcceptsZeroAfter() {
        // Boundary: 0 (the default) MUST be accepted; only strictly
        // negative values are rejected.
        SubscribeOptions opts = SubscribeOptions.builder().after(0L).build();
        assertEquals(0L, opts.after());
    }

    @Test
    void subscribeOptions_builderRejectsNullLongPoll() {
        // Null is a programming error — fail fast at the builder
        // rather than NPE deep inside the FFI bridge.
        assertThrows(NullPointerException.class,
            () -> SubscribeOptions.builder().longPoll(null).build());
    }

    @Test
    void subscribeOptions_builderRejectsNegativeLongPoll() {
        // Negative durations have no meaningful semantics here — the
        // registry takes a non-negative timeout. Mirrors the
        // {@code after} >= 0 constraint.
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> SubscribeOptions.builder().longPoll(Duration.ofSeconds(-1)).build());
        assertTrue(e.getMessage().toLowerCase().contains("non-negative"),
            "error message must say non-negative; got: " + e.getMessage());
    }

    @Test
    void subscribeOptions_builderAcceptsZeroLongPoll() {
        // Boundary: Duration.ZERO MUST be accepted — it bridges to a
        // single immediate read per the JavaDoc. Pins the documented
        // contract so a future maintainer doesn't tighten validation.
        SubscribeOptions opts = SubscribeOptions.builder()
            .longPoll(Duration.ZERO)
            .build();
        assertEquals(Duration.ZERO, opts.longPoll());
    }

    // -----------------------------------------------------------------
    // Envelope validation — fractional seq / next_after must be
    // rejected, not silently truncated via longValue(). This mirrors
    // Python's `type(seq) is int` strictness. The private helper
    // requireIntegralLong centralises the check; we exercise it via
    // reflection here because the public path (JobProxy.listEvents →
    // EventSubscription.hasNext) requires a live registry response.
    // -----------------------------------------------------------------

    @Test
    void subscribeEvents_rejectsFractionalSeq() throws Exception {
        // Jackson maps JSON 1.5 to Double; the helper must reject it
        // with a MeshException mentioning the field name.
        MeshException e = invokeRequireIntegralLongExpectingThrow(
            Double.valueOf(1.5), "seq", Map.of("seq", 1.5));
        assertTrue(e.getMessage().toLowerCase().contains("fractional"),
            "error must mention fractional; got: " + e.getMessage());
        assertTrue(e.getMessage().contains("seq"),
            "error must mention the field name; got: " + e.getMessage());
    }

    @Test
    void subscribeEvents_rejectsFractionalNextAfter() throws Exception {
        // Same check applied to the watermark field — a fractional
        // next_after also corrupts the cursor advance and must throw.
        MeshException e = invokeRequireIntegralLongExpectingThrow(
            Double.valueOf(1.5), "next_after", Double.valueOf(1.5));
        assertTrue(e.getMessage().toLowerCase().contains("fractional"),
            "error must mention fractional; got: " + e.getMessage());
        assertTrue(e.getMessage().contains("next_after"),
            "error must mention the field name; got: " + e.getMessage());
    }

    /**
     * Invoke the private static {@code requireIntegralLong} helper
     * via reflection and unwrap the InvocationTargetException, asserting
     * the underlying cause is a {@link MeshException}.
     */
    private static MeshException invokeRequireIntegralLongExpectingThrow(
            Number n, String fieldName, Object context) throws Exception {
        Method helper = EventSubscription.class.getDeclaredMethod(
            "requireIntegralLong", Number.class, String.class, Object.class);
        helper.setAccessible(true);
        try {
            helper.invoke(null, n, fieldName, context);
        } catch (java.lang.reflect.InvocationTargetException ite) {
            Throwable cause = ite.getCause();
            if (cause instanceof MeshException me) {
                return me;
            }
            throw new AssertionError("expected MeshException, got " + cause, cause);
        }
        throw new AssertionError("expected MeshException, but no exception was thrown");
    }

    // -----------------------------------------------------------------
    // JobProxy lock concurrency — assert read-locked methods can be
    // entered in parallel. We cannot easily mock the FFI from a unit
    // test, so we exercise the lock class semantics directly: verify
    // that ReentrantReadWriteLock allows two simultaneous read holders
    // (which is the property JobProxy.listEvents relies on), and that
    // JobProxy uses a non-fair ReentrantReadWriteLock in the expected
    // field. Together these pin the behavioural contract without
    // booting a live registry.
    // -----------------------------------------------------------------

    @Test
    void jobProxy_useReentrantReadWriteLock() throws Exception {
        // Structural assertion: JobProxy.lock must be a
        // ReentrantReadWriteLock so concurrent subscribers on the same
        // cached proxy can long-poll listEvents in parallel. The
        // previous `synchronized (Object lock)` design serialised ALL
        // operations on a single JobProxy instance.
        Field f = JobProxy.class.getDeclaredField("lock");
        f.setAccessible(true);
        JobProxy proxy = JobProxy.open("j-lock", FAKE_REGISTRY);
        try {
            Object actual = f.get(proxy);
            assertTrue(actual instanceof ReentrantReadWriteLock,
                "JobProxy.lock must be a ReentrantReadWriteLock; got: "
                    + (actual == null ? "null" : actual.getClass().getName()));
        } finally {
            proxy.close();
        }
    }

    @Test
    void jobProxy_readLockAllowsConcurrentHolders() throws Exception {
        // Behavioural assertion on the lock class — two threads can
        // hold the read lock at the same time. This is the property
        // listEvents relies on to permit concurrent long-polls.
        // We reach into JobProxy.lock to make the assertion concrete:
        // grab a read lock on it from two threads and assert
        // getReadLockCount() reflects both holders.
        Field f = JobProxy.class.getDeclaredField("lock");
        f.setAccessible(true);
        JobProxy proxy = JobProxy.open("j-lock-conc", FAKE_REGISTRY);
        try {
            ReentrantReadWriteLock rwLock = (ReentrantReadWriteLock) f.get(proxy);
            java.util.concurrent.CountDownLatch bothHoldRead = new java.util.concurrent.CountDownLatch(2);
            java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
            Runnable holder = () -> {
                rwLock.readLock().lock();
                try {
                    bothHoldRead.countDown();
                    release.await();
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                } finally {
                    rwLock.readLock().unlock();
                }
            };
            Thread t1 = new Thread(holder, "rwlock-reader-1");
            Thread t2 = new Thread(holder, "rwlock-reader-2");
            t1.setDaemon(true);
            t2.setDaemon(true);
            t1.start();
            t2.start();
            // Both readers MUST reach the read-locked region without
            // blocking on each other. A 2s budget is generous —
            // ReentrantReadWriteLock entry is microseconds.
            assertTrue(bothHoldRead.await(2, java.util.concurrent.TimeUnit.SECONDS),
                "two threads should be able to hold JobProxy.lock.readLock concurrently");
            assertEquals(2, rwLock.getReadLockCount(),
                "ReentrantReadWriteLock should report both readers as active");
            release.countDown();
            t1.join(2000);
            t2.join(2000);
        } finally {
            proxy.close();
        }
    }

    // -----------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------

    /**
     * Construct an {@link EventSubscription} bound to a real
     * {@link JobProxy} (constructed against a fake registry URL — no
     * HTTP happens until listEvents is called). We never advance the
     * iterator past the buffered events; the FFI long-poll path is
     * exercised by the integration test.
     */
    private static EventSubscription constructStubSubscription() throws Exception {
        JobProxy proxy = JobProxy.open("j-stub", FAKE_REGISTRY);
        Constructor<EventSubscription> ctor = EventSubscription.class
            .getDeclaredConstructor(JobProxy.class, SubscribeOptions.class);
        ctor.setAccessible(true);
        return ctor.newInstance(proxy, SubscribeOptions.defaults());
    }

    @SuppressWarnings("unchecked")
    private static Deque<Map<String, Object>> bufferField(EventSubscription sub) throws Exception {
        Field f = EventSubscription.class.getDeclaredField("buffer");
        f.setAccessible(true);
        return (Deque<Map<String, Object>>) f.get(sub);
    }

    private static Map<String, Object> makeEvent(long seq, String type) {
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("job_id", "j-stub");
        ev.put("seq", seq);
        ev.put("type", type);
        ev.put("payload", Map.of());
        ev.put("trace_context", null);
        ev.put("posted_by", null);
        ev.put("created_at", 0);
        return ev;
    }
}
