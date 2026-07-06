package com.example.longtaskprovider;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob test-suite producer (uc23_meshjob_java) — Java port of
 * uc21_meshjob/fixtures/long-task-provider/main.py and
 * uc22_meshjob_ts/fixtures/long-task-provider-ts.
 *
 * <p>Hosts a small zoo of {@code task = true} capabilities, one per
 * scenario the suite needs to exercise. Capability names mirror the
 * Python and TypeScript fixtures exactly so the polyglot tests
 * (tc17–tc22) can call them interchangeably across runtimes.
 *
 * <h2>Capabilities</h2>
 * <ul>
 *   <li>{@code generate_report}              — happy path, progress + complete</li>
 *   <li>{@code report_with_explicit_complete} — explicit complete({...}) marker</li>
 *   <li>{@code report_with_implicit_complete} — return value WITHOUT complete()</li>
 *   <li>{@code report_with_explicit_fail}     — calls fail("reason")</li>
 *   <li>{@code report_that_crashes}            — raises mid-attempt</li>
 *   <li>{@code runs_overlong}                  — long sleep loop for cancel tests</li>
 *   <li>{@code report_with_downstream_call}    — injects an McpMeshTool
 *       {@code slow_downstream} dependency and calls it (task=true +
 *       Selector deps; parity with Python's slow_downstream McpMeshAgent dep)</li>
 * </ul>
 */
@MeshAgent(
    name = "long-task-provider-java",
    version = "1.0.0",
    description = "MeshJob test producer (uc23 Java) — multi-capability fixture for the integration suite.",
    port = 9120
)
@SpringBootApplication
public class LongTaskProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(LongTaskProviderApplication.class, args);
    }

    // -------------------------------------------------------------------
    // Happy path — generate_report
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "generate_report",
        task = true,
        description = "Long-running multi-section report generator with progress."
    )
    public Map<String, Object> generateReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob job) throws InterruptedException {
        if (sections == null) {
            sections = List.of("default");
        }
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.0, "starting");
        }

        List<Map<String, String>> results = new ArrayList<>();
        int total = Math.max(sections.size(), 1);
        for (int i = 0; i < sections.size(); i++) {
            Thread.sleep(2000);
            String section = sections.get(i);
            Map<String, String> entry = new LinkedHashMap<>();
            entry.put("section", section);
            entry.put("content", "Generated content for " + section);
            results.add(entry);
            if (controller != null) {
                controller.updateProgress(
                    (i + 1.0) / total,
                    "finished section " + (i + 1) + "/" + total);
            }
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("report", results);

        if (controller != null) {
            controller.complete(payload);
        }
        return payload;
    }

    // -------------------------------------------------------------------
    // Explicit complete with fixed marker payload (tc03)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_with_explicit_complete",
        task = true,
        description = "Calls job.complete({...}) with a fixed marker payload."
    )
    public Map<String, Object> reportWithExplicitComplete(
            @Param("user_id") String userId,
            MeshJob job) throws InterruptedException {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.5, "midpoint");
            Thread.sleep(500);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("explicit", true);
        payload.put("marker", "X");
        payload.put("user_id", userId);
        if (controller != null) {
            controller.complete(payload);
        }
        return payload;
    }

    // -------------------------------------------------------------------
    // Implicit complete (auto-complete on return) (tc04)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_with_implicit_complete",
        task = true,
        description = "Returns a value WITHOUT calling job.complete() — relies on auto-complete."
    )
    public Map<String, Object> reportWithImplicitComplete(
            @Param("user_id") String userId,
            MeshJob job) throws InterruptedException {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.5, "halfway");
            Thread.sleep(500);
            controller.updateProgress(0.9, "almost done");
        }
        // Intentionally do NOT call complete() — runtime auto-complete should fire.
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("implicit", true);
        payload.put("user_id", userId);
        return payload;
    }

    // -------------------------------------------------------------------
    // Explicit fail — no retry (tc05)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_with_explicit_fail",
        task = true,
        description = "Calls job.fail('reason') — must NOT trigger retry even with max_retries > 0."
    )
    public Map<String, Object> reportWithExplicitFail(
            @Param("user_id") String userId,
            MeshJob job) throws InterruptedException {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.1, "about to fail");
            Thread.sleep(300);
            controller.fail("explicit: not retryable");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("failed", true);
        payload.put("reason", "explicit: not retryable");
        return payload;
    }

    // -------------------------------------------------------------------
    // Crash on attempt (tc12)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_that_crashes",
        task = true,
        description = "Always raises mid-attempt — drives crash-recovery / retry-exhaustion tests."
    )
    public Map<String, Object> reportThatCrashes(
            @Param("user_id") String userId,
            MeshJob job) throws InterruptedException {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.1, "about to crash");
            Thread.sleep(300);
        }
        throw new RuntimeException("simulated crash for crash-recovery test");
    }

    // -------------------------------------------------------------------
    // Transient-failure path — exercises @MeshTool(retryOn=...) (#895) (tc23)
    // -------------------------------------------------------------------
    //
    // Mirrors Python's report_with_transient_failures
    // (uc21_meshjob/fixtures/long-task-provider/main.py). The handler is
    // annotated with retryOn={IOException.class}: when the body throws
    // IOException the dispatch wrapper calls JobController.releaseLease
    // (NOT fail), so the registry resets owner_instance_id and the next
    // claim cycle re-runs the handler — proving the fast-retry path
    // engaged rather than waiting for lease expiry.
    //
    // The attempt counter lives at /tmp/mesh-retry-on-counter so it
    // survives across attempts even if the runtime ever hands the next
    // claim to a peer replica. Single-process here; the file pattern
    // matches Python so the assertions (attempt_count=3) remain
    // language-agnostic.
    // -------------------------------------------------------------------
    private static final Path RETRY_COUNTER_PATH = Paths.get("/tmp/mesh-retry-on-counter");

    /**
     * Atomic-ish file-based counter shared across attempts. Returns the
     * NEW (post-increment) value so the handler can decide whether this
     * attempt is in the transient-failure window or the success window.
     *
     * <p>Uses {@link FileLock} so concurrent claims (would-be peers in a
     * future scaled scenario) don't lose updates. Mirrors Python's
     * {@code _bump_retry_counter} which uses a plain read-modify-write.
     */
    private static int bumpRetryCounter() throws IOException {
        // Ensure the file exists before opening read-write so the first
        // call doesn't see a FileNotFoundException.
        if (!Files.exists(RETRY_COUNTER_PATH)) {
            Files.write(RETRY_COUNTER_PATH, "0".getBytes(StandardCharsets.UTF_8));
        }
        try (RandomAccessFile raf = new RandomAccessFile(RETRY_COUNTER_PATH.toFile(), "rw");
             FileChannel ch = raf.getChannel();
             FileLock ignored = ch.lock()) {
            // Read from the locked raf — Files.readAllBytes would open a
            // separate FD and bypass the lock.
            long len = raf.length();
            String body = "0";
            if (len > 0) {
                byte[] buf = new byte[(int) len];
                raf.seek(0);
                raf.readFully(buf);
                body = new String(buf, StandardCharsets.UTF_8).trim();
            }
            int n = body.isEmpty() ? 0 : Integer.parseInt(body);
            n += 1;
            raf.setLength(0);
            raf.seek(0);
            raf.write(Integer.toString(n).getBytes(StandardCharsets.UTF_8));
            return n;
        }
    }

    @MeshTool(
        capability = "report_with_transient_failures",
        task = true,
        retryOn = IOException.class,
        description = "Raises IOException on the first N attempts, succeeds on N+1 — exercises retryOn (#895)."
    )
    public Map<String, Object> reportWithTransientFailures(
            @Param("user_id") String userId,
            @Param(value = "transient_failures", required = false) Integer transientFailures,
            MeshJob job) throws IOException {
        int targetTransient = transientFailures == null ? 2 : transientFailures;
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.1, "checking transient counter");
        }
        int n = bumpRetryCounter();
        if (n <= targetTransient) {
            // Match Python's message shape so log-grep based debugging
            // is uniform across runtimes. retryOn=IOException matches
            // here -> dispatch wrapper calls releaseLease(reason).
            throw new IOException(
                "simulated transient failure " + n + "/" + targetTransient);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("succeeded_on_attempt", n);
        if (controller != null) {
            controller.complete(payload);
        }
        return payload;
    }

    // -------------------------------------------------------------------
    // Long-running task (tc06, tc09, tc10–tc13 use this via SIGKILL)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "runs_overlong",
        task = true,
        description = "Sleeps for many small intervals so cancel / kill can land mid-flight."
    )
    public Map<String, Object> runsOverlong(
            @Param("user_id") String userId,
            @Param(value = "seconds", required = false) Integer seconds,
            MeshJob job) throws InterruptedException {
        int totalSecs = seconds == null ? 30 : seconds;
        JobController controller = job instanceof JobController c ? c : null;
        double elapsed = 0.0;
        double step = 0.5;
        double total = Math.max(totalSecs, step);
        boolean cancelled = false;
        while (elapsed < total) {
            Thread.sleep((long) (step * 1000));
            elapsed += step;
            // Poll the cancel-registry state between sleeps so a
            // mid-flight POST /jobs/{id}/cancel breaks out of the loop
            // promptly. Java's Thread.sleep can't be interrupted by a
            // Tokio token firing the way Python's asyncio.sleep can,
            // so this poll IS our cancellation observation point. Once
            // observed, we skip the trailing updateProgress and the
            // complete() below — the cancel route has already flipped
            // the registry row to terminal `cancelled`, so any further
            // delta from this defunct attempt would either be rejected
            // as not_owner or stomp on the cancel marker.
            if (controller != null && controller.isCancelled()) {
                cancelled = true;
                break;
            }
            if (controller != null) {
                controller.updateProgress(
                    Math.min(elapsed / total, 0.99),
                    String.format("alive at %.1fs", elapsed));
            }
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("elapsed", elapsed);
        payload.put("cancelled", cancelled);
        if (controller != null && !cancelled) {
            controller.complete(payload);
        }
        return payload;
    }

    // -------------------------------------------------------------------
    // Job that calls a downstream regular tool (tc09)
    //
    // Parity target: uc21_meshjob/fixtures/long-task-provider/main.py's
    // report_with_downstream_call, which declares a `slow_downstream`
    // McpMeshAgent dependency on a task=true producer and awaits it.
    //
    // Wave 1 (this branch) brought Java's claim path to parity: a
    // task=true producer may now declare McpMeshTool / @Selector
    // dependencies and have them resolved + injected on the claim path
    // (the old JobsRuntimeManager.validateProducerParams rejection is
    // gone). So this fixture now mirrors Python exactly — it takes a
    // real injected McpMeshTool slow_downstream dependency and calls it
    // via the SDK's McpHttpClient proxy path rather than hand-rolling a
    // java.net.http request. Cancel propagation through that outbound
    // call is wired by #900 (McpHttpClient abort hook).
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_with_downstream_call",
        task = true,
        dependencies = @Selector(capability = "slow_downstream"),
        description = "Calls a downstream regular tool that sleeps; cancel must abort the in-flight HTTP."
    )
    public Object reportWithDownstreamCall(
            @Param("user_id") String userId,
            McpMeshTool slowDownstream,
            MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.1, "calling downstream");
        }
        if (slowDownstream == null) {
            // Mirror Python's missing-dep branch: surface the unresolved
            // dependency as an explicit terminal failure rather than
            // letting a returned error dict trip auto-complete.
            if (controller != null) {
                controller.fail("slow_downstream dependency not injected");
            }
            return null;
        }
        // The downstream tool sleeps 30s. With cancel propagation
        // working, the producer's cancel token aborts the in-flight
        // McpHttpClient request well before the 30s timer elapses.
        Object result = slowDownstream.call(
            Map.of("user_id", userId, "seconds", 30));
        if (controller != null) {
            controller.complete(result);
        }
        return result;
    }

    // -------------------------------------------------------------------
    // Event-injection scenarios (tc24/tc25/tc26 — recvEvent primitive,
    // issue #1032). Mirrors Python uc21 / TS uc22 fixtures field-for-field:
    //   - run_with_event   — happy path: wait for one 'signal' event
    //   - run_with_filter  — type-filter correctness
    //   - run_until_cancel — synthetic 'cancelled' event observation
    // All three use task=true and call job.recvEvent(...) on the injected
    // JobController. The producer's recvEvent timeout uses Duration to
    // bridge cleanly through the SDK's Optional<Duration> API.
    // -------------------------------------------------------------------

    @MeshTool(
        capability = "run_with_event",
        task = true,
        description = "Wait for one 'signal' event and return its payload — happy path for recvEvent."
    )
    public Map<String, Object> runWithEvent(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        controller.updateProgress(0.1, "parked on recvEvent");
        Map<String, Object> event = controller.recvEvent(
            List.of("signal"), Duration.ofSeconds(10));
        if (event == null) {
            Map<String, Object> timeout = new LinkedHashMap<>();
            timeout.put("status", "timeout");
            timeout.put("received", false);
            return timeout;
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", "got_event");
        payload.put("received", true);
        payload.put("type", event.get("type"));
        payload.put("payload", event.get("payload"));
        payload.put("seq", event.get("seq"));
        controller.complete(payload);
        return payload;
    }

    @MeshTool(
        capability = "run_with_filter",
        task = true,
        description = "Wait for a 'target' event and ignore other types — exercises recvEvent filter."
    )
    public Map<String, Object> runWithFilter(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        controller.updateProgress(0.1, "parked with type filter");
        // Long timeout so the consumer has slack to post 2 ignored
        // events before the matching one. A broken filter would wake
        // on the FIRST event (ignore_a) and the test would catch it.
        Map<String, Object> event = controller.recvEvent(
            List.of("target"), Duration.ofSeconds(15));
        if (event == null) {
            Map<String, Object> timeout = new LinkedHashMap<>();
            timeout.put("timeout", true);
            return timeout;
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", event.get("type"));
        payload.put("payload", event.get("payload"));
        payload.put("seq", event.get("seq"));
        controller.complete(payload);
        return payload;
    }

    @MeshTool(
        capability = "run_until_done",
        task = true,
        description = "Loop on recvEvent for 'work' events, exit on payload {final: true} — paired with subscribeEvents observer."
    )
    public Map<String, Object> runUntilDone(MeshJob job) {
        // Producer side of tc27_subscribe_events_streams_observer_pattern_java.
        // Consumes 'work' events in a loop; a caller-defined termination
        // event (a 'work' event whose payload contains {"final": true})
        // is the signal to exit gracefully and return the count of events
        // processed. The subscribeEvents observer on the consumer side
        // watches the SAME event stream independently — its cursor is
        // per-subscription, not shared with the producer's recv_event cursor.
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        List<Map<String, Object>> eventsProcessed = new ArrayList<>();
        // Bounded loop — safety net so a missing termination event
        // doesn't hang the job indefinitely. Per-iteration long timeout
        // matches the consumer's posting cadence (3 events with ~500ms
        // spacing; 10s is plenty).
        for (int i = 0; i < 20; i++) {
            Map<String, Object> event = controller.recvEvent(
                List.of("work"), Duration.ofSeconds(10));
            if (event == null) {
                Map<String, Object> timeout = new LinkedHashMap<>();
                timeout.put("status", "timeout");
                timeout.put("processed", eventsProcessed);
                return timeout;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("seq", event.get("seq"));
            entry.put("payload", event.get("payload"));
            eventsProcessed.add(entry);
            Object payloadRaw = event.get("payload");
            if (payloadRaw instanceof Map<?, ?> payloadMap
                && Boolean.TRUE.equals(payloadMap.get("final"))) {
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("status", "done");
                result.put("processed_count", eventsProcessed.size());
                result.put("events", eventsProcessed);
                controller.complete(result);
                return result;
            }
        }
        Map<String, Object> exhausted = new LinkedHashMap<>();
        exhausted.put("status", "loop_exhausted");
        exhausted.put("processed", eventsProcessed);
        return exhausted;
    }

    @MeshTool(
        capability = "run_until_cancel",
        task = true,
        description = "Loop on recvEvent for 'work'/'cancelled' types until cancelled-event arrives."
    )
    public Map<String, Object> runUntilCancel(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        List<Map<String, Object>> eventsSeen = new ArrayList<>();
        // Loop with per-iteration long timeout. A correct flow exits
        // via the "cancelled" branch within ~3s of the consumer firing
        // cancel. Bounded loop count is a safety net against runaway
        // iterations if the cancel event never lands.
        for (int i = 0; i < 20; i++) {
            Map<String, Object> event = controller.recvEvent(
                List.of("work", "cancelled"), Duration.ofSeconds(15));
            if (event == null) {
                // Surface the partial state so the test can distinguish
                // "no event ever arrived" from "wrong event type observed".
                Map<String, Object> timeoutResult = new LinkedHashMap<>();
                timeoutResult.put("status", "timeout");
                timeoutResult.put("events_seen", eventsSeen);
                return timeoutResult;
            }
            Map<String, Object> seen = new LinkedHashMap<>();
            seen.put("type", event.get("type"));
            seen.put("payload", event.get("payload"));
            eventsSeen.add(seen);
            if ("cancelled".equals(event.get("type"))) {
                // Don't call complete()/fail() — the registry row is
                // already cancelled (synthetic event posted by CancelJob
                // AFTER the row transition). The runtime's auto-complete
                // is a no-op once terminal is recorded.
                //
                // Log a marker line so the test driver can assert the
                // producer observed the synthetic cancel event WITHOUT
                // relying on proxy.wait() (raises on cancelled terminal).
                System.out.println(
                    "[run_until_cancel] cancelled_gracefully events_seen="
                        + eventsSeen);
                System.out.flush();
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("status", "cancelled_gracefully");
                result.put("events_seen", eventsSeen);
                return result;
            }
        }
        Map<String, Object> exhausted = new LinkedHashMap<>();
        exhausted.put("status", "loop_exhausted");
        exhausted.put("events_seen", eventsSeen);
        return exhausted;
    }

    // -------------------------------------------------------------------
    // input_required parking — exercises C1 lease-reclaim of
    // input_required jobs (#1229). Java port of uc21's awaits_input_forever
    // producer (uc21_meshjob/fixtures/long-task-provider/main.py).
    //
    // The injected JobController exposes requestInput(prompt) — the SDK
    // primitive (added in this branch: JNA -> C-FFI -> shared Rust core)
    // that transitions the owned job to input_required (status-only,
    // non-terminal, flushed immediately). It uses the controller's own job
    // context and lease ownership, so no registry-URL / instance-id
    // plumbing is needed.
    //
    // After signalling input_required the handler parks on recvEvent for
    // an "answer" event that never arrives, posting NO progress. Because
    // progress deltas are what extend the lease, the silent park lets the
    // lease lapse so the registry's ReclaimExpiredLeaseJobs phase (now
    // input_required-scoped) can reap it — the whole point of the C1 test.
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "awaits_input_forever",
        task = true,
        description = "Transitions the job to input_required, then parks on recvEvent for an answer that never arrives — never posts progress, never completes."
    )
    public Map<String, Object> awaitsInputForever(
            @Param("user_id") String userId,
            MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        // Transition the row to input_required via the SDK primitive (the
        // injected controller is the lease owner, so no manual owner-check
        // plumbing needed).
        controller.requestInput("waiting on input for " + userId);
        // Park waiting for an "answer" event that the consumer never posts.
        // CRITICAL: do NOT call updateProgress here — a progress delta
        // would extend the lease and defeat the lease-reclaim test.
        // recvEvent is a pure long-poll read; it does not heartbeat the
        // lease. We loop on the long-poll so the handler stays parked well
        // past the lease window; the registry reaps the row out from under
        // us via ReclaimExpiredLeaseJobs.
        for (int i = 0; i < 60; i++) {
            Map<String, Object> event = controller.recvEvent(
                List.of("answer"), Duration.ofSeconds(15));
            if (event != null) {
                // An answer arrived (not expected in the C1 test) — complete
                // so the fixture stays well-behaved if ever exercised that way.
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("status", "got_answer");
                payload.put("payload", event.get("payload"));
                controller.complete(payload);
                return payload;
            }
        }
        Map<String, Object> neverAnswered = new LinkedHashMap<>();
        neverAnswered.put("status", "never_answered");
        return neverAnswered;
    }

    // -------------------------------------------------------------------
    // Durable recvEvent cursor resume (tc31 / tc32 — issue #1277)
    // -------------------------------------------------------------------
    //
    // Java port of uc21's resume_task/replay_task and uc22's TS twins. Two
    // capabilities with the SAME body but opposite {@code resumeCursor} opt-in —
    // this is the first e2e exercise of the JNA/C-FFI binding's core resume
    // (Wave-2 unit tests bound to MOCKED controllers).
    //
    // Both loop on {@code recvEvent(["work"])}, record every processed seq to a
    // job-id-keyed sink, and emit {@code updateProgress} AFTER each event. The
    // progress delta FLUSHES the lagging durable recv_cursor to the registry
    // (the cursor rides the delta, trailing receipt by one — at-least-once). On a
    // re-claim the claim response carries the persisted recv_cursor; the Java
    // ClaimDispatcher opens the new controller via
    // {@code JobController.openWithResume(...)} when {@code resumeCursor=true},
    // so {@code recvEvent} resumes AFTER the persisted position instead of
    // replaying from seq 0.
    //
    //   - resume_task (resumeCursor=true)  — early durably-flushed events are
    //     consumed EXACTLY ONCE across both claims (resume).
    //   - replay_task (resumeCursor absent) — control: a re-claim replays from
    //     seq 0, so every pre-reclaim event is consumed a SECOND time.
    //
    // The ONLY difference is the annotation flag, so any behavioural divergence
    // the integration TCs observe is attributable to the opt-in alone. Note
    // (Java-specific): a superseded attempt-1's next recvEvent is rejected by the
    // registry (epoch fencing) and throws / returns null; because a single
    // controller's cursor is monotonic it never re-returns an early seq, so
    // attempt 1 records each early seq at most once regardless — the
    // count(seq=1)==1 resume assertion is robust to Java's blocking model.
    // -------------------------------------------------------------------

    // Single-type filter ["work"] canonicalises to the bare key "work" on the
    // registry side (jobs.rs::filter_key) — the integration gate reads
    // .recv_cursor.work.
    private static final List<String> RESUME_FILTER = List.of("work");

    private static Path resumeSinkPath(String jobId) {
        // SINGLE-REPLICA ASSUMPTION: this /tmp sink assumes the SAME provider
        // process re-claims the job after the reclaim (the suite runs one
        // provider = sole claimant, so attempt 1 and attempt 2 share a
        // filesystem). If this fixture is ever scaled to 2+ replicas the sink
        // must move to a tool-call / registry read (e.g. job progress or the
        // event log), since a reclaim could land on a different node whose
        // /tmp the driver cannot see.
        return Paths.get("/tmp/uc23-resume-processed-" + jobId);
    }

    /**
     * Append one processed-seq line. The driver counts occurrences of a given
     * seq across BOTH claims: exactly-once ⇒ resume, twice ⇒ replay-from-0.
     * Synchronized so a superseded attempt racing the resumed one can't
     * interleave a half-written line.
     */
    private static synchronized void recordProcessedSeq(String jobId, Object seq) {
        try {
            Files.write(
                resumeSinkPath(jobId),
                ("seq=" + seq + "\n").getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException e) {
            throw new RuntimeException("failed to record processed seq", e);
        }
    }

    private static Map<String, Object> consumeWorkLoop(JobController controller) {
        List<Object> processed = new ArrayList<>();
        // Bounded loop (safety net). 60 rounds * 3s = 180s park ceiling — longer
        // than the reclaim window, shorter than the TC timeout so a wedged run
        // fails loudly. A superseded attempt's next recvEvent is rejected
        // claim_superseded and throws / returns null; we record NOTHING on that
        // path (recvEvent returns no event), so a superseded attempt contributes
        // no spurious seqs.
        for (int i = 0; i < 60; i++) {
            Map<String, Object> event = controller.recvEvent(
                RESUME_FILTER, Duration.ofSeconds(3));
            if (event == null) {
                // No work yet — keep parking across the reclaim boundary.
                continue;
            }
            Object seq = event.get("seq");
            recordProcessedSeq(controller.jobId(), seq);
            processed.add(seq);
            // Flush the lagging durable cursor by emitting a progress delta
            // AFTER processing — the persistence step under test.
            double prog = seq instanceof Number nseq
                ? Math.min(nseq.doubleValue() / 10.0, 0.99) : 0.5;
            controller.updateProgress(prog, "processed seq=" + seq);
            Object payloadRaw = event.get("payload");
            if (payloadRaw instanceof Map<?, ?> payloadMap
                && Boolean.TRUE.equals(payloadMap.get("final"))) {
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("status", "done");
                result.put("processed", processed);
                controller.complete(result);
                return result;
            }
        }
        Map<String, Object> exhausted = new LinkedHashMap<>();
        exhausted.put("status", "loop_exhausted");
        exhausted.put("processed", processed);
        return exhausted;
    }

    @MeshTool(
        capability = "resume_task",
        task = true,
        resumeCursor = true,
        description = "Consume 'work' events; on re-claim RESUMES after the persisted recvEvent cursor (issue #1277 opt-in ON)."
    )
    public Map<String, Object> resumeTask(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        return consumeWorkLoop(controller);
    }

    @MeshTool(
        capability = "replay_task",
        task = true,
        // resumeCursor defaults false — the control: a re-claim replays from seq 0.
        description = "Consume 'work' events; on re-claim REPLAYS from seq 0 (issue #1277 opt-in OFF — control)."
    )
    public Map<String, Object> replayTask(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            Map<String, Object> noJob = new LinkedHashMap<>();
            noJob.put("status", "no_job_ctx");
            return noJob;
        }
        return consumeWorkLoop(controller);
    }
}
