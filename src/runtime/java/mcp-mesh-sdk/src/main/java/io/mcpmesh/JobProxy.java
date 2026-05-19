package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshException;
import io.mcpmesh.core.MeshObjectMappers;
import jnr.ffi.Pointer;
import jnr.ffi.byref.PointerByReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * Consumer-side handle: returned by {@link MeshJobSubmitter#submit(Map)} (or
 * obtained directly from a known job id) and exposes
 * {@link #wait(double)} / {@link #status()} / {@link #cancel(String)} for
 * code that wants to await a remote job.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.job_proxy.PyJobProxy}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ... JobProxy}</li>
 * </ul>
 *
 * <p>Implements {@link AutoCloseable}; the underlying native handle is
 * lightweight (just a backend reference + job id) but still needs an
 * explicit {@link #close} to drop the FFI box. Idempotent.
 */
public final class JobProxy implements MeshJob, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(JobProxy.class);
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private final MeshCore core;
    /**
     * Native handle. {@code null} after {@link #close} runs. Read/written
     * only while holding the appropriate {@link #lock} mode (write for
     * mutation, read for FFI calls) — see {@link JobController} for
     * the analogous protection; without it a concurrent close could free
     * the pointer mid-FFI-call (PR #891 review).
     */
    private Pointer handle;
    private final String jobId;
    /**
     * Read-write lock so concurrent subscribers can long-poll
     * {@link #listEvents} on the same cached proxy in parallel. The
     * underlying Rust {@code JobProxy} ({@code Arc<dyn TaskBackend> +
     * String}) is {@code Sync} and {@code list_events} explicitly does
     * NOT serialise — see {@code core/src/jobs.rs} JobProxy doc — so
     * the read lock is correct here. {@link #close} takes the write
     * lock so an in-flight FFI call can never see the handle pointer
     * freed underneath it.
     */
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();
    private volatile boolean closed = false;

    JobProxy(MeshCore core, Pointer handle, String jobId) {
        this.core = core;
        this.handle = handle;
        this.jobId = jobId;
    }

    /**
     * Open a proxy bound to a known {@code jobId} + {@code registryUrl}.
     * Normally callers obtain a proxy via {@link MeshJobSubmitter#submit(Map)};
     * this constructor is for tests and the fallback "I already know the
     * job id, just give me a handle" path.
     */
    public static JobProxy open(String jobId, String registryUrl) {
        if (jobId == null || jobId.isEmpty()) {
            throw new IllegalArgumentException("jobId is required");
        }
        if (registryUrl == null || registryUrl.isEmpty()) {
            throw new IllegalArgumentException("registryUrl is required");
        }
        MeshCore core = MeshCore.load();
        PointerByReference out = new PointerByReference();
        int rc = core.mesh_job_proxy_new(jobId, registryUrl, out);
        if (rc != 0) {
            throw new MeshException("mesh_job_proxy_new failed: " + lastError(core));
        }
        Pointer handle = out.getValue();
        if (handle == null) {
            throw new MeshException("mesh_job_proxy_new returned null handle");
        }
        return new JobProxy(core, handle, jobId);
    }

    /** The job id this proxy is bound to. */
    public String jobId() {
        return jobId;
    }

    /**
     * Read the latest job state from the registry (single GET). Returns the
     * full job row deserialized as a {@code Map<String, Object>} (matches
     * the Python / TS bindings that return a dict / object).
     *
     * @throws MeshException if the registry call fails
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> status() {
        // FFI call inside the READ lock — concurrent status/await/
        // listEvents calls can proceed in parallel; only close() (write
        // lock) is mutually exclusive. The result string itself was
        // allocated by Rust and is independent of the proxy handle, so
        // we can parse it unguarded.
        Pointer p;
        lock.readLock().lock();
        try {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_status(handle, out);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_status failed: " + lastError(core));
            }
            p = out.getValue();
        } finally {
            lock.readLock().unlock();
        }
        if (p == null) {
            throw new MeshException("mesh_job_proxy_status returned null payload");
        }
        try {
            String json = p.getString(0);
            return (Map<String, Object>) MAPPER.readValue(json, Map.class);
        } catch (Exception e) {
            throw new MeshException("Failed to parse job status JSON", e);
        } finally {
            core.mesh_free_string(p);
        }
    }

    /**
     * Poll until the job reaches a terminal state. Returns the result
     * payload as a generic Java value (Map / List / Number / String /
     * Boolean / null) — Jackson default binding.
     *
     * <p>Named {@code await} (not {@code wait}) because {@link Object#wait()}
     * is {@code final} on every Java object — overloading the name on a
     * subclass is a compile error. Mirrors the Python {@code .wait()} and
     * TypeScript {@code .wait()} APIs semantically; the rename is purely a
     * Java language constraint.
     *
     * @param timeoutSecs Wall-clock timeout in seconds.
     *                    <ul>
     *                      <li>Negative or zero (including {@code -0.0})
     *                          → no timeout (block until terminal).</li>
     *                      <li>Positive finite → wait that many
     *                          seconds, then surface a timeout error.</li>
     *                      <li>Non-finite (NaN, ±Inf) → no timeout.</li>
     *                    </ul>
     *                    The {@link #await()} no-arg overload uses
     *                    {@code -1.0} to opt into the no-timeout branch.
     * @return The job result payload
     * @throws MeshException on timeout, cancellation, or non-success terminal
     *                       (the message starts with the variant name —
     *                       {@code "timeout: ..."} / {@code "cancelled: ..."}
     *                       / etc., matching the napi-rs surface).
     */
    public Object await(double timeoutSecs) {
        // The wait FFI may block for the full timeout — we hold the
        // READ lock for that whole duration so a concurrent close()
        // (write lock) doesn't free the handle while the Rust runtime
        // is still polling on it. Other read-locked operations
        // (status/listEvents/await) may proceed concurrently.
        // Closing the proxy from another thread is a programming
        // error if you also have an outstanding await(), but the lock
        // prevents the worst (use-after-free) outcome.
        Pointer p;
        lock.readLock().lock();
        try {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_wait(handle, timeoutSecs, out);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_wait failed: " + lastError(core));
            }
            p = out.getValue();
        } finally {
            lock.readLock().unlock();
        }
        if (p == null) {
            // await() succeeded but produced no payload — treat as JSON null.
            return null;
        }
        try {
            String json = p.getString(0);
            return MAPPER.readValue(json, Object.class);
        } catch (Exception e) {
            throw new MeshException("Failed to parse job wait result JSON", e);
        } finally {
            core.mesh_free_string(p);
        }
    }

    /** Convenience: {@link #await(double)} without a timeout. */
    public Object await() {
        return await(-1.0);
    }

    /**
     * Request cancellation. The registry forwards the signal to the owner
     * replica when alive. Returns once the registry has acknowledged.
     *
     * @param reason Optional cancel reason (may be null)
     * @throws MeshException if the registry call fails
     */
    public void cancel(String reason) {
        // Read-locked — cancel only forwards the signal via FFI; the
        // handle itself isn't mutated. Concurrent reads (status/await/
        // listEvents) may proceed in parallel.
        lock.readLock().lock();
        try {
            ensureOpen();
            int rc = core.mesh_job_proxy_cancel(handle, reason);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_cancel failed: " + lastError(core));
            }
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Post an event into this job's event channel (mirror of
     * {@code JobProxy::send_event} in the Rust core, issue #1032).
     * The running handler (inside a {@code task=true} job) will see
     * the event on its next {@code recvEvent} call — or wake immediately
     * if it's currently long-polling.
     *
     * <p>Mirrors:
     * <ul>
     *   <li>Python {@code proxy.send_event(event_type, payload)}</li>
     *   <li>TypeScript {@code proxy.sendEvent(eventType, payload)}</li>
     * </ul>
     *
     * @param eventType Event-type tag (required, non-null)
     * @param payload   Optional payload Map; {@code null} normalises to
     *                  an empty JSON object {@code {}} matching the
     *                  Python {@code payload=None} contract
     * @return Receipt map with {@code job_id, seq, created_at} so
     *         callers can stitch a follow-up {@code recvEvent} via
     *         {@code seq}.
     * @throws JobNotFoundException if the registry doesn't know the
     *                              job (404 from {@code POST /jobs/{id}/events})
     * @throws JobTerminalException if the job has already reached a
     *                              terminal state — no more events
     *                              accepted (409 from the registry)
     * @throws MeshException        for transport errors, serialization
     *                              failures, or other backend issues
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> sendEvent(String eventType, Map<String, Object> payload) {
        if (eventType == null || eventType.isEmpty()) {
            throw new IllegalArgumentException("eventType is required");
        }
        // Serialize OUTSIDE the lock — keep FFI critical section short.
        String payloadJson;
        if (payload == null) {
            // null → null pointer at the FFI boundary → Rust treats as
            // {} (matches Python's `payload=None` → empty-dict
            // normalisation in `mesh.jobs.post_event`).
            payloadJson = null;
        } else {
            try {
                payloadJson = MAPPER.writeValueAsString(payload);
            } catch (Exception e) {
                throw new MeshException("Failed to serialize event payload", e);
            }
        }

        Pointer p;
        lock.readLock().lock();
        try {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_send_event(handle, eventType, payloadJson, out);
            String err = rc == 0 ? null : lastError(core);
            switch (rc) {
                case 0:
                    p = out.getValue();
                    break;
                case -2:
                    throw new JobNotFoundException(
                        "mesh_job_proxy_send_event: job not found: " + err);
                case -3:
                    throw new JobTerminalException(
                        "mesh_job_proxy_send_event: job is terminal: " + err);
                case -1:
                case -4:
                default:
                    throw new MeshException(
                        "mesh_job_proxy_send_event failed (rc=" + rc + "): " + err);
            }
        } finally {
            lock.readLock().unlock();
        }
        if (p == null) {
            throw new MeshException("mesh_job_proxy_send_event returned null receipt");
        }
        try {
            String json = p.getString(0);
            return (Map<String, Object>) MAPPER.readValue(json, Map.class);
        } catch (Exception e) {
            throw new MeshException("Failed to parse send_event receipt JSON", e);
        } finally {
            core.mesh_free_string(p);
        }
    }

    /**
     * Fetch a single batch of events from this job's event log with
     * {@code seq > after}, optionally filtered by {@code types}. The
     * SDK's {@link MeshJobs#subscribeEvents(String, SubscribeOptions)}
     * blocking iterator is built on top of this primitive — callers
     * manage their own cursor between calls.
     *
     * <p>Mirrors:
     * <ul>
     *   <li>Python {@code proxy.list_events(after, types, long_poll_secs)}</li>
     *   <li>TypeScript {@code proxy.listEvents(after, types, longPollSecs)}</li>
     * </ul>
     *
     * @param after        Cursor — only events with {@code seq > after}
     *                     are returned. Pass {@code 0} for "from the
     *                     beginning of the event log".
     * @param types        Optional event-type filter (e.g.
     *                     {@code List.of("work","progress")}); {@code null}
     *                     or empty means "all types".
     * @param longPoll     Long-poll wait budget per registry call.
     *                     {@code null} or {@link Duration#ZERO} or
     *                     negative means "single immediate read".
     * @return Envelope {@code {events: List<Map>, next_after: Long}}.
     *         {@code next_after} is the registry-supplied watermark to
     *         feed back as {@code after} on the next call so empty
     *         pages caused by server-side {@code types} filtering still
     *         advance the cursor.
     * @throws JobNotFoundException if the job has been reaped from the
     *                              registry (404 from
     *                              {@code GET /jobs/{id}/events})
     * @throws MeshException        for transport errors, malformed
     *                              types filter, or other backend
     *                              issues
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> listEvents(long after, List<String> types, Duration longPoll) {
        // Serialize types filter OUTSIDE the lock — Jackson is
        // thread-safe and the list is typically short, but keeping
        // user-data work off the FFI critical section matches the
        // pattern used by sendEvent()/recvEvent().
        String typesJson;
        if (types == null || types.isEmpty()) {
            typesJson = null;
        } else {
            try {
                typesJson = MAPPER.writeValueAsString(types);
            } catch (Exception e) {
                throw new MeshException("Failed to serialize types filter", e);
            }
        }
        // Bridge Optional<Duration> → FFI negative-sentinel "no timeout".
        // Treat null AND negative as "no timeout" so the boundary
        // matches the recvEvent contract.
        double timeoutSecs;
        if (longPoll == null) {
            timeoutSecs = -1.0;
        } else {
            double secs = longPoll.toNanos() / 1_000_000_000.0;
            timeoutSecs = secs < 0.0 ? -1.0 : secs;
        }

        // Read-locked — multiple subscribers on the same cached proxy
        // long-poll listEvents concurrently. Rust-side `list_events`
        // explicitly does NOT serialise (see core/src/jobs.rs JobProxy
        // doc); the read lock only blocks against close()'s write lock.
        Pointer p;
        lock.readLock().lock();
        try {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_list_events(handle, after, typesJson, timeoutSecs, out);
            String err = rc == 0 ? null : lastError(core);
            switch (rc) {
                case 0:
                    p = out.getValue();
                    break;
                case -2:
                    throw new JobNotFoundException(
                        "mesh_job_proxy_list_events: job not found: " + err);
                case -1:
                case -3:
                default:
                    throw new MeshException(
                        "mesh_job_proxy_list_events failed (rc=" + rc + "): " + err);
            }
        } finally {
            lock.readLock().unlock();
        }
        if (p == null) {
            throw new MeshException("mesh_job_proxy_list_events returned null envelope");
        }
        try {
            String json = p.getString(0);
            return (Map<String, Object>) MAPPER.readValue(json, Map.class);
        } catch (Exception e) {
            throw new MeshException("Failed to parse list_events envelope JSON", e);
        } finally {
            core.mesh_free_string(p);
        }
    }

    /** Free the underlying native handle. Idempotent. */
    @Override
    public void close() {
        // See JobController.close() for the rationale: hold the WRITE
        // lock across the free so any in-flight FFI call (read-locked)
        // finishes first. Mutually exclusive with every other public
        // method on this class.
        lock.writeLock().lock();
        try {
            if (!closed) {
                closed = true;
                Pointer h = handle;
                handle = null;
                try {
                    if (h != null) {
                        core.mesh_job_proxy_free(h);
                    }
                } catch (RuntimeException e) {
                    log.warn("mesh_job_proxy_free threw for job {}: {}", jobId, e.getMessage());
                    throw e;
                }
            }
        } finally {
            lock.writeLock().unlock();
        }
    }

    /** Caller MUST hold either the read or write side of {@link #lock}. */
    private void ensureOpen() {
        if (closed || handle == null) {
            throw new MeshException("JobProxy for job " + jobId + " is closed");
        }
    }

    private static String lastError(MeshCore core) {
        Pointer err = core.mesh_last_error();
        if (err == null) {
            return "<no error message>";
        }
        try {
            return err.getString(0);
        } finally {
            core.mesh_free_string(err);
        }
    }

    @Override
    public String toString() {
        return "JobProxy{jobId=" + jobId + ", closed=" + closed + "}";
    }
}
