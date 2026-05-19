package com.example.longtaskprovider;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
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
 *   <li>{@code report_with_downstream_call}    — calls slow_downstream regular tool</li>
 * </ul>
 *
 * <h2>Cancel limitation (#889)</h2>
 *
 * <p>Java's sync JNR-FFI bindings cannot bind the per-job cancel
 * registry (would require a nested Tokio runtime which Tokio rejects).
 * Tests that exercise mid-flight cancellation (tc06, tc09, tc22)
 * therefore assert only the registry-side correctness — the row's
 * {@code status} field flips to {@code cancelled} via the registry's
 * route + sweep — but the producer's task body does NOT abort
 * mid-flight; the loop runs to natural completion or until orphaned by
 * the sweep. See {@code MeshToolWrapper.dispatchAsJob} javadoc.
 */
@MeshAgent(
    name = "long-task-provider-java",
    version = "1.0.0",
    description = "MeshJob test producer (uc23 Java) — multi-capability fixture for the integration suite.",
    port = 9120
)
@SpringBootApplication
public class LongTaskProviderApplication {

    private static final ObjectMapper MAPPER = new ObjectMapper();

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
    // NOTE: Java's JobsRuntimeManager rejects task=true methods with
    // McpMeshTool / @Selector dependencies (see exception in
    // JobsRuntimeManager.validateProducerParams) — the claim path
    // doesn't resolve those for task tools. Python and TS allow it.
    // We work around by issuing the downstream HTTP call DIRECTLY via
    // the mesh registry's proxy (registry forwards /proxy/{ip}:{port}
    // to the agent's /mcp endpoint), exercising the same outbound HTTP
    // path that the McpMeshTool wrapper would use, just minus the
    // resolution layer. From the substrate's POV the cancel-propagation
    // surface is identical (both go through the JVM's HTTP client).
    // -------------------------------------------------------------------
    @MeshTool(
        capability = "report_with_downstream_call",
        task = true,
        description = "Calls a downstream regular tool that sleeps; cancel must abort the in-flight HTTP."
    )
    public Object reportWithDownstreamCall(
            @Param("user_id") String userId,
            MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.1, "calling downstream");
        }
        // Resolve the downstream agent via the registry's /agents API
        // and call its /mcp endpoint directly. The registry proxy URL
        // shape is /proxy/{host}:{port}/mcp.
        String registryUrl = System.getenv().getOrDefault(
            "MCP_MESH_REGISTRY_URL", "http://localhost:8000");
        try {
            HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();

            // Discover the slow_downstream provider's instance.
            HttpRequest agentsReq = HttpRequest.newBuilder()
                .uri(URI.create(registryUrl + "/agents"))
                .timeout(Duration.ofSeconds(5))
                .GET()
                .build();
            HttpResponse<String> agentsResp = client.send(
                agentsReq, HttpResponse.BodyHandlers.ofString());
            // Parse the /agents response with Jackson — string-based
            // indexOf scanning was brittle once the JSON object grew
            // past the lookback window or agent ordering shifted, and
            // could attribute the wrong endpoint to the matched name.
            String agentEndpoint = null;
            for (String candidate : List.of(
                    "downstream-sleeper-java",
                    "downstream-sleeper",
                    "downstream-sleeper-ts")) {
                agentEndpoint = findEndpointForAgentName(agentsResp.body(), candidate);
                if (agentEndpoint != null) break;
            }
            if (agentEndpoint == null) {
                if (controller != null) {
                    controller.fail("slow_downstream provider not registered");
                }
                return null;
            }

            // Call /mcp on that endpoint with a tools/call request.
            //
            // MCP tool name registration differs across runtimes:
            //   - Python: capability == tool name (snake_case)
            //   - TS:     capability == tool name (snake_case)
            //   - Java:   tool name == @MeshTool method name (camelCase)
            //
            // To survive any of those, try the snake_case shape first
            // (matches Python/TS), and if the agent reports "Unknown
            // tool" / "Tool not found", retry with camelCase. This
            // makes the provider portable across uc21/uc22/uc23
            // sleepers without baking in the choice.
            HttpResponse<String> callResp = invokeDownstream(
                client, agentEndpoint, "slow_downstream", userId);
            String respBody = callResp.body();
            if (callResp.statusCode() == 200
                && (respBody.contains("Unknown tool") || respBody.contains("Tool not found"))) {
                // Java sleeper — retry with camelCase method name.
                callResp = invokeDownstream(
                    client, agentEndpoint, "slowDownstream", userId);
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("status_code", callResp.statusCode());
            result.put("body", callResp.body());
            if (controller != null) {
                controller.complete(result);
            }
            return result;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (controller != null) {
                controller.fail("downstream call failed: " + e.getMessage());
            }
            return null;
        } catch (IOException e) {
            if (controller != null) {
                controller.fail("downstream call failed: " + e.getMessage());
            }
            return null;
        }
    }

    /**
     * Issue a tools/call POST to the given agent endpoint with the
     * specified tool name. Used by reportWithDownstreamCall to call
     * slow_downstream / slowDownstream regardless of the downstream
     * runtime's tool-naming convention.
     */
    private static HttpResponse<String> invokeDownstream(
            HttpClient client,
            String agentEndpoint,
            String toolName,
            String userId) throws IOException, InterruptedException {
        // Build the JSON-RPC body via Jackson rather than string concat
        // so the embedded user_id / tool name get properly escaped if
        // they ever contain a quote, backslash, or control char.
        ObjectNode root = MAPPER.createObjectNode();
        root.put("jsonrpc", "2.0");
        root.put("id", 1);
        root.put("method", "tools/call");
        ObjectNode params = root.putObject("params");
        params.put("name", toolName);
        ObjectNode args = params.putObject("arguments");
        args.put("user_id", userId);
        args.put("seconds", 30);
        String mcpBody = MAPPER.writeValueAsString(root);
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(agentEndpoint + "/mcp"))
            .timeout(Duration.ofSeconds(60))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(mcpBody))
            .build();
        return client.send(req, HttpResponse.BodyHandlers.ofString());
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

    /**
     * Find the {@code endpoint} field for the named agent in a
     * registry {@code GET /agents} response body. Returns {@code null}
     * if the agent isn't present or the response shape doesn't match.
     *
     * <p>Replaces an earlier indexOf-based scanner that could land on
     * the wrong agent's endpoint when the JSON exceeded an 800-char
     * lookback window or agent ordering shifted between requests.
     */
    private static String findEndpointForAgentName(String body, String agentName) {
        try {
            JsonNode root = MAPPER.readTree(body);
            JsonNode agents = root.has("agents") ? root.get("agents") : root;
            if (agents == null || !agents.isArray()) return null;
            for (JsonNode agent : agents) {
                JsonNode name = agent.get("name");
                if (name != null && agentName.equals(name.asText())) {
                    JsonNode endpoint = agent.get("endpoint");
                    return endpoint != null && !endpoint.isNull() ? endpoint.asText() : null;
                }
            }
            return null;
        } catch (RuntimeException e) {
            // Jackson 3.x throws unchecked JacksonException — return
            // null so the caller falls through to controller.fail().
            return null;
        }
    }
}
