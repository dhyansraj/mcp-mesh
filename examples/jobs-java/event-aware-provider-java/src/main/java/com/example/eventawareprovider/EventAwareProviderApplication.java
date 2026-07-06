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

    /**
     * Durable variant of {@link #eventAwareLongTask}. Accumulates each
     * {@code work} event's amount and exits cleanly on {@code stop}.
     *
     * <p>{@code resumeCursor = true} (issue #1277): if this job is re-claimed
     * after a crash or reclaim, the handler resumes {@code recvEvent} from the
     * persisted per-filter cursor — it does NOT replay the event log from
     * seq 0, so the non-idempotent {@code total += amount} accumulation below
     * is not re-applied for events already consumed on the prior claim.
     *
     * <p>Resume contract:
     * <ul>
     *   <li>At-least-once still holds: a bounded tail of already-processed
     *       events may replay on resume, so keep per-event effects tolerant of
     *       a rare repeat (or fence on {@code event.get("seq")}).</li>
     *   <li>Consumption MUST stay strictly sequential-per-filter: process each
     *       event fully before the next {@code recvEvent}. Do NOT prefetch a
     *       batch or fan events out to concurrent workers — the persisted
     *       cursor only advances correctly for in-order, one-at-a-time
     *       draining.</li>
     * </ul>
     */
    @MeshTool(
        capability = "resumable_event_task",
        task = true,
        resumeCursor = true,
        description =
            "Durable variant of event_aware_long_task. Opts into resumeCursor "
            + "so a re-claimed run resumes after the last processed event "
            + "instead of replaying its event log from seq 0."
    )
    public Map<String, Object> resumableEventTask(MeshJob job) {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller == null) {
            return Map.of("error", "no job controller injected");
        }

        long total = 0;
        int processed = 0;
        while (true) {
            Map<String, Object> event = controller.recvEvent(
                List.of("work", "stop"), Duration.ofSeconds(30));
            if (event == null) {
                continue;
            }

            if ("stop".equals(event.get("type"))) {
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("processed", processed);
                payload.put("total", total);
                payload.put("status", "stopped");
                controller.complete(payload);
                return payload;
            }

            // Sequential-per-filter: this non-idempotent accumulation runs
            // once per event, in order, before we request the next one.
            long amount = 1;
            if (event.get("payload") instanceof Map<?, ?> p
                    && p.get("amount") instanceof Number n) {
                amount = n.longValue();
            }
            total += amount;
            processed += 1;
            controller.updateProgress(
                Math.min(processed / 10.0, 0.99),
                "applied work item " + processed
                    + " (seq=" + event.get("seq") + ", total=" + total + ")");
        }
    }
}
