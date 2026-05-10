package com.example.reportconsumersse;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AStream;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A2A consumer example (issue #910 / Phase 3, SSE variant) — Java
 * port of {@code examples/a2a/consumer_report_agent_sse.py}.
 *
 * <p>Same end-to-end shape as
 * {@code com.example.reportconsumer.ReportConsumerAgentApplication}
 * but uses {@link A2AClient#subscribe} (SSE) instead of poll-based
 * {@link A2AClient#submit} + {@link io.mcpmesh.a2a.A2AJob#bridge}.
 *
 * <h2>Cancel propagation note</h2>
 *
 * Per A2A v1.0, client disconnect is a transient signal — the
 * producer continues running unless explicitly canceled.
 * {@link A2AStream#bridge} therefore does NOT POST
 * {@code tasks/cancel} upstream when the mesh-side job is cancelled
 * (it just closes the SSE connection). Users who need cancel
 * propagation should use the polling
 * {@code ReportConsumerAgentApplication} (which polls
 * {@link JobController#isCancelled()} between iterations and POSTs
 * {@code tasks/cancel}).
 */
@MeshAgent(
    name = "report-consumer-sse",
    version = "1.0.0",
    description = "Java A2A consumer (SSE) — bridges the report_a2a_agent.py generate-report skill as a mesh ``report-sse`` capability.",
    port = 9212
)
@SpringBootApplication
public class ReportConsumerSseAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ReportConsumerSseAgentApplication.class);

    private static final A2AClient A2A_CLIENT = new A2AClient(
        "http://localhost:9091/agents/report",
        "generate-report"
    );

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        log.info("Starting Java A2A Consumer (report-consumer-sse, SSE bridge)...");
        SpringApplication.run(ReportConsumerSseAgentApplication.class, args);
    }

    /**
     * Bridge the upstream A2A {@code generate-report} skill onto the
     * mesh as the {@code report-sse} capability via
     * {@code tasks/sendSubscribe}. The {@link A2AStream} returned by
     * {@link A2AClient#subscribe} is closed automatically by
     * {@link A2AStream#bridge} on completion (or any terminal failure).
     */
    @MeshTool(
        // Underscore form (report_sse) matches the existing Python
        // caller-agent-report fixture's report_sse dependency name —
        // makes the Java example a drop-in replacement for the Python
        // consumer_report_agent_sse.py without re-wiring downstream
        // callers.
        capability = "report_sse",
        task = true,
        description = "Bridge upstream A2A generate-report skill via SSE as a mesh ``report_sse`` capability.",
        tags = {"a2a-bridge", "sse"}
    )
    @A2AConsumer
    public Object generateReportSse(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob job) throws Exception {
        if (sections == null || sections.isEmpty()) {
            sections = List.of("default");
        }
        Map<String, Object> message = buildMessage(userId, sections);
        if (!(job instanceof JobController controller)) {
            // Fast-path tools/call (no X-Mesh-Job-Id header) — drain
            // the stream into a no-op controller surrogate so we still
            // return the artifact text. The polling consumer falls back
            // to A2AClient.send() here; the SSE variant has no direct
            // equivalent so we drain the stream and toss progress.
            return drainSyncFallback(message);
        }
        try (A2AStream stream = A2A_CLIENT.subscribe(message)) {
            return stream.bridge(controller);
        }
    }

    private Object drainSyncFallback(Map<String, Object> message) throws Exception {
        // Synchronous tools/call path — no JobController to mirror to,
        // so just iterate the stream and return the first artifact's
        // parsed payload (or the raw text if it isn't JSON).
        try (A2AStream stream = A2A_CLIENT.subscribe(message)) {
            for (var event : stream) {
                if (event.kind() == io.mcpmesh.a2a.A2AEvent.Kind.ARTIFACT) {
                    String text = event.artifactText();
                    if (text == null || text.isEmpty()) {
                        continue;     // skip empty/null, look for the next artifact
                    }
                    try {
                        return JSON.readValue(text, Object.class);
                    } catch (Exception parseExc) {
                        return text;
                    }
                }
            }
        }
        return "";
    }

    private static Map<String, Object> buildMessage(String userId, List<String> sections) throws Exception {
        Map<String, Object> argsPayload = new LinkedHashMap<>();
        argsPayload.put("user_id", userId);
        argsPayload.put("sections", sections);
        return Map.of(
            "role", "user",
            "parts", List.of(Map.of(
                "type", "text",
                "text", JSON.writeValueAsString(argsPayload)))
        );
    }

    @PreDestroy
    void releaseA2AClient() {
        try {
            A2A_CLIENT.close();
        } catch (Exception e) {
            log.warn("Failed to close A2AClient during shutdown", e);
        }
    }
}
