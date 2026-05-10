package com.example.reportconsumerjava;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AJob;
import io.mcpmesh.a2a.A2AResponse;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * uc27 Phase 3 fixture (refactored under #923) — Java A2A consumer that
 * bridges {@code report_a2a_agent.py}'s {@code generate-report} skill onto
 * the mesh as a long-running {@code report} capability via
 * {@link A2AClient#submit} + {@link A2AJob#bridge}.
 *
 * <p>Auto-tag scheme matches the Python uc25 consumer-report-agent:
 * {@code capability="report"}, {@code tags=[a2a-bridge, report-consumer]}
 * (the second tag is auto-injected by the Spring starter from
 * {@link MeshAgent#name()} via {@link A2AConsumer}).
 */
@MeshAgent(
    name = "report-consumer",
    version = "1.0.0",
    description = "uc27 Java A2A long-running consumer fixture — bridges report_a2a_agent.py generate-report.",
    port = 9211
)
@SpringBootApplication
public class ConsumerReportAgentJavaApplication {

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        SpringApplication.run(ConsumerReportAgentJavaApplication.class, args);
    }

    @MeshTool(
        capability = "report",
        task = true,
        description = "Bridge upstream A2A generate-report skill onto the mesh as a long-running report capability.",
        tags = {"a2a-bridge"}
    )
    @A2AConsumer(
        url = "http://localhost:9091/agents/report",
        skillId = "generate-report"
    )
    public Object generateReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            A2AClient a2a,
            MeshJob job) throws Exception {
        if (sections == null) {
            sections = List.of("default");
        }
        Map<String, Object> message = buildMessage(userId, sections);
        if (!(job instanceof JobController controller)) {
            A2AResponse response = a2a.send(message);
            String text = response.artifactText();
            if (text == null || text.isEmpty()) {
                return text == null ? "" : text;
            }
            try {
                return JSON.readValue(text, Object.class);
            } catch (Exception parseExc) {
                return text;
            }
        }
        A2AJob a2aJob = a2a.submit(message);
        return a2aJob.bridge(controller);
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
