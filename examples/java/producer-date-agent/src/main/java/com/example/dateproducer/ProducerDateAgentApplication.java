package com.example.dateproducer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A2A producer example (issue #932 Chunk 1C) — Java port of
 * {@code examples/a2a/date_a2a_agent.py}.
 *
 * <p>Exposes a {@code get-date} skill via the A2A v1.0 protocol surface
 * using {@link MeshA2A} on a Spring Boot bean method. The Spring Boot
 * starter mounts both companion routes the A2A protocol requires:
 *
 * <pre>
 *   GET  /agents/date/.well-known/agent.json   (agent card)
 *   POST /agents/date                          (JSON-RPC tasks/* entry)
 * </pre>
 *
 * <p>The {@code @MeshA2A} method is the Java equivalent of Python's
 * {@code @mesh.a2a.mount(app, path=...)} decorator: it carries the
 * skill-level metadata (skill id, name, description, tags) AND wires
 * the JSON-RPC dispatch table for {@code tasks/send}, {@code tasks/get},
 * {@code tasks/cancel}, {@code tasks/sendSubscribe},
 * {@code tasks/resubscribe} at {@code POST /agents/date}. Return values
 * are wrapped as an A2A v1.0 {@code Task} envelope with
 * {@code state=completed}; handler exceptions become {@code state=failed}.
 *
 * <p>The mesh dependency on {@code date_service} demonstrates DDDI
 * inside an A2A handler: at request time the framework resolves the
 * {@link McpMeshTool} proxy through {@link MeshDependency} and injects
 * it at the {@link MeshInject} parameter slot — same wiring used by
 * {@code @MeshRoute}.
 *
 * <h2>Stack</h2>
 *
 * <ul>
 *   <li>Registry — {@code meshctl start --registry-only}</li>
 *   <li>System agent (Python) — provides {@code date_service} on port 9100</li>
 *   <li>This Java producer — exposes {@code get-date} via A2A on port 9090</li>
 * </ul>
 *
 * <h2>Run</h2>
 * <pre>
 * # in src/runtime/java (build the starter)
 * mvn install -DskipTests
 *
 * # in examples/java/producer-date-agent
 * mvn spring-boot:run
 *
 * # test the agent card
 * curl http://localhost:9090/agents/date/.well-known/agent.json | jq
 *
 * # test the JSON-RPC tasks/send entry
 * curl -X POST http://localhost:9090/agents/date \
 *      -H 'Content-Type: application/json' \
 *      -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
 *           "params":{"id":"t1","message":{"role":"user",
 *           "parts":[{"type":"text","text":"now"}]}}}'
 * </pre>
 */
@MeshAgent(
    name = "date-a2a-agent",
    version = "1.0.0",
    description = "Java A2A producer — exposes a get-date skill via the A2A v1.0 protocol surface.",
    port = 9090
)
@SpringBootApplication
public class ProducerDateAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ProducerDateAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Java A2A Producer (date-a2a-agent)...");
        SpringApplication.run(ProducerDateAgentApplication.class, args);
    }

    /**
     * The skill handler. Bean-scoped (not on the
     * {@code @SpringBootApplication} class) so {@code @Component} scanning
     * picks it up the same way {@code @MeshRoute} bean post-processors
     * do for the other examples.
     */
    @Component
    static class DateSkill {

        /**
         * Handle inbound A2A {@code tasks/send} (and {@code tasks/get},
         * {@code tasks/cancel}, {@code tasks/sendSubscribe},
         * {@code tasks/resubscribe} — same handler, the framework picks
         * the right envelope shape based on the inbound method).
         *
         * <p>The framework passes the inbound A2A {@code message} dict
         * ({@code {"role": "user", "parts": [...]}}) at the {@code Map}
         * parameter slot. For the date example we ignore it and just
         * call the upstream {@code date_service} mesh dependency.
         *
         * @param message    inbound A2A request message (ignored here)
         * @param dateService framework-injected mesh tool proxy
         * @return a map that becomes the A2A artifact text payload
         *         (JSON-stringified into {@code parts[0].text})
         * @throws Exception on upstream failure (becomes state=failed)
         */
        @MeshA2A(
            path = "/agents/date",
            skillId = "get-date",
            skillName = "Get Date",
            description = "Get current date/time via A2A protocol",
            tags = {"system", "date"},
            dependencies = {
                @MeshDependency(capability = "date_service")
            }
        )
        public Map<String, Object> getDate(
                Map<String, Object> message,
                @MeshInject("date_service") McpMeshTool dateService) throws Exception {
            Map<String, Object> payload = new LinkedHashMap<>();
            if (dateService == null) {
                // Defer-resolution: dependency not yet wired by mesh DI.
                // Returning a sentinel keeps the example runnable solo
                // (sync handler return → state=completed envelope).
                payload.put("date", Instant.now().toString());
                payload.put("note", "date_service not yet resolved — returning local fallback");
                return payload;
            }
            Object result = dateService.call(Map.of());
            payload.put("date", result);
            return payload;
        }
    }
}
