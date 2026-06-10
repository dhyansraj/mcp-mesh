package io.mcpmesh.core;

import tools.jackson.databind.ObjectMapper;
import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.Closeable;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * Handle to a running MCP Mesh agent.
 *
 * <p>This class wraps the native agent handle and provides a Java-friendly API
 * for interacting with the Rust core runtime.
 *
 * <p>Implements {@link Closeable} for use with try-with-resources.
 *
 * <h2>Usage Example</h2>
 * <pre>{@code
 * AgentSpec spec = new AgentSpec("my-agent", "http://localhost:8000");
 * try (MeshHandle handle = MeshHandle.start(spec)) {
 *     while (handle.isRunning()) {
 *         Optional<MeshEvent> event = handle.nextEvent(5000);
 *         event.ifPresent(this::handleEvent);
 *     }
 * }
 * }</pre>
 */
public class MeshHandle implements Closeable {

    private static final Logger log = LoggerFactory.getLogger(MeshHandle.class);
    private static final ObjectMapper objectMapper = MeshObjectMappers.create();

    /** Bounded wait in {@link #close()} for in-flight native calls to drain. */
    private static final long CLOSE_DRAIN_TIMEOUT_MS = 5_000;

    private final MeshCore core;
    private final Pointer handle;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    /**
     * Guards the closed-check + native call as one atomic unit (issue #1179).
     *
     * <p>Accessors take the read lock around {@code closed.get()} and the
     * native call, so once {@link #close()} holds the write lock no accessor
     * can be between the check and the call — closing the check-then-act gap
     * where a thread passes the {@code closed} check, is preempted for the
     * entire duration of {@code close()}, and then enters native code with a
     * freed pointer. (Calls already inside native code when free happens are
     * separately safe: the Rust side reference-counts the handle.)
     */
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();

    // Package-private for tests (MeshHandleTest injects a fake MeshCore).
    MeshHandle(MeshCore core, Pointer handle) {
        this.core = core;
        this.handle = handle;
    }

    /**
     * Start an agent from the given specification.
     *
     * @param spec The agent specification
     * @return A handle to the running agent
     * @throws MeshException if the agent fails to start
     */
    public static MeshHandle start(AgentSpec spec) {
        MeshCore core = MeshCore.load();

        try {
            String specJson = objectMapper.writeValueAsString(spec);
            log.debug("Starting agent with spec: {}", specJson);

            Pointer handle = core.mesh_start_agent(specJson);
            if (handle == null) {
                String error = getLastError(core);
                throw new MeshException("Failed to start agent: " + error);
            }

            log.info("Agent '{}' started successfully", spec.getName());
            return new MeshHandle(core, handle);
        } catch (Exception e) {
            throw new MeshException("Failed to serialize AgentSpec", e);
        }
    }

