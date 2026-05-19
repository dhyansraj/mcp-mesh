package com.example.eventawareprovider;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob Phase 2 — Java Provider: event-aware long task (v2.2).
 *
 * <p>Demonstrates the producer-side event-channel surface added in v2.2:
 * <pre>{@code
 * @MeshTool(capability = "event_aware_long_task", task = true)
 * public Map<String, Object> eventAwareLongTask(MeshJob job) {
 *   JobController controller = (JobController) job;
 *   while (true) {
 *     Map<String, Object> event = controller.recvEvent(
 *         List.of("work", "stop"), Duration.ofSeconds(30));
 *     // ...
 *   }
 * }
 * }</pre>
 *
 * <p>Pattern: the handler drains a per-job event log inline.
 * {@code recvEvent} long-polls the registry; each invocation returns
 * the next event matching the type filter, or {@code null} if no event
 * arrives within the timeout budget. The {@code stop} event lets a
 * remote caller cleanly shut the loop down without having to
 * {@code cancel()} the job.
 *
 * <p>Pair this provider with
 * {@code ../event-aware-consumer-java} for a full 3-terminal demo.
 *
 * <p>Run:
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "event-aware-provider-java",
    version = "1.0.0",
    description = "MeshJob v2.2 (Java) producer — drains injected events via recvEvent",
    port = 9122
)
@SpringBootApplication
public class EventAwareProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(EventAwareProviderApplication.class, args);
    }

    @MeshTool(
        capability = "event_aware_long_task",
        task = true,
        description =
            "Long-running task that drains injected events. Loops on "
            + "recvEvent(['work', 'stop']) and exits cleanly on 'stop'."
    )
    public Map<String, Object> eventAwareLongTask(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            return Map.of("error", "no job controller injected");
        }

        int processed = 0;
        while (true) {
            Map<String, Object> event = controller.recvEvent(
                List.of("work", "stop"), Duration.ofSeconds(30));
            if (event == null) {
                // Long-poll budget elapsed with no matching event. In a
                // real producer this is a good moment to tick housekeeping
                // (refresh leases, write checkpoints) before re-parking.
                controller.updateProgress(
                    processed / (processed + 1.0),
                    "idle, waiting for events (processed=" + processed + ")");
                continue;
            }

            if ("stop".equals(event.get("type"))) {
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("processed", processed);
                payload.put("status", "stopped");
                controller.complete(payload);
                return payload;
            }

            // 'work' event — advance counter, log progress.
            processed += 1;
            controller.updateProgress(
                Math.min(processed / 10.0, 0.99),
                "processed work item " + processed
                    + " (seq=" + event.get("seq") + ")");
        }
    }
}
