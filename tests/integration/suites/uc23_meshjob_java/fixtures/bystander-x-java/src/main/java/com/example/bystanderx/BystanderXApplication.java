package com.example.bystanderx;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Bystander X (uc23 Java) — used by tc16 to verify third-party status reads.
 *
 * <p>Has no MeshJob deps and no task=true tools. The framework still
 * auto-registers {@code __mesh_job_status} / {@code __mesh_job_result} /
 * {@code __mesh_job_cancel} on every mesh agent, so the test can read
 * job state from this agent for a job_id it did not submit.
 *
 * <p>Distinct fixture file (separate from bystander-y-java) so meshctl's
 * "is this agent already running" check (which keys off
 * {@code @MeshAgent(name=...)}) doesn't conflate the two instances.
 */
@MeshAgent(
    name = "bystander-x-java",
    version = "1.0.0",
    description = "Bystander agent X (Java) — verifies third-party status reads (tc16).",
    port = 9124
)
@SpringBootApplication
public class BystanderXApplication {

    public static void main(String[] args) {
        SpringApplication.run(BystanderXApplication.class, args);
    }

    @MeshTool(
        capability = "bystander_x_ping",
        description = "Trivial tool — keeps bystander X alive in the registry."
    )
    public Map<String, Object> bystanderXPing() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("ok", true);
        response.put("agent", "bystander-x-java");
        return response;
    }
}