    /**
     * Check if the agent is still running.
     *
     * @return true if running, false if shutdown
     */
    public boolean isRunning() {
        // Lock-free fast path: post-close calls return immediately instead of
        // queuing behind close()'s write lock. The check under the read lock
        // below is the authoritative one for the close/accessor race.
        if (closed.get()) {
            return false;
        }
        lock.readLock().lock();
        try {
            if (closed.get()) {
                return false;
            }
            return core.mesh_is_running(handle) == 1;
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Get the next event from the agent runtime.
     *
     * <p>Blocks until an event is available or the timeout expires.
     *
     * @param timeoutMs Timeout in milliseconds (-1 for infinite, 0 for non-blocking)
     * @return The event, or empty if timeout/shutdown
     */
    public Optional<MeshEvent> nextEvent(long timeoutMs) {
        // Lock-free fast path: post-close calls return immediately instead of
        // queuing behind close()'s write lock. The check under the read lock
        // below is the authoritative one for the close/accessor race.
        if (closed.get()) {
            return Optional.empty();
        }
        // Holding the read lock for the full (potentially long) native wait
        // is intentional: close() wakes a parked caller via mesh_shutdown
        // BEFORE waiting for the lock, and its wait is bounded regardless.
        lock.readLock().lock();
        try {
            if (closed.get()) {
                return Optional.empty();
            }

            Pointer eventPtr = core.mesh_next_event(handle, timeoutMs);
            if (eventPtr == null) {
                return Optional.empty();
            }

            try {
                String eventJson = eventPtr.getString(0);
                log.debug("Received event: {}", eventJson);
                MeshEvent event = objectMapper.readValue(eventJson, MeshEvent.class);
                return Optional.of(event);
            } catch (Exception e) {
                log.error("Failed to parse event JSON", e);
                return Optional.empty();
            } finally {
                core.mesh_free_string(eventPtr);
            }
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Report the agent's health status.
     *
     * @param status The health status ("healthy", "degraded", or "unhealthy")
     * @throws MeshException if the status report fails
     */
    public void reportHealth(String status) {
        // Lock-free fast path: post-close calls fail immediately instead of
        // queuing behind close()'s write lock. The check under the read lock
        // below is the authoritative one for the close/accessor race.
        if (closed.get()) {
            throw new MeshException("Handle is closed");
        }
        lock.readLock().lock();
        try {
            if (closed.get()) {
                throw new MeshException("Handle is closed");
            }

            int result = core.mesh_report_health(handle, status);
            if (result != 0) {
                String error = getLastError(core);
                throw new MeshException("Failed to report health: " + error);
            }
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Report the agent as healthy.
     */
    public void reportHealthy() {
        reportHealth("healthy");
    }

    /**
     * Report the agent as degraded.
     */
    public void reportDegraded() {
        reportHealth("degraded");
    }

    /**
     * Report the agent as unhealthy.
     */
    public void reportUnhealthy() {
        reportHealth("unhealthy");
    }

    /**
     * Update the HTTP port after auto-detection.
     *
     * <p>Call this after the HTTP server starts with port=0 to update
     * the registry with the actual assigned port. This triggers a full
     * heartbeat to re-register with the correct endpoint.
     *
     * @param port The actual port the HTTP server is listening on
     * @return true if the update was sent successfully
     */
    public boolean updatePort(int port) {
        // Lock-free fast path: post-close calls fail immediately instead of
        // queuing behind close()'s write lock. The check under the read lock
        // below is the authoritative one for the close/accessor race.
        if (closed.get()) {
            throw new MeshException("Handle is closed");
        }
        lock.readLock().lock();
        try {
            if (closed.get()) {
                throw new MeshException("Handle is closed");
            }

            int result = core.mesh_update_port(handle, port);
            if (result != 0) {
                String error = getLastError(core);
                log.warn("Failed to update port to {}: {}", port, error);
                return false;
            }
            log.info("Port updated to {}", port);
            return true;
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Request graceful shutdown of the agent.
     *
     * <p>This is non-blocking. Use {@link #nextEvent(long)} to wait for the
     * shutdown event.
     */
    public void shutdown() {
        lock.readLock().lock();
        try {
            if (!closed.get()) {
                log.info("Requesting agent shutdown");
                core.mesh_shutdown(handle);
            }
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Close the handle and free associated resources.
     *
     * <p>If the agent is still running, this will trigger graceful shutdown
     * and wait briefly for cleanup. Waits (bounded) for in-flight native
     * calls on other threads to drain before freeing the native handle.
     *
     * <p>Concurrent close: only one caller performs the shutdown/drain/free
     * sequence; a losing concurrent caller returns immediately while the
     * winner may still be draining or freeing. Callers therefore must NOT
     * treat a returned {@code close()} as "native handle freed".
     */
    @Override
    public void close() {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        log.info("Closing agent handle");

        // Ordering matters here (issue #1179):
        //
        // 1. `closed` is flipped first (CAS above), so any accessor that has
        //    not yet passed its closed-check under the read lock bails out
        //    before reaching native code.
        //
        // 2. mesh_shutdown is called BEFORE waiting for in-flight calls to
        //    drain. A nextEvent caller can be parked inside native code for
        //    its full timeout (potentially infinite). mesh_shutdown signals
        //    the runtime; its run loop emits the shutdown event and exits,
        //    closing the event channel — which wakes a parked nextEvent
        //    promptly. Draining first would deadlock against such a caller:
        //    previously it was mesh_free_handle itself that triggered the
        //    wake-up, so waiting for the drain before free is chicken-and-egg
        //    unless shutdown is signalled up front. Calling mesh_shutdown
        //    without the write lock is safe: this thread is the only one that
        //    frees (CAS winner) and the free has not happened yet.
        //
        // 3. Wait (bounded) for in-flight native calls to drain by acquiring
        //    the write lock — then RELEASE it before freeing. Acquiring the
        //    write lock proves the drain is complete: `closed` is already
        //    true, so any reader that takes the read lock afterwards bails at
        //    the closed-check before reaching native code — holding the write
        //    lock across the free adds no safety. It would hurt, though:
        //    mesh_free_handle can block for seconds on the Rust side
        //    (shutdown wait + span drain), and holding the lock across it
        //    would stall every post-close accessor queued on the read lock.
        //    On timeout (e.g. a nextEvent parked on an infinite timeout with
        //    a wedged runtime) we warn and free anyway: the Rust side
        //    reference-counts the handle, so freeing under a call that
        //    already STARTED is safe — this lock only closes the gap for
        //    calls that would start after the free.
        core.mesh_shutdown(handle);

        boolean drained = false;
        boolean interrupted = false;
        try {
            drained = lock.writeLock().tryLock(CLOSE_DRAIN_TIMEOUT_MS, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            interrupted = true;
            Thread.currentThread().interrupt(); // restore the interrupt flag for the caller
        }
        if (drained) {
            lock.writeLock().unlock();
        } else if (interrupted) {
            log.warn("Interrupted while waiting for in-flight native calls to drain; freeing "
                + "handle anyway (safe for calls already in native code: the handle is "
                + "reference-counted)");
        } else {
            log.warn("In-flight native calls did not drain within {}ms; freeing handle anyway "
                + "(safe for calls already in native code: the handle is reference-counted)",
                CLOSE_DRAIN_TIMEOUT_MS);
        }
        core.mesh_free_handle(handle);
    }

    private static String getLastError(MeshCore core) {
        Pointer errorPtr = core.mesh_last_error();
        if (errorPtr == null) {
            return "Unknown error";
        }
        try {
            return errorPtr.getString(0);
        } finally {
            core.mesh_free_string(errorPtr);
        }
    }
}
