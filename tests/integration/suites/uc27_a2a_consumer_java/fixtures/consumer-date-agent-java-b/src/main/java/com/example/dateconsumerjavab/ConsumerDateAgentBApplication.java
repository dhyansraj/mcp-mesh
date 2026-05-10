package com.example.dateconsumerjavab;

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
 * uc27 Java consumer (alt) — second bridge over the same date_a2a_agent
 * producer at localhost:9090, but registered under
 * date-consumer-alt so the auto-injected consumer-name tag
 * distinguishes it from date-consumer for failover (tc03).
 */
@MeshAgent(
    name = "date-consumer-alt",
    version = "1.0.0",
    description = "uc27 Java A2A consumer (alt) — second bridge for failover tests.",
    port = 9202
)
@SpringBootApplication
public class ConsumerDateAgentBApplication {

    private static final A2AClient A2A_CLIENT = new A2AClient(
        "http://localhost:9090/agents/date",
        "get-date"
    );

    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) {
        SpringApplication.run(ConsumerDateAgentBApplication.class, args);
    }

    @MeshTool(
        capability = "current-date",
        description = "Bridge upstream A2A get-date skill onto the mesh (alt consumer).",
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
