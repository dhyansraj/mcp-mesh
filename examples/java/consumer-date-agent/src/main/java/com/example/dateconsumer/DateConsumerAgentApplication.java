package com.example.dateconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import tools.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;

/**
 * A2A consumer example (issue #916 Phase 1) — Java port of
 * {@code examples/a2a/consumer_date_agent.py}.
 *
 * <p>Bridges the existing {@code examples/a2a/date_a2a_agent.py}
 * {@code get-date} skill into the mesh as a regular {@code current-date}
 * capability. A downstream mesh tool depending on {@code current-date}
 * does not need to know it is talking to an A2A backend — mesh's
 * existing capability+tag failover applies the moment a SECOND consumer
 * (e.g. a TypeScript or Python bridge) registers the same
 * {@code current-date} capability with a different consumer-name tag.
 *
 * <p>Each consumer auto-tags its capability with the surrounding
 * {@link MeshAgent#name()} via {@link A2AConsumer} (here
 * {@code date-consumer}) so downstream resolvers can pin a specific
 * backend via the dependency tag selector.
 *
 * <h2>Stack</h2>
 * <ul>
 *   <li>Registry — {@code meshctl start --registry-only}</li>
 *   <li>System agent (Python) — provides {@code date_service}</li>
 *   <li>Date A2A surface (Python) — exposes get-date via A2A on
 *       {@code http://localhost:9090/agents/date}</li>
 *   <li>This Java consumer — bridges the get-date skill onto the mesh
 *       as {@code current-date}</li>
 * </ul>
 *
 * <h2>Run</h2>
 * <pre>
 * # in src/runtime/java
 * mvn install -DskipTests
 *
 * # in examples/java/consumer-date-agent
 * mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "date-consumer",
    version = "1.0.0",
    description = "Java A2A consumer bridge — re-publishes the date_a2a_agent get-date skill as a mesh current-date capability.",
    port = 9201
)
@SpringBootApplication
public class DateConsumerAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(DateConsumerAgentApplication.class);

    /**
     * One reusable client per (url, skillId, auth) tuple — amortises
     * the underlying {@link java.net.http.HttpClient} connection pool
     * across calls. The producer is unauth in the example deployment
     * so no {@code A2ABearer} is supplied.
     */
    private static final A2AClient A2A_CLIENT = new A2AClient(
        "http://localhost:9090/agents/date",
        "get-date"
    );

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        log.info("Starting Java A2A Consumer (date-consumer)...");
        SpringApplication.run(DateConsumerAgentApplication.class, args);
    }

    /**
     * Bridge the upstream A2A {@code get-date} skill onto the mesh as
     * the {@code current-date} capability. The {@link A2AConsumer}
     * marker tells the runtime to inject the surrounding
     * {@link MeshAgent#name()} as a tag, so this capability registers
     * with tags {@code [a2a-bridge, date-consumer]}.
     *
     * <p>The producer-side handler returns
     * {@code {"date": "<iso-string>"}} and the A2A surface
     * JSON-stringifies it into the artifact text part — so we
     * {@code readValue} on the consumer side to recover the dict.
     *
     * @return the producer's date payload as a Map
     * @throws Exception on transport, JSON, or A2A protocol failure.
     */
    @MeshTool(
        capability = "current-date",
        description = "Get the current date by bridging the upstream A2A get-date skill",
        tags = {"a2a-bridge"}
    )
    @A2AConsumer
    public Map<String, Object> currentDate() throws Exception {
        A2AResponse response = A2A_CLIENT.send(Map.of(
            "role", "user",
            "parts", List.of(Map.of("type", "text", "text", "now"))
        ));
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = JSON.readValue(response.artifactText(), Map.class);
        return payload;
    }
}
