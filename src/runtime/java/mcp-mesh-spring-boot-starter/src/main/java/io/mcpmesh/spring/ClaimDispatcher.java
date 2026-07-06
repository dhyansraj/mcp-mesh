package io.mcpmesh.spring;

import io.mcpmesh.JobContext;
import io.mcpmesh.JobController;
import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshObjectMappers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Pure-Java claim dispatcher for {@code task=true} producers (Phase B —
 * MeshJob substrate). One dispatcher is spawned per registered task
 * capability; each runs a polling loop that:
 *
 * <ol>
 *   <li>Acquires a permit from a {@link Semaphore} sized to the
 *       concurrency cap (default 4 — matches Rust core +
 *       Python {@code _MAX_CONCURRENT_DISPATCHES} + TS dispatcher).</li>
 *   <li>POSTs to {@code /jobs/claim} on the registry. On 204 / empty,
 *       releases the permit and backs off (200ms → 1s → 5s).</li>
 *   <li>On a successful claim, hands the permit to the dispatch
 *       executor; the dispatch task constructs a {@link JobController},
 *       sets both Java + native contexts, invokes the user method via
 *       reflection, and auto-completes / fails as the inbound wrapper
 *       does. Releases the permit in {@code finally}.</li>
 * </ol>
 *
 * <p><b>Acquire-before-claim ordering</b> is critical — see PR #883 (Python)
 * and PR #885 (TypeScript) for the same fix. Without it, a 5th
 * concurrent claim could be granted while four handlers were still
 * running; the registry would record this agent as the owner and tick
 * down the lease, then orphan + reclaim once the lease expired.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.claim_dispatcher.PythonClaimDispatcher}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ClaimDispatcher} (claim-dispatcher.ts)</li>
 * </ul>
 */
