package com.example.reportproducerjava;

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
 * uc28_a2a_producer_java fixture (long-running) — Java A2A producer
 * exposing the {@code generate-report} skill via {@code @MeshA2A} on
 * top of the existing {@code generate_report} {@code task=true}
 * capability served by the long-task-provider Python agent on port
 * 9100. Returns a {@link JobProxy} to trigger the framework's
 * long-running mode (parks the task in the A2A task store, services
 * {@code tasks/get}, {@code tasks/cancel}, {@code tasks/sendSubscribe},
 * {@code tasks/resubscribe} from it).
 *
 * <p>Issue #936: the {@link MeshJobSubmitter} is auto-injected by the
 * dispatcher — capability defaults to the {@code skillId} with
 * {@code '-'} replaced by {@code '_'} (so {@code "generate-report"}
 * resolves to {@code generate_report}). No more {@code @Lazy MeshRuntime}
 * workaround.
 */
@MeshAgent(
    name = "report-a2a-agent",
    version = "1.0.0",
    description = "uc28 Java A2A producer fixture (long-running).",
    port = 9091
)
@SpringBootApplication
public class ProducerReportAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ProducerReportAgentApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(ProducerReportAgentApplication.class, args);
    }

    @Component
    static class ReportSkill {

        private static final ObjectMapper JSON = new ObjectMapper();

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
                        log.debug("Failed to parse parts[0].text: {}", parseExc.getMessage());
                    }
                }
            }

            if (jobSubmitter == null) {
                throw new IllegalStateException(
                    "MeshJobSubmitter not yet available — mesh runtime is still initialising. "
                        + "Retry tasks/send shortly.");
            }

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("user_id", userId);
            payload.put("sections", sections);
            // Bounded wait: submit() is a registry round-trip, NOT the long
            // job itself. Anything beyond 30s is a registry/network problem
            // and should surface as a failed A2A task, not as an indefinite
            // hang on the dispatcher thread.
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
            log.info("@MeshA2A generate-report: parked job_id={}", proxy.jobId());
            return proxy;
        }
    }
}
