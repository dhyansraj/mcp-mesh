package com.example.reportconsumerjavasse;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AEvent;
import io.mcpmesh.a2a.A2AStream;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * uc27 Phase 3 fixture, SSE variant (refactored under #923) — Java
 * A2A SSE consumer that bridges {@code report_a2a_agent.py}'s
 * {@code generate-report} skill onto the mesh as a long-running
 * {@code report-sse} capability via {@link A2AClient#subscribe} +
 * {@link A2AStream#bridge}.
 *
 * <p>Auto-tag scheme: {@code capability="report-sse"},
 * {@code tags=[a2a-bridge, sse, report-consumer-sse]} (the third tag is
 * auto-injected by the Spring starter from {@link MeshAgent#name()} via
 * {@link A2AConsumer}).
 */
@MeshAgent(
    name = "report-consumer-sse",
    version = "1.0.0",
    description = "uc27 Java A2A SSE long-running consumer fixture.",
    port = 9212
)
@SpringBootApplication
public class ConsumerReportAgentJavaSseApplication {

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        SpringApplication.run(ConsumerReportAgentJavaSseApplication.class, args);
    }

    @MeshTool(
        // Underscore form to match the Python caller-agent-report fixture's
        // report_sse dependency name (lets uc27 reuse the uc25 caller as-is).
        capability = "report_sse",
        task = true,
        description = "Bridge upstream A2A generate-report skill via SSE as report_sse capability.",
        tags = {"a2a-bridge", "sse"}
    )
    @A2AConsumer(
        url = "http://localhost:9091/agents/report",
        skillId = "generate-report"
    )
    public Object generateReportSse(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            A2AClient a2a,
            MeshJob job) throws Exception {
        if (sections == null) {
            sections = List.of("default");
        }
        Map<String, Object> message = buildMessage(userId, sections);
        if (!(job instanceof JobController controller)) {
            return drainSyncFallback(a2a, message);
        }
        try (A2AStream stream = a2a.subscribe(message)) {
            return stream.bridge(controller);
        }
    }

    private Object drainSyncFallback(A2AClient a2a, Map<String, Object> message) throws Exception {
        try (A2AStream stream = a2a.subscribe(message)) {
            for (A2AEvent event : stream) {
                if (event.kind() == A2AEvent.Kind.ARTIFACT) {
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
}
