package com.example.dateconsumerjava;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.a2a.A2AResponse;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import tools.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;

/**
 * uc27_a2a_consumer_java fixture (issue #923 — annotation-config form) —
 * bridges the existing date_a2a_agent.py producer's get-date skill onto
 * the mesh as a current-date capability.
 *
 * <p>All test agents share the tsuite container's network namespace,
 * so the upstream A2A endpoint is reachable on localhost:9090 (NOT a
 * docker service name).
 */
@MeshAgent(
    name = "date-consumer",
    version = "1.0.0",
    description = "Java A2A consumer fixture — bridges date_a2a_agent.py get-date as current-date.",
    port = 9201
)
@SpringBootApplication
public class ConsumerDateAgentApplication {

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        SpringApplication.run(ConsumerDateAgentApplication.class, args);
    }

    @MeshTool(
        capability = "current-date",
        description = "Bridge upstream A2A get-date skill onto the mesh.",
        tags = {"a2a-bridge"}
    )
    @A2AConsumer(
        url = "http://localhost:9090/agents/date",
        skillId = "get-date"
    )
    public Map<String, Object> currentDate(A2AClient a2a) throws Exception {
        A2AResponse response = a2a.send(Map.of(
            "role", "user",
            "parts", List.of(Map.of("type", "text", "text", "now"))
        ));
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = JSON.readValue(response.artifactText(), Map.class);
        return payload;
    }
}
