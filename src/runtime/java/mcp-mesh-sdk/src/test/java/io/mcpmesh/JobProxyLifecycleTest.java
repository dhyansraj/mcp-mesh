package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import jnr.ffi.Pointer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.lang.ref.WeakReference;
import java.lang.reflect.Proxy;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Native-handle lifecycle of {@link JobProxy} (issue #1592).
 *
 * <p>{@link MeshJobs} eviction no longer closes the proxies it drops, because a
 * live {@link EventSubscription} may still hold one. Something still has to
 * free the native handle: an explicit {@link JobProxy#close()} frees it at
 * once, and a proxy nobody closes is freed when it becomes unreachable — the
 * way Python's and TypeScript's bindings release theirs.
 */
class JobProxyLifecycleTest {

    /** Fake core counting {@code mesh_job_proxy_free} calls. */
    private static MeshCore fakeCore(AtomicInteger frees) {
        return (MeshCore) Proxy.newProxyInstance(
            MeshCore.class.getClassLoader(), new Class<?>[]{MeshCore.class},
            (proxy, method, args) -> {
                if ("mesh_job_proxy_free".equals(method.getName())) {
                    frees.incrementAndGet();
                    return null;
                }
                Class<?> rt = method.getReturnType();
                if (rt == int.class) return 0;
                if (rt == long.class) return 0L;
                if (rt == boolean.class) return false;
                return null;
            });
    }

    private static Pointer dummyHandle() {
        return Pointer.wrap(jnr.ffi.Runtime.getSystemRuntime(), 0x1L);
    }

    @Test
    void closeFreesTheHandleExactlyOnce() {
        AtomicInteger frees = new AtomicInteger();
        JobProxy proxy = new JobProxy(fakeCore(frees), dummyHandle(), "job-1");

        proxy.close();
        proxy.close();

        assertEquals(1, frees.get(), "close() is idempotent and frees once");
        assertTrue(proxy.toString().contains("closed=true"));
    }

    @Test
    @Timeout(30)
    void anUnreferencedProxyIsFreedWithoutClose() throws Exception {
        AtomicInteger frees = new AtomicInteger();
        MeshCore core = fakeCore(frees);
        WeakReference<JobProxy> ref = createAndDrop(core);

        // GC timing is not ours to control: apply bounded pressure, and SKIP
        // (never fail) if this JVM does not collect the proxy. A collection
        // that does happen must then free the handle.
        for (int i = 0; i < 50 && ref.get() != null; i++) {
            byte[][] pressure = new byte[16][];
            for (int j = 0; j < pressure.length; j++) {
                pressure[j] = new byte[256 * 1024];
            }
            System.gc();
            Thread.sleep(10);
        }
        assumeTrue(ref.get() == null, "JVM did not collect the proxy under bounded pressure; skipping");

        // Collected: the Cleaner thread runs the release shortly after.
        long deadline = System.nanoTime() + 10_000_000_000L;
        while (frees.get() == 0 && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        assertEquals(1, frees.get(),
            "a proxy dropped by every holder (e.g. evicted from the MeshJobs cache) "
                + "must not leak its native handle");
    }

    @Test
    void anExplicitlyClosedProxyIsNeverFreedAgainByTheCleaner() throws Exception {
        AtomicInteger frees = new AtomicInteger();
        MeshCore core = fakeCore(frees);
        WeakReference<JobProxy> ref = closeAndDrop(core);
        assertEquals(1, frees.get(), "close() freed the handle");

        // Whether or not the JVM collects it here, the count cannot rise:
        // close() unregistered the cleanup.
        for (int i = 0; i < 20 && ref.get() != null; i++) {
            System.gc();
            Thread.sleep(10);
        }
        Thread.sleep(50);
        assertEquals(1, frees.get(), "close() unregisters the cleanup — no double free");
    }

    private static WeakReference<JobProxy> createAndDrop(MeshCore core) {
        return new WeakReference<>(new JobProxy(core, dummyHandle(), "job-dropped"));
    }

    private static WeakReference<JobProxy> closeAndDrop(MeshCore core) {
        JobProxy proxy = new JobProxy(core, dummyHandle(), "job-closed");
        proxy.close();
        return new WeakReference<>(proxy);
    }
}
