package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshException;
import io.mcpmesh.core.MeshObjectMappers;
import jnr.ffi.Pointer;
import jnr.ffi.byref.PointerByReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Producer-side handle bound to a single job. Application code typically
 * receives one via {@link MeshJob} DDDI injection — the inbound tool wrapper
 * (Phase B) constructs it from the {@code X-Mesh-Job-Id} header on a
 * dispatch-eligible {@code tools/call}.
 *
 * <p>Each controller owns a per-instance coalescing queue plus a background
 * batching tick (spawned by the Rust core) that flushes mid-flight progress
 * deltas to the registry on a fixed cadence (default 2s). Terminal calls
 * ({@link #complete} / {@link #fail}) flush immediately. The tick is shut
 * down with a final flush when {@link #close} runs.
 *
 * <p>Implements {@link AutoCloseable} so callers MAY use try-with-resources;
 * the wrapper's finalizer is intentionally NOT relied upon for cleanup
 * (those are unreliable). The runtime's tool dispatch wrapper closes the
 * controller in a {@code finally} after invocation.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.job_controller.PyJobController}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ... JobController}</li>
 * </ul>
 *
 * <p>Memory safety: the underlying native handle is freed exactly once via
 * {@link #close}, guarded by an {@link AtomicBoolean} so concurrent
 * close-from-multiple-threads is a no-op on the second call.
 */
public final class JobController implements MeshJob, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(JobController.class);
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private final MeshCore core;
    private final Pointer handle;
    private final String jobId;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    private JobController(MeshCore core, Pointer handle, String jobId) {
        this.core = core;
        this.handle = handle;
        this.jobId = jobId;
    }

    /**
     * Open a controller bound to the given job + instance against the registry.
     *
     * @param jobId       Server-assigned job UUID
     * @param instanceId  This agent's instance ID (used by the registry to
     *                    attribute deltas to a specific replica)
     * @param registryUrl Registry base URL
     * @return A new controller; caller MUST {@link #close} when done
     * @throws MeshException if the native handle cannot be allocated
     */
    public static JobController open(String jobId, String instanceId, String registryUrl) {
        if (jobId == null || jobId.isEmpty()) {
            throw new IllegalArgumentException("jobId is required");
        }
        if (instanceId == null || instanceId.isEmpty()) {
            throw new IllegalArgumentException("instanceId is required");
        }
        if (registryUrl == null || registryUrl.isEmpty()) {
            throw new IllegalArgumentException("registryUrl is required");
        }
        MeshCore core = MeshCore.load();
        PointerByReference out = new PointerByReference();
        int rc = core.mesh_job_controller_new(jobId, instanceId, registryUrl, out);
        if (rc != 0) {
            throw new MeshException("mesh_job_controller_new failed: " + lastError(core));
        }
        Pointer handle = out.getValue();
        if (handle == null) {
            throw new MeshException("mesh_job_controller_new returned null handle");
        }
        return new JobController(core, handle, jobId);
    }

    /**
     * Internal constructor for the inbound dispatch path (Phase B). Allows
     * the wrapper to construct a controller from an already-allocated native
     * handle — used when the dispatcher creates the handle inside the Rust
     * runtime scope.
     */
    static JobController fromHandle(MeshCore core, Pointer handle, String jobId) {
        return new JobController(core, handle, jobId);
    }

    /** The job ID this controller is bound to. */
    public String jobId() {
        return jobId;
    }

    /**
     * Enqueue a progress update. Coalesces with any prior pending progress
     * for this job — only the latest survives the next batch flush.
     *
     * @param progress Progress value (typically 0.0..1.0)
     * @param message  Optional progress message (may be null)
     * @throws MeshException if the controller is closed or the native call fails
     */
    public void updateProgress(double progress, String message) {
        ensureOpen();
        int rc = core.mesh_job_controller_update_progress(handle, progress, message);
        if (rc != 0) {
            throw new MeshException("mesh_job_controller_update_progress failed: " + lastError(core));
        }
    }

    /**
     * Mark the job complete with the given result. Flushes immediately.
     * The result is JSON-serialized via Jackson (uses the project's shared
     * {@link MeshObjectMappers} for consistency with other tool returns).
     *
     * @param result Any JSON-serializable value (record, POJO, Map, primitive...)
     * @throws MeshException if serialization or the native call fails
     */
    public void complete(Object result) {
        ensureOpen();
        String json;
        try {
            // null → JSON null. Jackson handles this directly.
            json = MAPPER.writeValueAsString(result);
        } catch (Exception e) {
            throw new MeshException("Failed to serialize job result", e);
        }
        int rc = core.mesh_job_controller_complete(handle, json);
        if (rc != 0) {
            throw new MeshException("mesh_job_controller_complete failed: " + lastError(core));
        }
    }

    /**
     * Mark the job failed with the given error reason. Flushes immediately.
     * Retry semantics (or lack thereof) are decided by the registry based
     * on the job's {@code max_retries} — see {@code MESHJOB_DESIGN.org}
     * "Failure & Retry".
     *
     * @param error Error reason (free-form string surfaced to consumers)
     * @throws MeshException if the native call fails
     */
    public void fail(String error) {
        ensureOpen();
        if (error == null) {
            error = "";
        }
        int rc = core.mesh_job_controller_fail(handle, error);
        if (rc != 0) {
            throw new MeshException("mesh_job_controller_fail failed: " + lastError(core));
        }
    }

    /**
     * Whether {@link #complete} / {@link #fail} has already been called on
     * this controller. The dispatch wrapper uses this to decide whether a
     * returning user method needs an auto-{@code complete} (the
     * "if the user forgot, finish the job for them" path).
     *
     * @return true if terminal, false otherwise
     * @throws MeshException if the native call fails
     */
    public boolean isTerminal() {
        ensureOpen();
        int rc = core.mesh_job_controller_is_terminal(handle);
        if (rc < 0) {
            throw new MeshException("mesh_job_controller_is_terminal failed: " + lastError(core));
        }
        return rc == 1;
    }

    /**
     * Free the underlying native handle and stop the background batching
     * tick (with a final flush). Idempotent — repeated calls are no-ops.
     */
    @Override
    public void close() {
        if (closed.compareAndSet(false, true)) {
            try {
                core.mesh_job_controller_free(handle);
            } catch (RuntimeException e) {
                // Don't swallow — but log so callers see the unusual case.
                log.warn("mesh_job_controller_free threw for job {}: {}", jobId, e.getMessage());
                throw e;
            }
        }
    }

    private void ensureOpen() {
        if (closed.get()) {
            throw new MeshException("JobController for job " + jobId + " is closed");
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
        return "JobController{jobId=" + jobId + ", closed=" + closed.get() + "}";
    }
}
