package com.example.longtaskconsumer;

import io.mcpmesh.EventSubscription;
import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.MeshJobs;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.SubscribeOptions;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob test-suite consumer (uc23_meshjob_java) — Java port of
 * uc21_meshjob/fixtures/long-task-consumer/main.py and
 * uc22_meshjob_ts/fixtures/long-task-consumer-ts.
 *
 * <p>Hosts several variants of the submit-and-await pattern so
 * individual test cases can exercise behavioural knobs without forking
 * new agents. Capability names match the Python and TypeScript fixtures
 * exactly so the polyglot tests (tc17–tc22) can call them
 * interchangeably across runtimes.
 *
 * <h2>Wrappers</h2>
 * <ul>
 *   <li>{@code commission_report}        — submit + wait; returns terminal payload</li>
 *   <li>{@code commission_with_options}  — submit + wait with caller-supplied
 *                                          max_retries + total_deadline_secs</li>
 *   <li>{@code commission_submit_only}   — submit and return job_id immediately</li>
 *   <li>{@code commission_explicit_fail} — submits report_with_explicit_fail</li>
 *   <li>{@code commission_crash}          — submits report_that_crashes</li>
 *   <li>{@code commission_overlong}       — submits runs_overlong</li>
 *   <li>{@code commission_downstream}     — submits report_with_downstream_call</li>
 * </ul>
 */
