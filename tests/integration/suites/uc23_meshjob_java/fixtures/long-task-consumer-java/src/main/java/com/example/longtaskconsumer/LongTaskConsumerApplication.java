package com.example.longtaskconsumer;

import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

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
