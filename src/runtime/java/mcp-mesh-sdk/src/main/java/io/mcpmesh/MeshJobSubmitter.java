package io.mcpmesh;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshException;
import io.mcpmesh.core.MeshObjectMappers;
import jnr.ffi.Pointer;
import jnr.ffi.byref.PointerByReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Consumer-side submitter: injected via {@link MeshJob} DDDI for tools that
 * depend on a {@code task = true} capability. Calling {@link #submit(Map)}
 * returns a {@link JobProxy} the user can {@code wait()} / {@code status()} /
 * {@code cancel()} on.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.job_submitter.MeshJobSubmitter}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ... MeshJobSubmitter}</li>
 * </ul>
 *
 * <p><b>Async ergonomics:</b> the underlying C ABI is sync (the FFI runtime
 * blocks on the registry call). The {@link #submit(Map)} entry point wraps
 * that in a {@link CompletableFuture} so application code can compose it
 * with other async work without holding a thread. The CF is completed on
 * a dedicated {@link #IO_EXECUTOR} cached thread pool — NOT the common
 * {@link java.util.concurrent.ForkJoinPool}, because {@code mesh_submit_job}
 * blocks on a network FFI call and a sustained burst of submissions
 * would otherwise saturate the FJP and stall every other CompletableFuture
 * in the JVM (PR #891 review).
 *
 * <p>The submitter itself is stateless after construction (capability +
 * registry URL only); a single instance can be used for many submissions.
 */
public final class MeshJobSubmitter implements MeshJob {

    private static final Logger log = LoggerFactory.getLogger(MeshJobSubmitter.class);
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    /**
     * Dedicated executor for the blocking {@code mesh_submit_job} FFI
     * call. Cached pool — grows on demand under burst, threads die
     * after 60s idle. Daemon threads so the JVM can shut down without
     * waiting on idle workers.
     *
     * <p>Java 17 baseline (no virtual threads); when the project moves
     * to Java 21+ this can become {@code Thread.ofVirtual().factory()}
     * and the cached pool can shrink to a small fixed pool driving the
     * VTs.
     */
    private static final Executor IO_EXECUTOR = Executors.newCachedThreadPool(
        new java.util.concurrent.ThreadFactory() {
            private final AtomicInteger seq = new AtomicInteger();
            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r, "mesh-job-submit-io-" + seq.incrementAndGet());
                t.setDaemon(true);
                return t;
            }
        }
    );

    private final MeshCore core;
    private final String capability;
    private final String submittedBy;
    private final String registryUrl;

    /**
     * Construct a submitter bound to a capability + the local instance ID.
     * Phase B's DDDI wiring constructs these per-call-site; the constructor
     * is also exposed for tests.
     *
     * @param capability   Target capability name (the {@code task = true} tool)
     * @param submittedBy  Submitter identity (typically this agent's instance id)
     * @param registryUrl  Registry base URL
     */
    public MeshJobSubmitter(String capability, String submittedBy, String registryUrl) {
        if (capability == null || capability.isEmpty()) {
            throw new IllegalArgumentException("capability is required");
        }
        if (submittedBy == null || submittedBy.isEmpty()) {
            throw new IllegalArgumentException("submittedBy is required");
        }
        if (registryUrl == null || registryUrl.isEmpty()) {
            throw new IllegalArgumentException("registryUrl is required");
        }
        this.core = MeshCore.load();
        this.capability = capability;
        this.submittedBy = submittedBy;
        this.registryUrl = registryUrl;
    }

    /** Capability this submitter targets. */
    public String capability() {
        return capability;
    }

    /** Identity recorded as {@code submitted_by} on each new job row. */
    public String submittedBy() {
        return submittedBy;
    }

    /**
     * Submit a job with the given payload, no extra options.
     *
     * <p>Equivalent to {@link #submit(SubmitOptions)} with a default
     * {@link SubmitOptions} carrying just the payload.
     */
    public CompletableFuture<JobProxy> submit(Map<String, Object> payload) {
        return submit(new SubmitOptions(payload, null, null, null, null));
    }

    /**
     * Submit a job with full control over registry-side options.
     *
     * @param options Submission options (payload + optional duration / retries / deadline)
     * @return A future resolving to a {@link JobProxy} for the new job, or
     *         completing exceptionally with a {@link MeshException} on
     *         submission failure.
     */
    public CompletableFuture<JobProxy> submit(SubmitOptions options) {
        if (options == null) {
            return CompletableFuture.failedFuture(
                new IllegalArgumentException("options is required"));
        }
        // Build the args envelope on the calling thread (cheap, deterministic
        // failure surface) — the heavy lifting (network call) happens on
        // the FJP worker.
        final String argsJson;
        try {
            argsJson = buildArgsJson(options);
        } catch (Exception e) {
            return CompletableFuture.failedFuture(
                new MeshException("Failed to encode submit args", e));
        }
        return CompletableFuture.supplyAsync(() -> doSubmit(argsJson), IO_EXECUTOR);
    }

    private JobProxy doSubmit(String argsJson) {
        PointerByReference out = new PointerByReference();
        int rc = core.mesh_submit_job(argsJson, out);
        if (rc != 0) {
            throw new MeshException("mesh_submit_job failed: " + lastError(core));
        }
        Pointer handle = out.getValue();
        if (handle == null) {
            throw new MeshException("mesh_submit_job returned null handle");
        }
        // Read the job id off the proxy so the wrapper can carry it without
        // a second FFI hop later.
        PointerByReference idOut = new PointerByReference();
        int rc2 = core.mesh_job_proxy_job_id(handle, idOut);
        if (rc2 != 0) {
            // Free the handle we just leaked into ownership-land.
            core.mesh_job_proxy_free(handle);
            throw new MeshException("mesh_job_proxy_job_id failed: " + lastError(core));
        }
        Pointer idPtr = idOut.getValue();
        String jobId;
        try {
            jobId = idPtr != null ? idPtr.getString(0) : "";
        } finally {
            if (idPtr != null) {
                core.mesh_free_string(idPtr);
            }
        }
        log.debug("Submitted job {} for capability {}", jobId, capability);
        return new JobProxy(core, handle, jobId);
    }

    private String buildArgsJson(SubmitOptions options) {
        ObjectNode root = MAPPER.createObjectNode();
        root.put("registry_url", registryUrl);
        root.put("capability", capability);
        root.put("submitted_by", submittedBy);
        // Payload may be null → emit JSON null so the wire schema validates.
        root.set("payload", MAPPER.valueToTree(options.payload));
        if (options.ownerInstanceId != null) {
            root.put("owner_instance_id", options.ownerInstanceId);
        }
        if (options.maxDuration != null) {
            root.put("max_duration", options.maxDuration);
        }
        if (options.maxRetries != null) {
            root.put("max_retries", options.maxRetries);
        }
        if (options.totalDeadline != null) {
            root.put("total_deadline", options.totalDeadline);
        }
        return MAPPER.writeValueAsString(root);
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

    /**
     * Submission options. All fields except {@code payload} are optional;
     * pass {@code null} to accept the registry / runtime defaults.
     *
     * <p>Field semantics match {@code SubmitJobArgs} in the Rust core
     * ({@code jobs.rs}): {@code maxDuration} is per-attempt seconds,
     * {@code maxRetries} caps the retry budget, {@code totalDeadline} is
     * an absolute Unix-epoch second cap across all retries (null ≡
     * unlimited), and {@code ownerInstanceId} pins the job to a specific
     * replica (push mode) vs. leaving it unclaimed for pull-mode workers.
     */
    public static final class SubmitOptions {
        public final Map<String, Object> payload;
        public final String ownerInstanceId;
        public final Integer maxDuration;
        public final Integer maxRetries;
        public final Long totalDeadline;

        public SubmitOptions(
                Map<String, Object> payload,
                String ownerInstanceId,
                Integer maxDuration,
                Integer maxRetries,
                Long totalDeadline) {
            this.payload = payload;
            this.ownerInstanceId = ownerInstanceId;
            this.maxDuration = maxDuration;
            this.maxRetries = maxRetries;
            this.totalDeadline = totalDeadline;
        }
    }
}
