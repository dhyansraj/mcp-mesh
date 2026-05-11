package com.example.dateproducerjava;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc28_a2a_producer_java fixture (issue #932 Chunk 1C) — Java A2A
 * producer mirroring date_a2a_agent.py. Same path, same skill id.
 *
 * <p>Listens on port 9090. Card at
 * {@code GET /agents/date/.well-known/agent.json}; JSON-RPC entry at
 * {@code POST /agents/date}. Depends on the {@code date_service} mesh
 * capability (provided by examples/simple/system_agent.py on port 9100).
 */
@MeshAgent(
    name = "date-a2a-agent",
    version = "1.0.0",
    description = "uc28 Java A2A producer fixture — exposes get-date via @MeshA2A.",
    port = 9090
)
@SpringBootApplication
public class ProducerDateAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(ProducerDateAgentApplication.class, args);
    }

    @Component
    static class DateSkill {

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
                // Returning a sentinel keeps the example runnable solo.
                payload.put("date", Instant.now().toString());
                payload.put("note", "date_service not yet resolved");
                return payload;
            }
            Object result = dateService.call(Map.of());
            payload.put("date", result);
            return payload;
        }
    }
}