public final class ClaimDispatcher implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(ClaimDispatcher.class);
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    /** Concurrency cap matches Rust core + Python + TS. */
    private static final int MAX_CONCURRENT_DISPATCHES = 4;

    private static final long POLL_BASE_MS = 200L;
    private static final long POLL_STEP_MS = 1_000L;
    private static final long POLL_MAX_MS = 5_000L;

    private static final long CLAIM_HTTP_TIMEOUT_SECS = 10L;
    private static final int CONSECUTIVE_FAILURE_ERROR_THRESHOLD = 5;

    private static final long DEFAULT_DRAIN_TIMEOUT_MS = 30_000L;

    /** Handler invoked with the claimed payload + a producer controller. */
    public interface ClaimHandler {
        /**
         * Run the user method for one claimed job. The dispatcher has
         * already constructed the controller and bound both job
         * contexts — the handler just calls the user method with the
         * payload and returns its result. Auto-complete is handled by
         * the dispatcher's caller (matches the inbound wrapper path).
         *
         * @param payload    The {@code submitted_payload} from the claim
         * @param controller A controller bound to the claimed job_id
         * @return The user method's return value
         * @throws Exception whatever the user method throws
         */
        Object handle(Map<String, Object> payload, JobController controller) throws Exception;
    }

    private final String capability;
    private final String instanceId;
    private final String registryUrl;
    private final ClaimHandler handler;
    /**
     * Issue #895: per-tool retry-eligible exception whitelist read from
     * the producer's {@code @MeshTool(retryOn=...)}. When the handler
     * raises a Throwable matching one of these classes, the dispatcher
     * calls {@link JobController#releaseLease(String)} instead of
     * {@link JobController#fail(String)} so a peer replica can re-claim
     * the job within ~5s. Always non-null (zero-length when not set).
     */
    private final Class<? extends Throwable>[] retryOn;

    /**
     * Issue #1277: cursor-resume opt-in read from the producer's
     * {@code @MeshTool(resumeCursor=...)}. When true AND the claim carries a
     * non-empty {@code recv_cursor}, the dispatcher opens the controller via
     * {@link JobController#openWithResume} so {@code recvEvent} resumes from
     * the persisted per-filter cursor instead of replaying from seq 0. When
     * false (default) or the claim has no cursor, the plain replay-from-0
     * {@link JobController#open} path is used.
     */
    private final boolean resumeCursor;

    /**
     * Issue #1268 pre-claim gate: returns the capability of a currently
     * unresolved {@code required} dependency (naming the reason a claim is
     * skipped), or {@code null} when the tool is clear to claim. Consulted
     * before every {@code /jobs/claim} attempt so a job for a capability whose
     * required dep is momentarily unresolved stays queued registry-side (no
     * owner, no attempt burn) and self-heals on a later poll — exactly the
     * #1258 claim-gating posture. Never null (defaults to "always ready").
     */
    private final java.util.function.Supplier<String> claimBlockedReason;

    /**
     * Tracks the gate's last observed state so the skip is logged once per
     * DOWN→UP / UP→DOWN transition (info) rather than every poll (issue #1268).
     */
    private final AtomicBoolean claimGated = new AtomicBoolean(false);

    private final Semaphore permits = new Semaphore(MAX_CONCURRENT_DISPATCHES);
    private final AtomicBoolean stopped = new AtomicBoolean(false);
    private final AtomicInteger consecutiveFailures = new AtomicInteger(0);

    /**
     * Tracks in-flight handler dispatches so {@link #stop(long)} can
     * drain them with a bounded timeout before closing the HttpClient
     * pool. Mirrors the TS dispatcher's {@code _inflightHandlers}
     * fix from PR #885.
     */
    private final Set<Future<?>> inflight = ConcurrentHashMap.newKeySet();

    /** The polling loop's executor (single-threaded, daemon). */
    private final ExecutorService loopExecutor;
    /** The dispatch executor — handlers run here so the loop stays free. */
    private final ExecutorService dispatchExecutor;
    /** HTTP client for /jobs/claim polls. Closed on stop(). */
    private final HttpClient httpClient;

    private Future<?> loopFuture;

    public ClaimDispatcher(String capability, String instanceId, String registryUrl, ClaimHandler handler) {
        this(capability, instanceId, registryUrl, handler, EMPTY_RETRY_ON);
    }

    public ClaimDispatcher(String capability, String instanceId, String registryUrl,
                           ClaimHandler handler, Class<? extends Throwable>[] retryOn) {
        this(capability, instanceId, registryUrl, handler, retryOn, null);
    }

    public ClaimDispatcher(String capability, String instanceId, String registryUrl,
                           ClaimHandler handler, Class<? extends Throwable>[] retryOn,
                           java.util.function.Supplier<String> claimBlockedReason) {
        this(capability, instanceId, registryUrl, handler, retryOn, claimBlockedReason, false);
    }

    /**
     * Construct a dispatcher with an explicit {@code retryOn} whitelist, a
     * pre-claim gate (issue #1268), and the cursor-resume opt-in (issue
     * #1277). Before each {@code /jobs/claim} poll the loop consults
     * {@code claimBlockedReason}; a non-null result names an unresolved
     * {@code required} dependency and the poll is skipped (the job stays
     * queued registry-side with no attempt burn) until the dep resolves.
     *
     * @param retryOn            Per-tool retry-eligible exception classes (may
     *                           be null/empty for "no retry-eligible exceptions").
     * @param claimBlockedReason Supplier returning the capability of an
     *                           unresolved required dependency, or {@code null}
     *                           when clear to claim. Null ⇒ "always ready".
     * @param resumeCursor       When true, a claim carrying a non-empty
     *                           {@code recv_cursor} opens the controller in
     *                           resume mode ({@code recvEvent} continues from
     *                           the persisted cursor); false ⇒ replay-from-0.
     */
    public ClaimDispatcher(String capability, String instanceId, String registryUrl,
                           ClaimHandler handler, Class<? extends Throwable>[] retryOn,
                           java.util.function.Supplier<String> claimBlockedReason,
                           boolean resumeCursor) {
        if (capability == null || capability.isEmpty()) {
            throw new IllegalArgumentException("capability is required");
        }
        if (instanceId == null || instanceId.isEmpty()) {
            throw new IllegalArgumentException("instanceId is required");
        }
        if (registryUrl == null || registryUrl.isEmpty()) {
            throw new IllegalArgumentException("registryUrl is required");
        }
        if (handler == null) {
            throw new IllegalArgumentException("handler is required");
        }
        this.capability = capability;
        this.instanceId = instanceId;
        this.registryUrl = stripTrailingSlash(registryUrl);
        this.handler = handler;
        this.retryOn = retryOn != null ? retryOn : EMPTY_RETRY_ON;
        this.claimBlockedReason = claimBlockedReason != null ? claimBlockedReason : () -> null;
        this.resumeCursor = resumeCursor;
        this.loopExecutor = Executors.newSingleThreadExecutor(named("mesh-claim-loop-" + capability));
        this.dispatchExecutor = Executors.newFixedThreadPool(MAX_CONCURRENT_DISPATCHES,
            named("mesh-claim-dispatch-" + capability));
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(CLAIM_HTTP_TIMEOUT_SECS))
            .build();
    }

    /** Issue #895: shared empty retryOn array — sentinel for "no retry-eligible exceptions". */
    @SuppressWarnings("unchecked")
    private static final Class<? extends Throwable>[] EMPTY_RETRY_ON =
        (Class<? extends Throwable>[]) new Class<?>[0];

    /** Spawn the polling loop. Idempotent. */
    public synchronized void start() {
        if (loopFuture != null) {
            return;
        }
        log.info("ClaimDispatcher started: capability={} instance={}", capability, instanceId);
        loopFuture = loopExecutor.submit(this::runLoop);
    }

    /**
     * Signal stop and drain in-flight handlers with the default 30s
     * timeout, then close the HttpClient pool. Idempotent.
     */
    @Override
    public void close() {
        stop(DEFAULT_DRAIN_TIMEOUT_MS);
    }

    /**
     * Signal stop and drain in-flight handlers with the given timeout.
     * Best-effort — never throws. Pass {@code 0} for an immediate close
     * (skips the drain entirely; tests use this).
     */
    public void stop(long drainTimeoutMs) {
        if (!stopped.compareAndSet(false, true)) {
            return;
        }
        log.info("ClaimDispatcher stopping: capability={} instance={} (drainTimeoutMs={})",
            capability, instanceId, drainTimeoutMs);
        // Wake the loop if it's blocked on permit acquire.
        permits.release(MAX_CONCURRENT_DISPATCHES * 2);

        // Stop the loop executor — it will exit at the next iteration check.
        loopExecutor.shutdownNow();
        try {
            loopExecutor.awaitTermination(2, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        // Drain in-flight handler dispatches before closing the HttpClient.
        if (drainTimeoutMs > 0 && !inflight.isEmpty()) {
            long deadline = System.currentTimeMillis() + drainTimeoutMs;
            for (Future<?> f : new HashSet<>(inflight)) {
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0) {
                    log.warn("ClaimDispatcher capability={} instance={}: drain timed out " +
                        "with {} handler(s) still in-flight; closing pool anyway",
                        capability, instanceId, inflight.size());
                    break;
                }
                try {
                    f.get(remaining, TimeUnit.MILLISECONDS);
                } catch (TimeoutException te) {
                    log.warn("ClaimDispatcher drain: handler still in-flight after timeout");
                    break;
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                } catch (ExecutionException ee) {
                    // Handler error already logged inside dispatch — ignore here.
                }
            }
        }

        dispatchExecutor.shutdownNow();
        try {
            dispatchExecutor.awaitTermination(2, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        // HttpClient (java.net.http) doesn't expose a close() in Java 17;
        // shutdown() / close() were added in 21. Use reflection so the
        // dispatcher compiles on 17 and still cleanly closes on 21+.
        try {
            httpClient.getClass().getMethod("close").invoke(httpClient);
        } catch (NoSuchMethodException nme) {
            // Java 17 — no explicit close. Pool will be GC'd; fine for
            // test harnesses since the ClassLoader survives.
        } catch (Exception e) {
            log.debug("HttpClient close failed: {}", e.getMessage());
        }
    }

    // ===== Internals ==========================================================

    private void runLoop() {
        long backoffMs = POLL_BASE_MS;
        try {
            while (!stopped.get() && !Thread.currentThread().isInterrupted()) {
                // Acquire BEFORE polling /jobs/claim so we never claim
                // more jobs than we can immediately execute. See class
                // javadoc for the cross-SDK rationale.
                try {
                    permits.acquire();
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
                if (stopped.get()) {
                    permits.release();
                    return;
                }

                // Pre-claim local skip (issue #1268): do not POST /jobs/claim
                // while any REQUIRED dependency slot is locally unresolved. The
                // job stays queued registry-side with no owner and no attempt
                // increment — the #1258 posture — and self-heals on a later
                // poll once the dep lands. Logged once per DOWN→UP transition.
                String blockedCap = claimBlockedReason.get();
                if (blockedCap != null) {
                    permits.release();
                    if (claimGated.compareAndSet(false, true)) {
                        log.info("[mesh-claim] capability={} instance={}: skipping claim — "
                            + "required dependency '{}' unavailable; job stays queued (no attempt burn)",
                            capability, instanceId, blockedCap);
                    } else {
                        log.debug("[mesh-claim] capability={} instance={}: still gated on "
                            + "required dependency '{}'", capability, instanceId, blockedCap);
                    }
                    // Fixed base cadence while gated (matches Python/TS ~0.5s) —
                    // do NOT ride the exponential no-work backoff, so claims
                    // resume within ~one poll of the required dep landing.
                    sleep(POLL_BASE_MS);
                    continue;
                }
                if (claimGated.compareAndSet(true, false)) {
                    // Gate just opened — reset any inherited no-work backoff so
                    // the resumed claim cadence isn't delayed by a stale window.
                    backoffMs = POLL_BASE_MS;
                    log.info("[mesh-claim] capability={} instance={}: required dependencies resolved — "
                        + "resuming claims", capability, instanceId);
                }

                Map<String, Object> claimed;
                boolean permitTransferred = false;
                try {
                    claimed = claimOnce();
                } catch (Exception e) {
                    int n = consecutiveFailures.incrementAndGet();
                    String msg = "claim_once raised: " + e + " (consecutive_failures=" + n + ")";
                    if (n >= CONSECUTIVE_FAILURE_ERROR_THRESHOLD) {
                        log.error("[mesh-claim] capability={} instance={}: {}", capability, instanceId, msg);
                    } else {
                        log.warn("[mesh-claim] capability={} instance={}: {}", capability, instanceId, msg);
                    }
                    permits.release();
                    sleep(backoffMs);
                    backoffMs = Math.min(backoffMs == POLL_BASE_MS ? POLL_STEP_MS : backoffMs * 5, POLL_MAX_MS);
                    continue;
                }

                if (claimed != null) {
                    consecutiveFailures.set(0);
                    backoffMs = POLL_BASE_MS;
                    // Hand the permit ownership to the dispatch task. The
                    // task self-removes its own Future from `inflight` in
                    // finally — without this, every claimed job would
                    // accumulate a Future entry holding the full payload
                    // map for the lifetime of the JVM (PR review #874).
                    //
                    // Construct the FutureTask FIRST and add it to
                    // `inflight` BEFORE handing it to the executor. With
                    // the previous `executor.submit() then add`
                    // pattern, a fast worker could run the whole
                    // handler + finally.remove() before the caller's
                    // add() landed — leaving a completed-but-never-
                    // removed Future leaked in the set (PR #891 review).
                    final java.util.concurrent.FutureTask<?> task =
                        new java.util.concurrent.FutureTask<Void>(() -> {
                            try {
                                dispatch(claimed);
                            } finally {
                                permits.release();
                                // `task` is in scope via the lambda
                                // capture; this is safe because the
                                // FutureTask reference is established
                                // before .execute() runs the body.
                            }
                            return null;
                        });
                    inflight.add(task);
                    permitTransferred = true;
                    try {
                        dispatchExecutor.execute(() -> {
                            try {
                                task.run();
                            } finally {
                                inflight.remove(task);
                            }
                        });
                    } catch (RuntimeException rejected) {
                        // Executor refused (shutdown race). Undo the
                        // bookkeeping so we don't leak a Future that
                        // never completes.
                        inflight.remove(task);
                        permits.release();
                        permitTransferred = false;
                        throw rejected;
                    }
                } else {
                    // No work — release permit and back off.
                    permits.release();
                    sleep(backoffMs);
                    backoffMs = Math.min(backoffMs == POLL_BASE_MS ? POLL_STEP_MS : backoffMs * 5, POLL_MAX_MS);
                }
                if (!permitTransferred && stopped.get()) {
                    return;
                }
            }
        } finally {
            log.info("ClaimDispatcher stopped: capability={} instance={}", capability, instanceId);
        }
    }

    /**
     * One {@code POST /jobs/claim} round-trip. Returns the single
     * claimed-job map (Phase 1 wire is single-claim) or null when no
     * work is available / on error. Errors increment
     * {@link #consecutiveFailures}; the loop logs at warn or error
     * depending on the count.
     */
    private Map<String, Object> claimOnce() throws Exception {
        String url = registryUrl + "/jobs/claim";
        // Use Jackson rather than manual escape — capability / instance_id
        // are well-formed in practice but a stray '\' or control char in
        // either would otherwise produce invalid JSON (PR review #874).
        String body = MAPPER.writeValueAsString(Map.of(
            "capability", capability,
            "instance_id", instanceId
        ));
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofSeconds(CLAIM_HTTP_TIMEOUT_SECS))
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) {
            return null;
        }
        if (resp.statusCode() != 200) {
            throw new RuntimeException("unexpected status " + resp.statusCode() + " from " + url);
        }
        JsonNode root = MAPPER.readTree(resp.body());
        JsonNode claimedArr = root.get("claimed");
        if (claimedArr == null || !claimedArr.isArray() || claimedArr.size() == 0) {
            return null;
        }
        // Phase 1 wire is single-claim by design. Defensive: take the first.
        if (claimedArr.size() > 1) {
            log.warn("[mesh-claim] capability={} instance={}: multi-claim response (got {} jobs) — " +
                "Phase 1 wire is single-claim by design; taking first only",
                capability, instanceId, claimedArr.size());
        }
        JsonNode first = claimedArr.get(0);
        if (first == null || !first.isObject()) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> claimedMap = MAPPER.convertValue(first, Map.class);
        if (claimedMap.get("id") == null) {
            return null;
        }
        return claimedMap;
    }

    /**
     * Run the local handler for one claimed job. Constructs a controller,
     * sets both Java + native job contexts, invokes the handler, auto-
     * completes / fails. Mirrors the inbound dispatch wrapper exactly so
     * push-mode (header-based) and pull-mode (claim-based) producers use
     * the same auto-complete semantics.
     */
    private void dispatch(Map<String, Object> claimed) {
        String jobId = String.valueOf(claimed.getOrDefault("id", ""));
        if (jobId.isEmpty()) return;

        @SuppressWarnings("unchecked")
        Map<String, Object> payload = claimed.get("submitted_payload") instanceof Map
            ? (Map<String, Object>) claimed.get("submitted_payload")
            : Map.of();
        Long deadlineSecs = null;
        Object maxDur = claimed.get("max_duration");
        if (maxDur instanceof Number n && n.longValue() > 0) {
            deadlineSecs = n.longValue();
        }
        // Claim generation minted by the registry on this claim (issue #1252).
        // Fences the controller's deltas + executor reads so a supersession
        // aborts this attempt. Absent on an old registry ⇒ null ⇒ legacy
        // owner-only fencing; never fabricate a 0 the registry didn't mint.
        Long claimEpoch = extractClaimEpoch(claimed.get("claim_epoch"));

        JobController controller;
        try {
            // Issue #1277: resume the recvEvent cursor from the claim's
            // persisted recv_cursor when the tool opted in AND the registry
            // supplied a non-empty cursor; else replay-from-0 (the default).
            controller = openController(jobId, claimEpoch, claimed.get("recv_cursor"));
        } catch (Exception e) {
            log.warn("[mesh-claim] failed to construct controller for job={}: {}", jobId, e.getMessage());
            // Best-effort: tell the registry we failed so the row doesn't
            // sit in `working` until the lease sweep notices.
            failJobByIdDirectly(jobId, "controller construction failed: " + e.getMessage());
            return;
        }

        try {
            // Bind both the Rust-side cancel registry (via mesh_run_as_job)
            // and the Java-side ThreadLocal job context (via
            // JobContext.withJob) for the user method's duration. The
            // Rust callback wrapper applies tokio::task::block_in_place
            // so nested mesh_job_controller_* block_on calls are legal.
            // See MeshToolWrapper.dispatchAsJob class javadoc for the
            // full rationale (resolved via #889).
            JobContext.Snapshot snap = new JobContext.Snapshot(jobId, deadlineSecs, claimEpoch);
            try {
                runAsJobWithRegistryBinding(jobId, deadlineSecs, claimEpoch, () -> {
                    JobContext.withJob(snap, () -> {
                        runHandler(payload, controller);
                        return null;
                    });
                    return null;
                });
            } catch (Throwable t) {
                // `runHandler` itself catches user-method exceptions and
                // calls `controller.fail(...)` — anything that lands here
                // is a dispatcher-internal error (JobContext binding,
                // reflection on the handler lambda, etc.). Without an
                // eager fail() the job stays in `working` until the
                // registry's lease sweep notices, which can be minutes.
                // (PR #891 review.)
                log.error("[mesh-claim] dispatcher-internal error for job={} capability={}: {}",
                    jobId, capability, t, t);
                String reason = "dispatcher-internal: " + (t.getMessage() != null
                    ? t.getMessage()
                    : t.getClass().getSimpleName());
                // Try the open controller first (cheap, already authenticated);
                // fall back to a direct /jobs/batch POST if the controller is
                // already terminal or its FFI call also fails.
                boolean reported = false;
                try {
                    if (!controller.isTerminal()) {
                        controller.fail(reason);
                        reported = true;
                    } else {
                        reported = true;  // already terminal — nothing more to do
                    }
                } catch (Throwable failErr) {
                    log.warn("[mesh-claim] controller.fail() failed for job={}: {}; " +
                        "falling back to /jobs/batch", jobId, failErr.getMessage());
                }
                if (!reported) {
                    failJobByIdDirectly(jobId, reason);
                }
            }
        } finally {
            controller.close();
        }
    }

    /**
     * Issue #1277 gate: choose the controller-open path for a claimed job.
     * When this dispatcher's tool opted into {@code resumeCursor} AND the
     * claim carried a non-empty {@code recv_cursor} map, open in resume mode
     * so {@code recvEvent} continues from the persisted per-filter cursor;
     * otherwise the plain replay-from-0 path. A malformed / empty / absent
     * cursor degrades to plain open — resume is a best-effort optimization
     * and never fails the dispatch. Package-private so the gate logic is
     * unit-testable at the {@link JobController} boundary without a live
     * native.
     *
     * @param recvCursorRaw the claim's {@code recv_cursor} value (a
     *                      {@code Map<String, Number>} or null)
     */
    JobController openController(String jobId, Long claimEpoch, Object recvCursorRaw) {
        if (resumeCursor && recvCursorRaw instanceof Map<?, ?> cursor && !cursor.isEmpty()) {
            @SuppressWarnings("unchecked")
            Map<String, ?> typed = (Map<String, ?>) cursor;
            return JobController.openWithResume(jobId, instanceId, registryUrl, claimEpoch, typed);
        }
        return JobController.open(jobId, instanceId, registryUrl, claimEpoch);
    }

    private void runHandler(Map<String, Object> payload, JobController controller) {
        Object result;
        try {
            result = handler.handle(payload, controller);
        } catch (Throwable t) {
            // Issue #895: retryOn-aware terminal handling. Mirrors Python
            // `_run_and_autocomplete` (job_dispatch.py:336-386) and TS
            // `runWithJobContext` (inbound-job-dispatch.ts:160-225). On a
            // suppressed (retryOn-matched) exception we just return — the
            // registry now owns the row's lifecycle. On non-matching, we
            // already best-effort fail()ed inside the helper; swallow
            // here too so the dispatch task ends without leaking the
            // exception into the executor's uncaught handler (would just
            // log noise; the controller already reflects the terminal
            // state).
            handleRetryOrFail(controller, t);
            return;
        }
        // Auto-complete iff the user didn't already close the row.
        try {
            if (!controller.isTerminal()) {
                controller.complete(result);
            }
        } catch (Exception e) {
            log.warn("Auto-complete failed for job {}: {}", controller.jobId(), e.getMessage());
        }
    }

    private static void tryFail(JobController controller, String reason) {
        try {
            if (!controller.isTerminal()) {
                controller.fail(reason);
            }
        } catch (Exception ignored) {
            // Best-effort.
        }
    }

    /**
     * Issue #895 — retryOn-aware terminal reporter for the claim path.
     *
     * <p>Mirrors {@link MeshToolWrapper}'s {@code handleRetryOrFail} (and
     * Python {@code _run_and_autocomplete}: probe is_terminal → retryOn
     * match triggers releaseLease → fall back to fail() on release
     * failure → non-matching does best-effort fail()). Returns without
     * propagating; the caller (runHandler) treats handler exceptions as
     * already-reported once this returns.
     */
    private void handleRetryOrFail(JobController controller, Throwable cause) {
        // Step 1: probe is_terminal — user may have already called
        // complete()/fail(); their terminal call is the source of truth.
        boolean alreadyTerminal = false;
        try {
            alreadyTerminal = controller.isTerminal();
        } catch (Throwable probeErr) {
            log.debug("[mesh-claim] is_terminal probe failed for job={}: {}",
                controller.jobId(), probeErr.toString());
        }
        if (alreadyTerminal) {
            return;
        }

        // Step 2 (issue #895): retryOn match → releaseLease (suppress) or
        // fail() fallback.
        if (retryOn != null && retryOn.length > 0) {
            for (Class<? extends Throwable> cls : retryOn) {
                if (cls.isInstance(cause)) {
                    String reason = cause.getClass().getSimpleName() +
                        ": " + cause.getMessage();
                    try {
                        controller.releaseLease(reason);
                        log.info("[mesh-claim] retryOn match for job={} ({}); released lease for fast retry",
                            controller.jobId(), reason);
                        return;
                    } catch (Throwable releaseErr) {
                        log.warn("[mesh-claim] release_lease failed for job={} ({}); falling back to fail()",
                            controller.jobId(), releaseErr.toString());
                        try {
                            controller.fail(
                                "retry-eligible " + reason +
                                "; release_lease failed: " + releaseErr.getMessage()
                            );
                        } catch (Throwable failErr) {
                            log.debug("[mesh-claim] fallback fail() also failed for job={}: {}",
                                controller.jobId(), failErr.toString());
                        }
                        return;
                    }
                }
            }
        }

        // Step 3: non-retryable → existing best-effort fail() behaviour.
        tryFail(controller, cause.toString());
    }

    /**
     * Fail a job by posting a single {@code failed} delta to
     * {@code /jobs/batch}, bypassing the (failed) controller construction
     * path. Without this the row stays in {@code working} until the
     * registry's lease sweeper notices, which can be minutes.
     */
    private void failJobByIdDirectly(String jobId, String reason) {
        try {
            String body = MAPPER.writeValueAsString(Map.of(
                "instance_id", instanceId,
                "deltas", new Object[]{ Map.of(
                    "id", jobId,
                    "status", "failed",
                    "error", reason
                )}
            ));
            HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(registryUrl + "/jobs/batch"))
                .timeout(Duration.ofSeconds(CLAIM_HTTP_TIMEOUT_SECS))
                .header("content-type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();
            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                log.warn("[mesh-claim] /jobs/batch returned {} when failing job={}; relying on registry sweep",
                    resp.statusCode(), jobId);
            }
        } catch (Exception e) {
            log.warn("[mesh-claim] /jobs/batch fail-fast for job={} raised: {}", jobId, e.getMessage());
        }
    }

    /**
     * Wrap a Java {@link java.util.concurrent.Callable} in
     * {@link MeshCore#mesh_run_as_job} so the Rust cancel-registry entry
     * for {@code jobId} is bound while the callable runs. Mirrors the
     * inbound wrapper's helper (see
     * {@link MeshToolWrapper#dispatchAsJob} class javadoc; resolved via
     * #889). Throwables raised by the body callable are captured in a
     * closure-captured holder and rethrown after {@code mesh_run_as_job}
     * returns, preserving the original exception type — the C ABI's
     * {@code int} return is too coarse to carry exception identity.
     *
     * <p>Snapshot serialization is a precondition, NOT part of the body:
     * a Jackson failure inside {@link #buildRunAsJobSnapshot} (extremely
     * unlikely given the trivial two-scalar map shape) propagates as
     * {@link IllegalStateException} to the caller and never reaches the
     * native FFI. The unified rethrow logic only covers exceptions raised
     * inside the user-supplied callable.
     */
    private Object runAsJobWithRegistryBinding(
            String jobId, Long deadlineSecs, Long claimEpoch,
            java.util.concurrent.Callable<Object> body)
            throws Exception {
        String snapshotJson = buildRunAsJobSnapshot(jobId, deadlineSecs, claimEpoch);
        Object[] resultBox = new Object[1];
        Throwable[] thrownBox = new Throwable[1];
        MeshCore core = MeshCore.load();
        int rc = core.mesh_run_as_job(snapshotJson, userData -> {
            try {
                resultBox[0] = body.call();
                return 0;
            } catch (Throwable t) {
                thrownBox[0] = t;
                return -1;
            }
        }, null);
        if (thrownBox[0] != null) {
            if (thrownBox[0] instanceof Exception ex) throw ex;
            if (thrownBox[0] instanceof Error err) throw err;
            throw new RuntimeException(thrownBox[0]);
        }
        if (rc != 0) {
            throw new RuntimeException(
                "mesh_run_as_job failed (rc=" + rc + ") for job=" + jobId
                + ": " + readLastError(core));
        }
        return resultBox[0];
    }

    static String buildRunAsJobSnapshot(String jobId, Long deadlineSecs, Long claimEpoch) {
        try {
            java.util.Map<String, Object> snap = new java.util.LinkedHashMap<>();
            snap.put("job_id", jobId);
            snap.put("deadline_secs", deadlineSecs);
            // Additive (issue #1252): carry the claim generation so the Rust
            // JobContext exposes it via mesh_current_job. null ⇒ legacy.
            snap.put("claim_epoch", claimEpoch);
            return MAPPER.writeValueAsString(snap);
        } catch (Exception e) {
            throw new IllegalStateException(
                "failed to serialize mesh_run_as_job snapshot for job=" + jobId, e);
        }
    }

    /**
     * Coerce a claim-response {@code claim_epoch} value (Jackson deserializes
     * it as an Integer/Long) into a {@link Long} generation, or {@code null}
     * when absent / malformed / negative (issue #1252). Only a registry-minted
     * non-negative generation is a real epoch — a genuine {@code 0} is valid;
     * never fabricate one the registry didn't mint.
     */
    static Long extractClaimEpoch(Object raw) {
        if (raw instanceof Number n) {
            long v = n.longValue();
            return v >= 0 ? v : null;
        }
        return null;
    }

    private static String readLastError(MeshCore core) {
        jnr.ffi.Pointer err = core.mesh_last_error();
        if (err == null) return "<no error>";
        try {
            return err.getString(0);
        } finally {
            core.mesh_free_string(err);
        }
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static ThreadFactory named(String prefix) {
        AtomicInteger seq = new AtomicInteger();
        return r -> {
            Thread t = new Thread(r, prefix + "-" + seq.incrementAndGet());
            t.setDaemon(true);
            return t;
        };
    }
}
