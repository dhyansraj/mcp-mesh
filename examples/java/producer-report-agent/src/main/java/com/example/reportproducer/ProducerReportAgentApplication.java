package com.example.reportproducer;

import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.spring.web.MeshA2A;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * A2A producer example for LONG-RUNNING tasks (issue #932 Chunk 1C) —
 * Java port of {@code examples/a2a/report_a2a_agent.py}.
 *
 * <p>Exposes a {@code generate-report} skill via the A2A v1.0 protocol
 * surface. The handler submits work to a {@code task=true} mesh
 * capability (here {@code generate_report}, served by the existing
 * {@code examples/jobs/long-task-provider} Python agent) and returns
 * the resulting {@link JobProxy}. The framework switches into
 * long-running mode:
 *
 * <ul>
 *   <li>The inbound {@code tasks/send} returns {@code state=working}
 *       immediately with a fresh task id.</li>
 *   <li>The task is parked in the A2A task store keyed by that id.</li>
 *   <li>Subsequent {@code tasks/get} polls the parked proxy via
 *       {@link JobProxy#status()}.</li>
 *   <li>{@code tasks/cancel} calls {@link JobProxy#cancel(String)},
 *       propagating through to the underlying mesh job.</li>
 *   <li>{@code tasks/sendSubscribe} opens an SSE stream of
 *       {@code TaskStatusUpdateEvent} + {@code TaskArtifactUpdateEvent}
 *       envelopes sourced from the parked proxy's status updates.</li>
 * </ul>
 *
 * <h2>MeshJobSubmitter wiring</h2>
 *
 * <p>Issue #936: the dispatcher auto-injects {@link MeshJobSubmitter}
 * at any handler parameter typed {@code MeshJobSubmitter}. The capability
 * defaults to the first declared {@code @MeshDependency} on the surface,
 * or — when none is declared, as in this example — to the {@code skillId}
 * with {@code '-'} replaced by {@code '_'} (so {@code "generate-report"}
 * resolves to the {@code generate_report} task capability). The submitter
 * is stateless and reused across requests; user code never has to autowire
 * {@code MeshRuntime} or know about agent identity / registry URL.
 *
 * <h2>Stack</h2>
 *
 * <ul>
 *   <li>Registry — {@code meshctl start --registry-only}</li>
 *   <li>Long-task provider (Python) — provides
 *       {@code generate_report} ({@code task=true}) on port 9100</li>
 *   <li>This Java producer — exposes {@code generate-report} via A2A
 *       on port 9091</li>
 * </ul>
 *
 * <h2>Run</h2>
 * <pre>
 * # in src/runtime/java (build the starter)
 * mvn install -DskipTests
 *
 * # in examples/java/producer-report-agent
 * mvn spring-boot:run
 *
 * # submit + poll
 * TASK_ID=$(curl -s -X POST http://localhost:9091/agents/report \
 *   -H 'Content-Type: application/json' \
 *   -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
 *        "params":{"id":"r1","message":{"role":"user",
 *        "parts":[{"type":"text",
 *        "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}' \
 *   | jq -r '.result.id')
 *
 * curl -s -X POST http://localhost:9091/agents/report \
 *   -H 'Content-Type: application/json' \
 *   -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tasks/get\",\"params\":{\"id\":\"$TASK_ID\"}}"
 *
 * # stream via SSE
 * curl -N -X POST http://localhost:9091/agents/report \
 *   -H 'Accept: text/event-stream' \
 *   -H 'Content-Type: application/json' \
 *   -d '{"jsonrpc":"2.0","id":3,"method":"tasks/sendSubscribe",
 *        "params":{"id":"s1","message":{"role":"user",
 *        "parts":[{"type":"text",
 *        "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}'
 * </pre>
 */
@MeshAgent(
    name = "report-a2a-agent",
    version = "1.0.0",
    description = "Java A2A producer (long-running) — bridges generate_report task=true via the A2A v1.0 protocol surface.",
    port = 9091
)
@SpringBootApplication
public class ProducerReportAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ProducerReportAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Java A2A Producer (report-a2a-agent, long-running)...");
        SpringApplication.run(ProducerReportAgentApplication.class, args);
    }

    @Component
    static class ReportSkill {

        private static final ObjectMapper JSON = new ObjectMapper();

        /**
         * Handle inbound A2A {@code tasks/send} (and {@code tasks/get},
         * {@code tasks/cancel}, {@code tasks/sendSubscribe},
         * {@code tasks/resubscribe} — same handler, the framework picks
         * the right envelope shape based on the inbound method).
         *
         * <p>The A2A request {@code message} carries the user payload as
         * a text part with JSON-encoded args. Real-world clients can use
         * any parts shape; for this example we parse {@code parts[0].text}
         * as JSON.
         *
         * <p>Returning the {@link JobProxy} switches the framework into
         * long-running mode (see class Javadoc).
         *
         * @param message inbound A2A request message
         * @param jobSubmitter framework-injected submitter bound to the
         *                     {@code generate_report} capability (derived
         *                     from {@code skillId} per issue #936)
         * @return the parked job proxy (long-running mode trigger)
         * @throws Exception on registry submission failure (becomes
         *         state=failed)
         */
        @MeshA2A(
            path = "/agents/report",
            skillId = "generate-report",
            skillName = "Generate Report",
            description = "Generate a long-form report via A2A (task=True streaming)",
            tags = {"reports", "long-running"}
        )
        public Object generateReport(
                Map<String, Object> message,
                MeshJobSubmitter jobSubmitter) throws Exception {
            // Parse the user payload from the message's first text part.
            // Tolerant: empty payload defaults to a single "overview" section.
            String userId = "anon";
            List<String> sections = List.of("overview");
            Object partsObj = message != null ? message.get("parts") : null;
            if (partsObj instanceof List<?> parts && !parts.isEmpty()
                && parts.get(0) instanceof Map<?, ?> firstPart
                && "text".equals(firstPart.get("type"))) {
                Object textObj = firstPart.get("text");
                if (textObj instanceof String text && !text.isEmpty()) {
                    try {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> args = JSON.readValue(text, Map.class);
                        Object u = args.get("user_id");
                        if (u instanceof String s && !s.isEmpty()) userId = s;
                        Object s = args.get("sections");
                        if (s instanceof List<?> list && !list.isEmpty()) {
                            sections = list.stream().map(String::valueOf).toList();
                        }
                    } catch (Exception parseExc) {
                        // Keep defaults on parse failure — A2A protocol does not
                        // mandate any particular payload shape.
                        log.debug("Failed to parse A2A message parts[0].text as JSON, using defaults: {}",
                            parseExc.getMessage());
                    }
                }
            }

            if (jobSubmitter == null) {
                // The framework injects the submitter; null only happens
                // when MeshRuntime hasn't finished initialising (transient).
                throw new IllegalStateException(
                    "MeshJobSubmitter not yet available — mesh runtime is still initialising. "
                        + "Retry tasks/send shortly.");
            }

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("user_id", userId);
            payload.put("sections", sections);
            // submit() returns CompletableFuture<JobProxy>. We block here
            // because the @MeshA2A dispatcher itself runs on a servlet
            // thread that's already waiting for the handler return —
            // returning the future would be misinterpreted as a sync result.
            //
            // Bounded wait: submit() is a registry round-trip (and any
            // capability claim handshake), NOT the long job itself. 30s
            // covers normal-case latency with comfortable headroom; anything
            // longer is a network / provider problem and should surface as a
            // failed A2A task, not as an indefinite hang on the dispatcher.
            JobProxy proxy;
            try {
                proxy = jobSubmitter.submit(payload).get(30, TimeUnit.SECONDS);
            } catch (TimeoutException te) {
                throw new RuntimeException(
                    "submit() did not return a JobProxy within 30s — "
                        + "registry / provider-side timeout", te);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("submit() interrupted", ie);
            } catch (ExecutionException ee) {
                Throwable cause = ee.getCause() != null ? ee.getCause() : ee;
                throw new RuntimeException("submit() failed: " + cause.getMessage(), cause);
            }
            log.info("@MeshA2A generate-report: submitted job_id={} (will park in A2A task store)",
                proxy.jobId());
            return proxy;
        }
    }
}
