package com.example.reportproducer;

import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.spring.MeshRuntime;
import io.mcpmesh.spring.web.MeshA2A;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Lazy;
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
 * <p>{@code @MeshA2A} handlers receive {@link io.mcpmesh.types.McpMeshTool}
 * proxies at parameter slots but the framework does not (today) inject
 * a {@link MeshJobSubmitter} via the {@code dependencies} array — that
 * auto-wiring is reserved for {@code @MeshTool}-decorated consumers.
 * For long-running producers we construct the submitter manually from
 * the autowired {@link MeshRuntime}: it carries both the registry URL
 * and the local agent id (the {@code submitted_by} identity recorded
 * on every new job row). The submitter is cheap to construct (no I/O
 * until {@link MeshJobSubmitter#submit(java.util.Map)} fires) and
 * stateless after construction.
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
         * Reference to the MeshRuntime — we read the registry URL and
         * the local agent id from {@link MeshRuntime#getAgentSpec()} at
         * request time. Autowiring (rather than constructor injection)
         * keeps the component decoupled from runtime construction order
         * (the runtime bean is created late, after auto-config).
         *
         * <p><strong>Why {@code @Lazy}.</strong> The user-level workaround
         * of injecting {@link MeshRuntime} into a {@code @Component} to
         * construct a {@code MeshJobSubmitter} by hand creates a bean-
         * creation cycle in Spring 6+: {@code MeshRuntime#buildAgentSpec}
         * eagerly walks {@code @Component} beans → finds this
         * {@code ReportSkill} (currently in creation) → cycle. The
         * {@code @Lazy} annotation tells Spring to inject a CGLIB proxy
         * that defers actual runtime resolution to first method call (at
         * request time, not at construction time), so the
         * {@code ReportSkill -> MeshRuntime} edge of the dependency graph
         * is broken structurally — regardless of which side is constructed
         * first. Same fix pattern as {@code MeshHealthController} in
         * {@code MeshAutoConfiguration}.
         *
         * <p>The cleaner long-term fix is for the {@code @MeshA2A}
         * dispatcher to auto-inject {@link io.mcpmesh.MeshJobSubmitter}
         * for {@code task=true} dependencies (today it only injects
         * {@link io.mcpmesh.types.McpMeshTool}). Tracked as a follow-up
         * issue; once that lands this autowire-and-hand-construct dance
         * goes away entirely.
         */
        @Autowired
        @Lazy
        private MeshRuntime meshRuntime;

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
        public Object generateReport(Map<String, Object> message) throws Exception {
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

            // Construct a MeshJobSubmitter bound to the long-task-provider's
            // generate_report capability. The framework's @MeshTool-side
            // auto-wiring (JobsRuntimeManager.wireConsumers) does not run
            // for @MeshA2A handlers; we wire by hand. Cheap to construct
            // — no I/O until submit() fires.
            String registryUrl = meshRuntime.getAgentSpec().getRegistryUrl();
            String agentId = meshRuntime.getAgentSpec().getAgentId();
            MeshJobSubmitter submitter = new MeshJobSubmitter("generate_report", agentId, registryUrl);

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
                proxy = submitter.submit(payload).get(30, TimeUnit.SECONDS);
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
