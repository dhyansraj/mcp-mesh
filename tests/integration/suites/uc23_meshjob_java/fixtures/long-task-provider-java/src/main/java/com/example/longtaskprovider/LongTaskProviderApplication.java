package com.example.longtaskprovider;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
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
        while (elapsed < total) {
            Thread.sleep((long) (step * 1000));
            elapsed += step;
            if (controller != null) {
                controller.updateProgress(
                    Math.min(elapsed / total, 0.99),
                    String.format("alive at %.1fs", elapsed));
            }
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("elapsed", elapsed);
        if (controller != null) {
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
            String body = agentsResp.body();
            String endpointMarker = "\"endpoint\":\"";
            String slowDownstreamMarker = "\"name\":\"downstream-sleeper-java\"";
            int nameIdx = body.indexOf(slowDownstreamMarker);
            if (nameIdx < 0) {
                // Try the polyglot variants if the Java sleeper isn't here.
                slowDownstreamMarker = "\"name\":\"downstream-sleeper\"";
                nameIdx = body.indexOf(slowDownstreamMarker);
            }
            if (nameIdx < 0) {
                slowDownstreamMarker = "\"name\":\"downstream-sleeper-ts\"";
                nameIdx = body.indexOf(slowDownstreamMarker);
            }
            if (nameIdx < 0) {
                if (controller != null) {
                    controller.fail("slow_downstream provider not registered");
                }
                return null;
            }
            // Walk back from the name to the enclosing endpoint field.
            int endpointStart = body.indexOf(endpointMarker, Math.max(0, nameIdx - 800));
            if (endpointStart < 0 || endpointStart > nameIdx) {
                if (controller != null) {
                    controller.fail("could not parse slow_downstream endpoint");
                }
                return null;
            }
            int valStart = endpointStart + endpointMarker.length();
            int valEnd = body.indexOf("\"", valStart);
            String agentEndpoint = body.substring(valStart, valEnd); // http://10.x.y.z:9122

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
        } catch (IOException | InterruptedException e) {
            if (controller != null) {
                controller.fail("downstream call failed: " + e.getMessage());
            }
            Thread.currentThread().interrupt();
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
        String mcpBody = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\","
            + "\"params\":{\"name\":\"" + toolName + "\",\"arguments\":"
            + "{\"user_id\":\"" + userId + "\",\"seconds\":30}}}";
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(agentEndpoint + "/mcp"))
            .timeout(Duration.ofSeconds(60))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(mcpBody))
            .build();
        return client.send(req, HttpResponse.BodyHandlers.ofString());
    }
}
