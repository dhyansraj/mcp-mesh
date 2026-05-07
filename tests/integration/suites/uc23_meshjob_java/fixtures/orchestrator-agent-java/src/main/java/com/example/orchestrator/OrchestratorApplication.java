package com.example.orchestrator;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Orchestrator agent (uc23 Java) — Java port of orchestrator-agent.
 *
 * <p>Has NO task=true tools and NO mesh deps. Used by tc14 to prove the
 * three framework helper tools ({@code __mesh_job_status} /
 * {@code __mesh_job_result} / {@code __mesh_job_cancel}) auto-register
 * on every Java mesh agent regardless of whether that agent
 * participates in the job lifecycle.
 */
@MeshAgent(
    name = "orchestrator-agent-java",
    version = "1.0.0",
    description = "Agent with no task tools and no mesh deps — verifies helper-tool auto-registration is universal (Java).",
    port = 9123
)
@SpringBootApplication
public class OrchestratorApplication {

    public static void main(String[] args) {
        SpringApplication.run(OrchestratorApplication.class, args);
    }

    @MeshTool(
        capability = "orchestrator_ping",
        description = "Trivial tool — only purpose is to keep the agent alive in the registry."
    )
    public Map<String, Object> orchestratorPing() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("ok", true);
        response.put("agent", "orchestrator-agent-java");
        return response;
    }
}
