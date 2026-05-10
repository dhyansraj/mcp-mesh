package com.example.reportconsumer;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AJob;
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
 * A2A consumer example (issue #910 / Phase 3) — Java port of
 * {@code examples/a2a/consumer_report_agent.py}.
 *
 * <p>Bridges the existing {@code examples/a2a/report_a2a_agent.py}
 * {@code generate-report} skill onto the mesh as a long-running
 * {@code report} capability that downstream callers consume via the
 * standard {@link MeshJob} / {@link JobController} interface — they
 * have no idea the actual work is happening on an external A2A
 * backend.
 *
 * <h2>Bridging pattern</h2>
 *
 * The {@code @MeshTool(task=true)} body issues a non-blocking
 * {@link A2AClient#submit} against the upstream A2A surface, then
 * hands the returned {@link A2AJob} to {@link A2AJob#bridge} which
 * polls the A2A backend, mirrors progress into the
 * framework-injected {@link JobController}, and returns the final
 * artifact value (the producer's report payload). Mesh's
 * {@code task=true} wrapper takes that return and calls
 * {@code controller.complete(...)} itself.
 *
 * <h2>Cancel semantics</h2>
 *
 * When the downstream caller cancels the mesh job,
 * {@link JobController#isCancelled()} flips to true. The bridge
 * polls this between iterations: on cancel detection it POSTs
 * {@code tasks/cancel} upstream so the A2A producer stops billing
 * for the work, then throws
 * {@link io.mcpmesh.a2a.A2AJobCanceledException} so the mesh
 * wrapper records the canceled outcome.
 *
 * <h2>Stack</h2>
 *
 * <ul>
 *   <li>Registry — {@code meshctl start --registry-only}</li>
 *   <li>Long-task provider (Python) — produces the report</li>
 *   <li>Report A2A surface (Python) — exposes generate-report via A2A</li>
 *   <li>This Java consumer — bridges A2A back into the mesh as
 *       {@code report} (port 9211)</li>
 * </ul>
 *
 * <h2>Run</h2>
 * <pre>
 * # in src/runtime/java
 * mvn install -DskipTests
 *
 * # in examples/java/consumer-report-agent
 * mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "report-consumer",
    version = "1.0.0",
    description = "Java A2A consumer (long-running) — bridges the report_a2a_agent.py generate-report skill as a mesh ``report`` capability.",
    port = 9211
)
@SpringBootApplication
public class ReportConsumerAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ReportConsumerAgentApplication.class);

    /**
     * One reusable client per (url, skillId, auth) tuple — amortises
     * the underlying {@link java.net.http.HttpClient} connection pool
     * across calls.
     */
    private static final A2AClient A2A_CLIENT = new A2AClient(
        "http://localhost:9091/agents/report",
        "generate-report"
    );

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        log.info("Starting Java A2A Consumer (report-consumer, polling bridge)...");
        SpringApplication.run(ReportConsumerAgentApplication.class, args);
    }

    /**
     * Bridge the upstream A2A {@code generate-report} skill onto the
     * mesh as the {@code report} capability. The {@link MeshTool}
     * carries {@code task=true} so the framework injects a
     * {@link JobController} (via the {@link MeshJob} parameter) for
     * long-running progress mirroring.
     *
     * @return the final artifact value as parsed JSON (typically a
     *         {@code Map<String,Object>} carrying the producer's
     *         report payload).
     */
    @MeshTool(
        capability = "report",
        task = true,
        description = "Bridge upstream A2A generate-report skill onto the mesh as a long-running ``report`` capability.",
        tags = {"a2a-bridge"}
    )
    @A2AConsumer
    public Object generateReport(
            @Param("user_id") String userId,
            @Param("sections") List<String> sections,
            MeshJob job) throws Exception {
        if (!(job instanceof JobController controller)) {
            // Fast-path tools/call (no X-Mesh-Job-Id header) — synchronous
            // send + return without bridging. Matches the producer-side
            // contract where task=true tools must tolerate a null MeshJob.
            return A2A_CLIENT.send(buildMessage(userId, sections));
        }
        Map<String, Object> message = buildMessage(userId, sections);
        A2AJob a2aJob = A2A_CLIENT.submit(message);
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

    @PreDestroy
    void releaseA2AClient() {
        try {
            A2A_CLIENT.close();
        } catch (Exception e) {
            log.warn("Failed to close A2AClient during shutdown", e);
        }
    }
}
