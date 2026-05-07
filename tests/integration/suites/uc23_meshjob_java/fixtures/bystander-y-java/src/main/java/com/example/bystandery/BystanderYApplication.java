package com.example.bystandery;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Bystander Y (uc23 Java) — used by tc16 to verify third-party status reads.
 *
 * <p>Mirror of bystander-x-java in every way except agent name; deployed
 * alongside X so the test can prove BOTH agents (each with no involvement
 * in the job) can read its state via the framework's helper tools.
 */
@MeshAgent(
    name = "bystander-y-java",
    version = "1.0.0",
    description = "Bystander agent Y (Java) — verifies third-party status reads (tc16).",
    port = 9125
)
@SpringBootApplication
public class BystanderYApplication {

    public static void main(String[] args) {
        SpringApplication.run(BystanderYApplication.class, args);
    }

    @MeshTool(
        capability = "bystander_y_ping",
        description = "Trivial tool — keeps bystander Y alive in the registry."
    )
    public Map<String, Object> bystanderYPing() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("ok", true);
        response.put("agent", "bystander-y-java");
        return response;
    }
}