@MeshAgent(
    name = "long-task-consumer-java",
    version = "1.0.0",
    description = "MeshJob test consumer (uc23 Java) — multi-capability fixture for the integration suite.",
    port = 9121
)
@SpringBootApplication
public class LongTaskConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(LongTaskConsumerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(LongTaskConsumerApplication.class, args);
    }

    /**
     * Convert relative seconds to a unix-epoch deadline. Returns null
     * when the input is null (≡ "no deadline").
     */
    private static Long utcDeadlineFromRelative(Integer secs) {
        if (secs == null) {
            return null;
        }
        return (System.currentTimeMillis() / 1000L) + secs;
    }

    // -------------------------------------------------------------------
    // Submit + wait — happy path baseline (tc01)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_report",
        description = "Submit a generate_report job and wait up to 60s for the result.",
        dependencies = @Selector(capability = "generate_report")
    )
    @SuppressWarnings("unchecked")
    public Map<String, Object> commissionReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob generateReport) throws Exception {
        if (!(generateReport instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "generate_report submitter not injected");
            return err;
        }
        if (sections == null) {
            sections = List.of("intro", "analysis", "summary");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("sections", sections);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 60, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            Object result = proxy.await(60.0);
            if (result instanceof Map<?, ?> m) {
                return (Map<String, Object>) m;
            }
            Map<String, Object> wrapped = new LinkedHashMap<>();
            wrapped.put("result", result);
            return wrapped;
        }
    }

    // -------------------------------------------------------------------
    // Submit + wait with caller-controlled retry / deadline knobs (tc13)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_with_options",
        description = "Submit generate_report with caller-supplied max_retries / total_deadline_secs.",
        dependencies = @Selector(capability = "generate_report")
    )
    public Map<String, Object> commissionWithOptions(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            @Param(value = "max_retries", required = false) Integer maxRetries,
            @Param(value = "total_deadline_secs", required = false) Integer totalDeadlineSecs,
            @Param(value = "wait_timeout_secs", required = false) Integer waitTimeoutSecs,
            MeshJob generateReport) {
        if (!(generateReport instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "generate_report submitter not injected");
            return err;
        }
        if (sections == null) {
            sections = List.of("intro", "analysis", "summary");
        }
        int retries = maxRetries == null ? 1 : maxRetries;
        int waitSecs = waitTimeoutSecs == null ? 60 : waitTimeoutSecs;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("sections", sections);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 60, retries, utcDeadlineFromRelative(totalDeadlineSecs));

        String jobId;
        try (JobProxy proxy = submitter.submit(opts).get()) {
            jobId = proxy.jobId();
            try {
                Object result = proxy.await((double) waitSecs);
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "completed");
                envelope.put("result", result);
                return envelope;
            } catch (Exception e) {
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "wait_raised");
                envelope.put("error", e.getMessage());
                return envelope;
            }
        } catch (Exception e) {
            Map<String, Object> envelope = new LinkedHashMap<>();
            envelope.put("job_id", null);
            envelope.put("status", "submit_raised");
            envelope.put("error", e.getMessage());
            return envelope;
        }
    }

    // -------------------------------------------------------------------
    // Submit-only — return job_id immediately (tc02, tc06, tc10–tc12, tc14, tc16)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_submit_only",
        description = "Submit generate_report and return the job_id without waiting.",
        dependencies = @Selector(capability = "generate_report")
    )
    public Map<String, Object> commissionSubmitOnly(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            @Param(value = "max_retries", required = false) Integer maxRetries,
            @Param(value = "max_duration", required = false) Integer maxDuration,
            MeshJob generateReport) throws Exception {
        if (!(generateReport instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "generate_report submitter not injected");
            return err;
        }
        if (sections == null) {
            sections = List.of("default");
        }
        int retries = maxRetries == null ? 1 : maxRetries;
        int duration = maxDuration == null ? 60 : maxDuration;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("sections", sections);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, duration, retries, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", proxy.jobId());
            return response;
        }
    }

    // -------------------------------------------------------------------
    // Explicit-fail submitter (tc05)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_explicit_fail",
        description = "Submit report_with_explicit_fail with caller-supplied max_retries.",
        dependencies = @Selector(capability = "report_with_explicit_fail")
    )
    public Map<String, Object> commissionExplicitFail(
            @Param("user_id") String userId,
            @Param(value = "max_retries", required = false) Integer maxRetries,
            @Param(value = "wait_timeout_secs", required = false) Integer waitTimeoutSecs,
            MeshJob reportWithExplicitFail) {
        if (!(reportWithExplicitFail instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "report_with_explicit_fail submitter not injected");
            return err;
        }
        int retries = maxRetries == null ? 3 : maxRetries;
        int waitSecs = waitTimeoutSecs == null ? 30 : waitTimeoutSecs;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 30, retries, null);

        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();
            try {
                Object result = proxy.await((double) waitSecs);
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "completed");
                envelope.put("result", result);
                return envelope;
            } catch (Exception e) {
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "wait_raised");
                envelope.put("error", e.getMessage());
                return envelope;
            }
        } catch (Exception e) {
            Map<String, Object> envelope = new LinkedHashMap<>();
            envelope.put("job_id", null);
            envelope.put("status", "submit_raised");
            envelope.put("error", e.getMessage());
            return envelope;
        }
    }

    // -------------------------------------------------------------------
    // Crash submitter (tc12)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_crash",
        description = "Submit report_that_crashes (always raises) with caller-supplied retry/deadline.",
        dependencies = @Selector(capability = "report_that_crashes")
    )
    public Map<String, Object> commissionCrash(
            @Param("user_id") String userId,
            @Param(value = "max_retries", required = false) Integer maxRetries,
            @Param(value = "total_deadline_secs", required = false) Integer totalDeadlineSecs,
            MeshJob reportThatCrashes) throws Exception {
        if (!(reportThatCrashes instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "report_that_crashes submitter not injected");
            return err;
        }
        int retries = maxRetries == null ? 0 : maxRetries;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 30, retries, utcDeadlineFromRelative(totalDeadlineSecs));
        try (JobProxy proxy = submitter.submit(opts).get()) {
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", proxy.jobId());
            return response;
        }
    }

    // -------------------------------------------------------------------
    // Transient-failures submitter (tc23 — exercises @MeshTool(retryOn=...))
    // -------------------------------------------------------------------
    //
    // Mirrors Python's commission_transient_failures
    // (uc21_meshjob/fixtures/long-task-consumer/main.py). Submits a
    // report_with_transient_failures job with caller-supplied max_retries
    // and waits for terminal — the captured payload exposes
    // succeeded_on_attempt so the test asserts attempt_count == 3.
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_transient_failures",
        description = "Submit report_with_transient_failures with caller-supplied max_retries.",
        dependencies = @Selector(capability = "report_with_transient_failures")
    )
    public Map<String, Object> commissionTransientFailures(
            @Param("user_id") String userId,
            @Param(value = "max_retries", required = false) Integer maxRetries,
            @Param(value = "transient_failures", required = false) Integer transientFailures,
            @Param(value = "wait_timeout_secs", required = false) Integer waitTimeoutSecs,
            MeshJob reportWithTransientFailures) {
        if (!(reportWithTransientFailures instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "report_with_transient_failures submitter not injected");
            return err;
        }
        int retries = maxRetries == null ? 3 : maxRetries;
        int targetTransient = transientFailures == null ? 2 : transientFailures;
        int waitSecs = waitTimeoutSecs == null ? 30 : waitTimeoutSecs;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("transient_failures", targetTransient);
        // max_duration=30s mirrors Python — keeps the per-attempt budget
        // tight so a slow-path lease-expiry recovery would push past the
        // 30s wall-clock guard the test asserts.
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 30, retries, null);

        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();
            try {
                Object result = proxy.await((double) waitSecs);
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "completed");
                envelope.put("result", result);
                return envelope;
            } catch (Exception e) {
                Map<String, Object> envelope = new LinkedHashMap<>();
                envelope.put("job_id", jobId);
                envelope.put("status", "wait_raised");
                envelope.put("error", e.getMessage());
                return envelope;
            }
        } catch (Exception e) {
            Map<String, Object> envelope = new LinkedHashMap<>();
            envelope.put("job_id", null);
            envelope.put("status", "submit_raised");
            envelope.put("error", e.getMessage());
            return envelope;
        }
    }

    // -------------------------------------------------------------------
    // Overlong submitter (tc06, tc20)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_overlong",
        description = "Submit runs_overlong and return the job_id (no wait).",
        dependencies = @Selector(capability = "runs_overlong")
    )
    public Map<String, Object> commissionOverlong(
            @Param("user_id") String userId,
            @Param(value = "seconds", required = false) Integer seconds,
            MeshJob runsOverlong) throws Exception {
        if (!(runsOverlong instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "runs_overlong submitter not injected");
            return err;
        }
        int secs = seconds == null ? 30 : seconds;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("seconds", secs);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 120, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", proxy.jobId());
            return response;
        }
    }

    // -------------------------------------------------------------------
    // Event-injection submitters (tc24 / tc25 / tc26 — issue #1032)
    // -------------------------------------------------------------------
    //
    // Each capability submits one of the new task=true producers and
    // drives MeshJobs.postEvent from inside the consumer's tool body
    // to exercise the producer's recvEvent long-poll. The static helper
    // MeshJobs.postEvent discovers the registry URL from
    // MCP_MESH_REGISTRY_URL (set by the agent startup pipeline) and
    // POSTs /jobs/{id}/events.
    // -------------------------------------------------------------------

    @MeshTool(
        capability = "commission_event",
        description = "Submit run_with_event, sleep so producer parks on recvEvent, then post one event.",
        dependencies = @Selector(capability = "run_with_event")
    )
    public Map<String, Object> commissionEvent(MeshJob runWithEvent) throws Exception {
        if (!(runWithEvent instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "run_with_event submitter not injected");
            return err;
        }
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            new LinkedHashMap<>(), null, 60, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();
            // Brief wait so producer reaches recvEvent before we post.
            // Without this, the post may land before the producer's
            // claim worker has even pulled the job off the queue.
            Thread.sleep(2000);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("hello", "world");
            payload.put("n", 42);
            Map<String, Object> receipt = MeshJobs.postEvent(jobId, "signal", payload);
            Object result = proxy.await(30.0);
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", jobId);
            response.put("post_seq", receipt.get("seq"));
            response.put("job_result", result);
            return response;
        }
    }

    @MeshTool(
        capability = "commission_event_filter",
        description = "Submit run_with_filter, post 2 ignored events, then the matching one.",
        dependencies = @Selector(capability = "run_with_filter")
    )
    public Map<String, Object> commissionEventFilter(MeshJob runWithFilter) throws Exception {
        if (!(runWithFilter instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "run_with_filter submitter not injected");
            return err;
        }
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            new LinkedHashMap<>(), null, 60, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();
            Thread.sleep(2000);
            // Post 2 unrelated events — producer must NOT wake on these.
            Map<String, Object> p1 = new LinkedHashMap<>();
            p1.put("n", 1);
            Map<String, Object> r1 = MeshJobs.postEvent(jobId, "ignore_a", p1);
            Map<String, Object> p2 = new LinkedHashMap<>();
            p2.put("n", 2);
            Map<String, Object> r2 = MeshJobs.postEvent(jobId, "ignore_b", p2);
            // Brief gap so a buggy filter (one that DID wake on ignore_a)
            // has time to drive the producer to completion; if the producer
            // is already done by now, the matching post will get
            // JobTerminalException.
            Thread.sleep(1000);
            Map<String, Object> p3 = new LinkedHashMap<>();
            p3.put("got_it", true);
            Map<String, Object> r3 = MeshJobs.postEvent(jobId, "target", p3);
            Object result = proxy.await(30.0);
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", jobId);
            response.put("ignore_seqs", List.of(r1.get("seq"), r2.get("seq")));
            response.put("target_seq", r3.get("seq"));
            response.put("result", result);
            return response;
        }
    }

    /**
     * Tc27 driver — submit a {@code run_until_done} job, fire 3 'work'
     * events concurrently with a {@link MeshJobs#subscribeEvents}
     * subscriber, and return a structured report so the integration
     * assertions can pin all three observers (producer, subscriber,
     * posters) agree on the event count and ordering.
     *
     * <p>Mirror of Python's {@code commission_subscribe_observer}
     * (uc21_meshjob/tc27). Java threading uses a daemon Thread + a
     * synchronized observed-events list instead of asyncio tasks; the
     * subscriber breaks on {@code payload.final == true}. A 15s join
     * timeout bounds the subscriber wait — on timeout we close the
     * subscription (drops the FFI long-poll's strong reference) and
     * report {@code subscriber_status = "timeout"}.
     */
    @MeshTool(
        capability = "commission_subscribe_observer",
        description = "Submit run_until_done, concurrently post 'work' events and subscribe — verifies observer pattern.",
        dependencies = @Selector(capability = "run_until_done")
    )
    public Map<String, Object> commissionSubscribeObserver(MeshJob runUntilDone) throws Exception {
        if (!(runUntilDone instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "run_until_done submitter not injected");
            return err;
        }
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            new LinkedHashMap<>(), null, 60, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();

            // Brief wait so producer claims the job + parks on
            // recvEvent before we post anything. Without this the
            // first 'work' event could land before the producer's
            // claim worker has pulled the row off the queue — the
            // event would still be observable but we wouldn't be
            // exercising the long-poll wake path.
            Thread.sleep(2000);

            // Synchronized list so the subscriber thread and the main
            // thread can both touch it safely. The subscriber writes;
            // the main thread reads after the join.
            List<Map<String, Object>> observedEvents = Collections.synchronizedList(new ArrayList<>());

            // Subscriber thread: walks the EventSubscription iterator,
            // collecting events into observedEvents, and breaks on the
            // 'final: true' payload marker. Mirrors Python's
            // _subscriber asyncio task. Wrapped in try-with-resources
            // so the subscription is always closed — even if the
            // poster loop throws InterruptedException or postEvent
            // raises.
            String subscriberStatus;
            List<Object> postedSeqs = new ArrayList<>();
            try (EventSubscription subscription = MeshJobs.subscribeEvents(
                    jobId,
                    SubscribeOptions.builder()
                        .types(List.of("work"))
                        .longPoll(Duration.ofSeconds(5))
                        .build())) {
                Thread subscriberThread = new Thread(() -> {
                    try {
                        while (subscription.hasNext()) {
                            Map<String, Object> event = subscription.next();
                            Map<String, Object> entry = new LinkedHashMap<>();
                            entry.put("seq", event.get("seq"));
                            entry.put("payload", event.get("payload"));
                            observedEvents.add(entry);
                            Object payloadRaw = event.get("payload");
                            if (payloadRaw instanceof Map<?, ?> payloadMap
                                && Boolean.TRUE.equals(payloadMap.get("final"))) {
                                return;
                            }
                        }
                    } catch (RuntimeException ex) {
                        // Subscriber-side error (e.g. JobNotFoundException
                        // if the job was reaped). Surface via the empty
                        // observed_events list — the assertions tolerate
                        // partial state — but log so test triage isn't
                        // blind when the exception is unexpected.
                        log.warn("tc27 subscriber thread caught exception (job_id={}): {}",
                            jobId, ex.toString(), ex);
                    }
                }, "tc27-subscriber");
                subscriberThread.setDaemon(true);
                subscriberThread.start();

                // Poster: fire 3 'work' events with ~500ms spacing; the
                // 3rd carries final=true to terminate the producer AND
                // the subscriber.
                List<Map<String, Object>> payloads = List.of(
                    Map.of("item", 1),
                    Map.of("item", 2),
                    Map.of("item", 3, "final", true));
                for (Map<String, Object> payload : payloads) {
                    Thread.sleep(500);
                    Map<String, Object> receipt = MeshJobs.postEvent(
                        jobId, "work", new LinkedHashMap<>(payload));
                    postedSeqs.add(receipt.get("seq"));
                }

                // Bound the subscriber wait — 15s is well above the
                // expected runtime (3 events * 500ms post-spacing + handler
                // overhead). On timeout the try-with-resources close()
                // drops the iterator's "keep polling" flag; the next
                // hasNext() in the subscriber thread will return false.
                // The thread may still be blocked on a long-poll — that's
                // fine, the daemon thread reclaims itself.
                subscriberThread.join(15_000L);
                subscriberStatus = subscriberThread.isAlive() ? "timeout" : "ok";
            }

            Object jobResult;
            try {
                jobResult = proxy.await(30.0);
            } catch (RuntimeException e) {
                jobResult = Map.of("error", e.getMessage());
            }

            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", jobId);
            response.put("posted_seqs", postedSeqs);
            response.put("subscriber_status", subscriberStatus);
            response.put("observed_count", observedEvents.size());
            response.put("observed_events", new ArrayList<>(observedEvents));
            response.put("job_result", jobResult);
            return response;
        }
    }

    @MeshTool(
        capability = "commission_cancel_via_event",
        description = "Submit run_until_cancel, post 'work', then cancel — synthetic 'cancelled' event must arrive.",
        dependencies = @Selector(capability = "run_until_cancel")
    )
    public Map<String, Object> commissionCancelViaEvent(MeshJob runUntilCancel) throws Exception {
        if (!(runUntilCancel instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "run_until_cancel submitter not injected");
            return err;
        }
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            new LinkedHashMap<>(), null, 60, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();
            Thread.sleep(2000);
            Map<String, Object> workPayload = new LinkedHashMap<>();
            workPayload.put("item", 1);
            Map<String, Object> workReceipt = MeshJobs.postEvent(jobId, "work", workPayload);
            // Give producer a moment to consume the 'work' event before
            // firing cancel — makes the events strictly ordered in
            // events_seen (work first, cancelled second).
            Thread.sleep(1000);
            proxy.cancel("external_stop_requested");
            // The job is now cancelled — producer's recvEvent loop will
            // observe the synthetic 'cancelled' event and return its
            // dict via the normal task return path. We CANNOT use
            // proxy.await() because wait() raises on cancelled terminal.
            // Poll for terminal status with deadline (was fixed 3s sleep);
            // gives headroom on slow cancels and exits fast on quick ones.
            long deadline = System.currentTimeMillis() + 8_000L;
            Map<String, Object> status = proxy.status();
            while (System.currentTimeMillis() < deadline) {
                String s = status != null ? (String) status.get("status") : null;
                if (s != null && (s.equals("completed") || s.equals("failed") || s.equals("cancelled"))) {
                    break;
                }
                Thread.sleep(300);
                status = proxy.status();
            }
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", jobId);
            response.put("work_seq", workReceipt.get("seq"));
            response.put("terminal_status", status.get("status"));
            response.put("terminal_error", status.get("error"));
            return response;
        }
    }

    // -------------------------------------------------------------------
    // Downstream-call submitter (tc09)
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "commission_downstream",
        description = "Submit report_with_downstream_call (provider calls slow_downstream) and return job_id.",
        dependencies = @Selector(capability = "report_with_downstream_call")
    )
    public Map<String, Object> commissionDownstream(
            @Param("user_id") String userId,
            MeshJob reportWithDownstreamCall) throws Exception {
        if (!(reportWithDownstreamCall instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "report_with_downstream_call submitter not injected");
            return err;
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload, null, 120, null, null);
        try (JobProxy proxy = submitter.submit(opts).get()) {
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", proxy.jobId());
            return response;
        }
    }
}
