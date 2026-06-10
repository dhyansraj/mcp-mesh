package io.mcpmesh.core;

import jnr.ffi.Pointer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Concurrency tests for {@link MeshHandle} close/accessor races (issue #1179).
 *
 * <p>These tests use a {@link Proxy}-based fake {@link MeshCore} instead of the
 * real native library so they run deterministically on every platform and can
 * observe the exact property under test: no handle-taking native call may
 * START after {@code mesh_free_handle} has run. (Calls already in flight when
 * free happens are covered by the Rust side's reference counting — that part
 * is exercised by the Rust test suite, not here.)
 *
 * <p>Limitation: the close-wakes-parked-nextEvent test relies on the fake
 * mirroring the documented Rust semantics (mesh_shutdown → run loop exits →
 * event channel closes → parked mesh_next_event returns). The real
 * end-to-end wake-up path requires the native library plus a running agent
 * and is not exercised here.
 */
class MeshHandleTest {

    /** Native FFI entry points that dereference the agent handle. */
    private static final Set<String> HANDLE_TAKING = Set.of(
        "mesh_is_running", "mesh_next_event", "mesh_report_health",
        "mesh_update_port", "mesh_shutdown", "mesh_free_handle");

    /**
     * Fake MeshCore that mimics the Rust FFI contract relevant to #1179:
     * <ul>
     *   <li>{@code mesh_next_event} parks until woken (or its timeout elapses)</li>
     *   <li>{@code mesh_shutdown} wakes parked {@code mesh_next_event} callers
     *       (in the real core: shutdown signal → run loop emits shutdown event
     *       and exits → event channel closes → parked recv returns)</li>
     *   <li>{@code mesh_free_handle} marks the handle freed; any handle-taking
     *       call STARTED afterwards is recorded as a use-after-free</li>
     * </ul>
     */
    private static final class FakeCore implements InvocationHandler {
        final AtomicBoolean freed = new AtomicBoolean(false);
        final AtomicInteger freeCount = new AtomicInteger();
        final AtomicBoolean shutdownSignalled = new AtomicBoolean(false);
        final AtomicBoolean calledAfterFree = new AtomicBoolean(false);
        final CountDownLatch nextEventParked = new CountDownLatch(1);
        final CountDownLatch wake = new CountDownLatch(1);
        final AtomicLong nextEventReturnedAt = new AtomicLong(-1);
        final AtomicLong freedAt = new AtomicLong(-1);
        /** When false, simulates a wedged runtime that never processes shutdown. */
        volatile boolean shutdownWakesNextEvent = true;
        /** When true, mesh_free_handle blocks until {@link #freeRelease} —
         *  simulates the real free taking seconds (Rust shutdown + span drain). */
        volatile boolean blockFree = false;
        final CountDownLatch freeStarted = new CountDownLatch(1);
        final CountDownLatch freeRelease = new CountDownLatch(1);

        MeshCore asCore() {
            return (MeshCore) Proxy.newProxyInstance(
                MeshCore.class.getClassLoader(), new Class<?>[]{MeshCore.class}, this);
        }

        @Override
        public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
            String name = method.getName();
            // The property under test: no handle-taking call may START after free.
            if (HANDLE_TAKING.contains(name) && !"mesh_free_handle".equals(name) && freed.get()) {
                calledAfterFree.set(true);
            }
            switch (name) {
                case "mesh_is_running":
                    return 1;
                case "mesh_report_health":
                case "mesh_update_port":
                    return 0;
                case "mesh_shutdown":
                    shutdownSignalled.set(true);
                    if (shutdownWakesNextEvent) {
                        wake.countDown();
                    }
                    return null;
                case "mesh_next_event": {
                    nextEventParked.countDown();
                    long timeoutMs = (Long) args[1];
                    try {
                        if (timeoutMs < 0) {
                            wake.await();
                        } else if (timeoutMs > 0) {
                            wake.await(timeoutMs, TimeUnit.MILLISECONDS);
                        }
                    } finally {
                        nextEventReturnedAt.set(System.nanoTime());
                    }
                    return null; // timeout / shutdown — no event
                }
                case "mesh_free_handle":
                    freedAt.set(System.nanoTime());
                    freed.set(true);
                    freeStarted.countDown();
                    if (blockFree) {
                        freeRelease.await();
                    }
                    freeCount.incrementAndGet();
                    return null;
                case "mesh_last_error":
                case "mesh_free_string":
                    return null;
                default:
                    Class<?> rt = method.getReturnType();
                    if (rt == int.class) return 0;
                    if (rt == long.class) return 0L;
                    if (rt == double.class) return 0.0d;
                    return null;
            }
        }
    }

    private static MeshHandle newHandle(FakeCore fake) {
        Pointer dummy = Pointer.wrap(jnr.ffi.Runtime.getSystemRuntime(), 0x1L);
        return new MeshHandle(fake.asCore(), dummy);
    }

    @Test
    @Timeout(60)
    void concurrentAccessorsRacingCloseNeverCallNativeAfterFree() throws Exception {
        // Hammer accessors from several threads while close() runs concurrently.
        // The original check-then-act gap means an accessor could pass the
        // closed-check, get preempted across the whole of close(), then enter
        // native code with a freed pointer. Repeat to give the race a chance.
        final int iterations = 200;
        final int accessorThreads = 4;

        for (int i = 0; i < iterations; i++) {
            FakeCore fake = new FakeCore();
            MeshHandle handle = newHandle(fake);

            CountDownLatch start = new CountDownLatch(1);
            CountDownLatch done = new CountDownLatch(accessorThreads);
            for (int t = 0; t < accessorThreads; t++) {
                final int id = t;
                Thread thread = new Thread(() -> {
                    try {
                        start.await();
                        for (int k = 0; k < 50; k++) {
                            try {
                                switch ((id + k) % 4) {
                                    case 0 -> handle.isRunning();
                                    case 1 -> handle.reportHealthy();
                                    case 2 -> handle.updatePort(8080);
                                    default -> handle.nextEvent(0);
                                }
                            } catch (MeshException expectedAfterClose) {
                                // reportHealth/updatePort throw once closed — expected.
                            }
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    } finally {
                        done.countDown();
                    }
                });
                thread.setDaemon(true);
                thread.start();
            }

            start.countDown();
            handle.close();
            assertTrue(done.await(30, TimeUnit.SECONDS), "accessor threads did not finish");

            assertFalse(fake.calledAfterFree.get(),
                "a handle-taking native call started after mesh_free_handle (iteration " + i + ")");
            assertEquals(1, fake.freeCount.get(), "handle must be freed exactly once");
        }
    }

    @Test
    @Timeout(30)
    void postCloseCallsAreRejectedWithoutTouchingNative() {
        FakeCore fake = new FakeCore();
        MeshHandle handle = newHandle(fake);

        handle.close();
        assertEquals(1, fake.freeCount.get());

        assertFalse(handle.isRunning());
        assertTrue(handle.nextEvent(0).isEmpty());
        assertThrows(MeshException.class, () -> handle.reportHealth("healthy"));
        assertThrows(MeshException.class, () -> handle.updatePort(8080));
        handle.shutdown(); // no-op after close
        handle.close();    // idempotent

        assertEquals(1, fake.freeCount.get(), "second close must not free again");
        assertFalse(fake.calledAfterFree.get(), "post-close calls must not reach native code");
    }

    @Test
    @Timeout(30)
    void closeWakesParkedNextEventAndFreesOnlyAfterItReturns() throws Exception {
        FakeCore fake = new FakeCore();
        MeshHandle handle = newHandle(fake);

        Thread parked = new Thread(() -> handle.nextEvent(-1)); // infinite timeout
        parked.setDaemon(true);
        parked.start();
        assertTrue(fake.nextEventParked.await(5, TimeUnit.SECONDS), "nextEvent did not park");

        long closeStart = System.nanoTime();
        handle.close();
        long closeMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - closeStart);

        parked.join(TimeUnit.SECONDS.toMillis(5));
        assertFalse(parked.isAlive(), "parked nextEvent caller did not return");

        // close() must signal shutdown FIRST (waking the parked caller), then
        // drain, then free — well inside the 5s drain budget, not the full
        // (here: infinite) nextEvent timeout.
        assertTrue(fake.shutdownSignalled.get(), "close must signal mesh_shutdown before freeing");
        assertTrue(closeMs < 4000, "close should return promptly once woken, took " + closeMs + "ms");
        assertTrue(fake.freedAt.get() >= fake.nextEventReturnedAt.get(),
            "mesh_free_handle ran before the parked mesh_next_event returned");
        assertFalse(fake.calledAfterFree.get());
    }

    @Test
    @Timeout(30)
    void closeProceedsAfterBoundedWaitWhenNextEventIsStuck() throws Exception {
        // Wedged-runtime simulation: shutdown never wakes the parked caller.
        // close() must NOT hang on it — it warns and frees after the bounded
        // drain wait (safe: the Rust side reference-counts in-flight calls).
        FakeCore fake = new FakeCore();
        fake.shutdownWakesNextEvent = false;
        MeshHandle handle = newHandle(fake);

        Thread parked = new Thread(() -> handle.nextEvent(-1));
        parked.setDaemon(true);
        parked.start();
        assertTrue(fake.nextEventParked.await(5, TimeUnit.SECONDS), "nextEvent did not park");

        long closeStart = System.nanoTime();
        handle.close();
        long closeMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - closeStart);

        assertEquals(1, fake.freeCount.get(), "close must free despite the stuck call");
        assertTrue(closeMs >= 4500, "close should wait the full drain budget, took " + closeMs + "ms");
        assertTrue(closeMs < 15000, "close must be bounded, took " + closeMs + "ms");

        // Release the stuck caller and verify it exits cleanly.
        fake.wake.countDown();
        parked.join(TimeUnit.SECONDS.toMillis(5));
        assertFalse(parked.isAlive(), "stuck nextEvent caller did not exit after wake");
    }

    @Test
    @Timeout(30)
    void postCloseAccessorsReturnFastWhileFreeIsStillInProgress() throws Exception {
        // close() releases the write lock BEFORE mesh_free_handle, and the
        // accessors have a lock-free closed fast path — so a slow native free
        // (real Rust free can block ~4s on shutdown wait + span drain) must
        // not stall post-close accessors. The fake blocks free on a latch to
        // pin the closer inside mesh_free_handle while we probe.
        FakeCore fake = new FakeCore();
        fake.blockFree = true;
        MeshHandle handle = newHandle(fake);

        Thread closer = new Thread(handle::close);
        closer.setDaemon(true);
        closer.start();
        assertTrue(fake.freeStarted.await(5, TimeUnit.SECONDS), "close did not reach free");
        assertTrue(closer.isAlive(), "closer must still be inside mesh_free_handle");

        long start = System.nanoTime();
        assertFalse(handle.isRunning());
        assertTrue(handle.nextEvent(0).isEmpty());
        assertThrows(MeshException.class, () -> handle.reportHealth("healthy"));
        assertThrows(MeshException.class, () -> handle.updatePort(8080));
        long elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);

        assertTrue(closer.isAlive(), "free must still be in progress while accessors ran");
        assertTrue(elapsedMs < 1000,
            "post-close accessors blocked behind the in-progress free, took " + elapsedMs + "ms");

        fake.freeRelease.countDown();
        closer.join(TimeUnit.SECONDS.toMillis(5));
        assertFalse(closer.isAlive(), "closer did not finish after free was released");
        assertEquals(1, fake.freeCount.get());
        assertFalse(fake.calledAfterFree.get(), "post-close accessors must not reach native code");
    }

    @Test
    @Timeout(30)
    void interruptDuringDrainLogsInterruptVariantAndRestoresFlag() throws Exception {
        // A parked nextEvent holds the read lock (wedged runtime: shutdown
        // never wakes it), so close()'s drain tryLock blocks. Interrupting the
        // closing thread must: log the interrupt-specific message (NOT the
        // "did not drain within Nms" timeout message — the wait lasted ~0ms,
        // not the full budget), restore the interrupt flag, and still free.
        FakeCore fake = new FakeCore();
        fake.shutdownWakesNextEvent = false;
        MeshHandle handle = newHandle(fake);

        Thread parked = new Thread(() -> handle.nextEvent(-1));
        parked.setDaemon(true);
        parked.start();
        assertTrue(fake.nextEventParked.await(5, TimeUnit.SECONDS), "nextEvent did not park");

        // slf4j-simple writes to System.err dynamically; capture it.
        java.io.PrintStream originalErr = System.err;
        java.io.ByteArrayOutputStream errBuf = new java.io.ByteArrayOutputStream();
        String errOutput;
        AtomicBoolean interruptFlagRestored = new AtomicBoolean(false);
        long closeMs;
        try {
            System.setErr(new java.io.PrintStream(errBuf, true));

            Thread closer = new Thread(() -> {
                handle.close();
                interruptFlagRestored.set(Thread.currentThread().isInterrupted());
            });
            closer.setDaemon(true);
            long closeStart = System.nanoTime();
            closer.start();

            // Wait until the closer is parked in the drain tryLock, then interrupt.
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (closer.getState() != Thread.State.TIMED_WAITING) {
                assertTrue(System.nanoTime() < deadline, "closer never reached the drain wait");
                Thread.onSpinWait();
            }
            closer.interrupt();

            closer.join(TimeUnit.SECONDS.toMillis(10));
            closeMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - closeStart);
            assertFalse(closer.isAlive(), "close did not return after interrupt");
        } finally {
            System.setErr(originalErr);
            errOutput = errBuf.toString();
        }

        assertTrue(closeMs < 4000,
            "interrupted close should return well before the 5s drain budget, took " + closeMs + "ms");
        assertEquals(1, fake.freeCount.get(), "close must still free after interrupt");
        assertTrue(interruptFlagRestored.get(), "close must restore the interrupt flag");
        assertTrue(errOutput.contains("Interrupted while waiting for in-flight native calls"),
            "expected the interrupt-specific log message, got:\n" + errOutput);
        assertFalse(errOutput.contains("did not drain within"),
            "interrupted drain must not be mislabelled as a timeout, got:\n" + errOutput);

        // Release the stuck caller and verify it exits cleanly.
        fake.wake.countDown();
        parked.join(TimeUnit.SECONDS.toMillis(5));
        assertFalse(parked.isAlive());
    }

    @Test
    @Timeout(30)
    void closedFlagIsCheckedUnderTheSameLockAsTheNativeCall() throws Exception {
        // Regression shape of the original TOCTOU: a reader that acquires the
        // read lock after close() has the write lock must observe closed=true
        // and bail without a native call. Drive it deterministically: park one
        // reader in nextEvent, start close() (which will signal shutdown, wake
        // the reader, then take the write lock and free), then issue a fresh
        // accessor call that races the free.
        FakeCore fake = new FakeCore();
        MeshHandle handle = newHandle(fake);

        Thread parked = new Thread(() -> handle.nextEvent(-1));
        parked.setDaemon(true);
        parked.start();
        assertTrue(fake.nextEventParked.await(5, TimeUnit.SECONDS));

        List<Thread> racers = List.of(
            new Thread(handle::close),
            new Thread(() -> {
                for (int i = 0; i < 1000; i++) {
                    handle.isRunning();
                }
            })
        );
        racers.forEach(t -> { t.setDaemon(true); t.start(); });
        for (Thread t : racers) {
            t.join(TimeUnit.SECONDS.toMillis(15));
            assertFalse(t.isAlive());
        }
        parked.join(TimeUnit.SECONDS.toMillis(5));

        assertFalse(fake.calledAfterFree.get(), "isRunning reached native code after free");
    }
}
