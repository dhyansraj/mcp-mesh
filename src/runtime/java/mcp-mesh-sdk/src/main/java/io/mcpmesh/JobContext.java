package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshObjectMappers;
import jnr.ffi.Pointer;
import jnr.ffi.byref.PointerByReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.util.concurrent.Callable;

/**
 * Java-side mirror of the Rust {@code job_context::JobContext} task-local.
 *
 * <p>Two layers of context live in parallel and intentionally — see
 * {@link io.mcpmesh.core.MeshCore#mesh_current_job} and the caveat block in
 * {@code jobs_ffi.rs}:
 *
 * <ul>
 *   <li><b>Rust side</b> — bound by {@code mesh_run_as_job}, visible to Rust
 *       futures polled within the scope (cancel-registry binding,
 *       Rust-originated outbound HTTP header injection).</li>
 *   <li><b>Java side</b> — this class' {@link ThreadLocal}, visible to user
 *       code and to Java-originated outbound calls. The two are mirrored
 *       by the inbound dispatch wrapper (Phase B) so user code can read
 *       {@link #current()} regardless of which side originated the work.</li>
 * </ul>
 *
 * <p>{@code ThreadLocal} (rather than {@code ScopedValue} from Project Loom)
 * is the safe-default: the rest of the project targets Java 17+ stable
 * APIs. A future revision can opt into {@code ScopedValue} for virtual-
 * thread fan-out scenarios.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.job_context.CURRENT_JOB} (contextvar)</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ... CURRENT_JOB} (AsyncLocalStorage)</li>
 * </ul>
 */
public final class JobContext {

    private static final Logger log = LoggerFactory.getLogger(JobContext.class);
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    /**
     * Snapshot of the active job context. Mirrors the Python
     * {@code JobContextSnapshot} dataclass and TS {@code JobContextSnapshot}
     * interface field-for-field.
     */
    public static final class Snapshot {
        public final String jobId;
        /** Seconds remaining on the deadline, or null if no deadline is set. */
        public final Long deadlineSecsRemaining;
        /**
         * Claim generation this attempt executes under (from the registry's
         * {@code POST /jobs/claim} response), or null for a push-mode inbound
         * job / an old registry (issue #1252). Additive, read-only — handlers
         * can stamp it on side effects so a superseded re-execution's writes
         * are distinguishable downstream. Supersession itself surfaces through
         * the existing cancellation path, not by polling this value.
         */
        public final Long claimEpoch;

        /** Back-compat constructor (no claim epoch — legacy owner-only). */
        public Snapshot(String jobId, Long deadlineSecsRemaining) {
            this(jobId, deadlineSecsRemaining, null);
        }

        public Snapshot(String jobId, Long deadlineSecsRemaining, Long claimEpoch) {
            this.jobId = jobId;
            this.deadlineSecsRemaining = deadlineSecsRemaining;
            this.claimEpoch = claimEpoch;
        }

        @Override
        public String toString() {
            return "JobContext.Snapshot{jobId=" + jobId
                + ", deadlineSecsRemaining=" + deadlineSecsRemaining
                + ", claimEpoch=" + claimEpoch + "}";
        }
    }

    private static final ThreadLocal<Snapshot> CURRENT = new ThreadLocal<>();

    private JobContext() {}

    /**
     * Snapshot of the active job context on the current thread, or null if
     * no job is in scope. Reads the Java-side {@link ThreadLocal} mirror,
     * NOT the Rust-side task-local (call
     * {@link io.mcpmesh.core.MeshCore#mesh_current_job} directly to read
     * the latter).
     */
    public static Snapshot current() {
        return CURRENT.get();
    }

    /**
     * Bind {@code snap} as the active job context on the current thread for
     * the duration of {@code body}, then restore the previous value (or
     * clear if there was none). Safe to nest.
     *
     * <p>This is the Java-side counterpart to Rust {@code with_job} — call it
     * from the inbound dispatch wrapper (Phase B) so user code reading
     * {@link #current()} during the tool invocation sees the right context.
     *
     * <p>For the full producer-side scope (cancel-registry binding +
     * deadline propagation to Rust outbound calls), pair this with
     * {@link MeshCore#mesh_run_as_job} so both sides are bound.
     *
     * @param snap Snapshot to bind (must not be null)
     * @param body Callable executed inside the scope
     * @return The body's return value
     * @throws Exception whatever {@code body} throws (verbatim)
     */
    public static <T> T withJob(Snapshot snap, Callable<T> body) throws Exception {
        if (snap == null) {
            throw new IllegalArgumentException("snap is required");
        }
        if (body == null) {
            throw new IllegalArgumentException("body is required");
        }
        Snapshot prev = CURRENT.get();
        CURRENT.set(snap);
        try {
            return body.call();
        } finally {
            if (prev != null) {
                CURRENT.set(prev);
            } else {
                CURRENT.remove();
            }
        }
    }

    /**
     * Convenience: bind a snapshot synthesized from the inbound
     * {@code X-Mesh-Job-Id} / {@code X-Mesh-Timeout} header pair. {@code
     * deadlineSecsRemaining} may be null when no deadline header was
     * present (matches the Rust "deadline opt-in / unlimited by default"
     * semantics).
     */
    public static <T> T withJob(String jobId, Long deadlineSecsRemaining, Callable<T> body)
            throws Exception {
        return withJob(new Snapshot(jobId, deadlineSecsRemaining), body);
    }

    /**
     * Read the Rust-side current job snapshot (NOT the Java ThreadLocal).
     * Available for FFI-bridge code that needs to know what the Rust core
     * sees — typically only used by the dispatch wrapper for parity checks.
     *
     * @return The snapshot, or null if no Rust task-local context is active
     */
    public static Snapshot currentFromNative() {
        MeshCore core = MeshCore.load();
        PointerByReference out = new PointerByReference();
        int rc = core.mesh_current_job(out);
        if (rc != 0) {
            log.warn("mesh_current_job returned {}, treating as no active context", rc);
            return null;
        }
        Pointer p = out.getValue();
        if (p == null) {
            return null;
        }
        try {
            String json = p.getString(0);
            tools.jackson.databind.JsonNode node = MAPPER.readTree(json);
            String jobId = node.has("job_id") ? node.get("job_id").asText() : null;
            Long remaining;
            if (node.has("deadline_secs_remaining") && !node.get("deadline_secs_remaining").isNull()) {
                remaining = node.get("deadline_secs_remaining").asLong();
            } else {
                remaining = null;
            }
            Long claimEpoch;
            if (node.has("claim_epoch") && !node.get("claim_epoch").isNull()) {
                claimEpoch = node.get("claim_epoch").asLong();
            } else {
                claimEpoch = null;
            }
            return new Snapshot(jobId, remaining, claimEpoch);
        } catch (Exception e) {
            log.warn("Failed to parse current job snapshot: {}", e.getMessage());
            return null;
        } finally {
            core.mesh_free_string(p);
        }
    }
}
