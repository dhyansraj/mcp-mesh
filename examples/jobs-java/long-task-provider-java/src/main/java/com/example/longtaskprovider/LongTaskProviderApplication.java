package com.example.longtaskprovider;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob Phase B — Java Provider: long-running report generator.
 *
 * <p>Demonstrates the producer-side dispatch surface in Java:
 * <pre>{@code
 * @MeshTool(capability = "generate_report", task = true)
 * public Map<String, Object> generateReport(
 *     @Param("user_id") String userId,
 *     @Param("sections") List<String> sections,
 *     MeshJob job) {
 *   // ... progress updates via (JobController) job ...
 * }
 * }</pre>
 *
 * <p>When invoked via the consumer's {@code MeshJobSubmitter.submit(...)} (see
 * {@code ../long-task-consumer-java}), the inbound tool wrapper sees the
 * {@code X-Mesh-Job-Id} header attached by the registry's claim flow,
 * builds a {@link JobController} bound to that job id, and injects it
 * into the {@code job} parameter. Progress updates and the terminal
 * {@code complete()} flush directly to the registry — the consumer's
 * {@code proxy.await(...)} polls the registry until terminal.
 *
 * <p>If you call {@code generateReport} synchronously (regular
 * {@code tools/call}, no {@code X-Mesh-Job-Id} header), the runtime
 * passes {@code null} for {@code job} per
 * {@code MESHJOB_DDDI_CONTRACT.md} — the function then runs the fast
 * path and just returns its result.
 *
 * <p>Run:
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "long-task-provider-java",
    version = "1.0.0",
    description = "MeshJob Phase B (Java) producer — generates reports as long-running jobs",
    port = 9120
)
@SpringBootApplication
public class LongTaskProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(LongTaskProviderApplication.class, args);
    }

    @MeshTool(
        capability = "generate_report",
        task = true,
        description =
            "Long-running report generator. Demonstrates progress updates "
            + "and structured terminal results."
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
            // Simulate substantive work — in a real producer this might be
            // an LLM call, a long DB query, or video transcoding.
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
            // Explicit terminal call — flushes immediately past the
            // batching tick so the consumer sees status=completed
            // without waiting on the next batch interval.
            controller.complete(payload);
        }

        return payload;
    }
}
