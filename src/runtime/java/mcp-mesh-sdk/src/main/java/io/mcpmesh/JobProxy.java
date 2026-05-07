package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshException;
import io.mcpmesh.core.MeshObjectMappers;
import jnr.ffi.Pointer;
import jnr.ffi.byref.PointerByReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

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
     * only while holding {@link #lock} — see {@link JobController} for
     * the same fix; without it a concurrent close could free the
     * pointer mid-FFI-call (PR #891 review).
     */
    private Pointer handle;
    private final String jobId;
    private final Object lock = new Object();
    private final AtomicBoolean closed = new AtomicBoolean(false);

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
        // FFI call inside the lock; JSON parse afterwards. We MUST own
        // the returned `p` before releasing the lock — once `close()`
        // runs it would otherwise be free to free a different handle
        // — but the result string itself was allocated by Rust and is
        // independent of the proxy handle, so we can parse it
        // unguarded.
        Pointer p;
        synchronized (lock) {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_status(handle, out);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_status failed: " + lastError(core));
            }
            p = out.getValue();
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
        // lock for that whole duration so a concurrent close() doesn't
        // free the handle while the Rust runtime is still polling on
        // it. Closing the proxy from another thread is a programming
        // error if you also have an outstanding await(), but the lock
        // prevents the worst (use-after-free) outcome.
        Pointer p;
        synchronized (lock) {
            ensureOpen();
            PointerByReference out = new PointerByReference();
            int rc = core.mesh_job_proxy_wait(handle, timeoutSecs, out);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_wait failed: " + lastError(core));
            }
            p = out.getValue();
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
        synchronized (lock) {
            ensureOpen();
            int rc = core.mesh_job_proxy_cancel(handle, reason);
            if (rc != 0) {
                throw new MeshException("mesh_job_proxy_cancel failed: " + lastError(core));
            }
        }
    }

    /** Free the underlying native handle. Idempotent. */
    @Override
    public void close() {
        // See JobController.close() for the rationale: hold the lock
        // across the free so any in-flight FFI call finishes first.
        synchronized (lock) {
            if (closed.compareAndSet(false, true)) {
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
        }
    }

    /** Caller MUST hold {@link #lock}. */
    private void ensureOpen() {
        if (closed.get() || handle == null) {
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
        return "JobProxy{jobId=" + jobId + ", closed=" + closed.get() + "}";
    }
}
