package com.example.downstreamsleeper;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Downstream sleeper agent (uc23 Java) — exercises cancel propagation.
 *
 * <p>Java port of uc21_meshjob/fixtures/downstream-sleeper/main.py and
 * uc22_meshjob_ts/fixtures/downstream-sleeper-ts.
 *
 * <p>Provides {@code slow_downstream}, a regular (non-task) tool that
 * sleeps for the requested number of seconds. The producer agent's
 * {@code report_with_downstream_call} invokes this via the mesh proxy.
 *
 * <h2>Cancel-propagation gap</h2>
 *
 * <p>In a runtime where cancel propagates end-to-end, the producer's
 * cancel token would abort the in-flight outbound HTTP, surfacing here
 * as an {@link InterruptedException}. The Java SDK (per #889) currently
 * cannot bind the cancel registry, so the cancel token never fires for
 * Java-owned jobs — this sleep runs to natural completion regardless.
 * Tests that exercise this path therefore assert ONLY registry-side
 * correctness ({@code status=cancelled}), not the marker line below.
 */
@MeshAgent(
    name = "downstream-sleeper-java",
    version = "1.0.0",
    description = "Slow downstream tool used to verify mesh-job cancel propagation (Java).",
    port = 9122
)
@SpringBootApplication
public class DownstreamSleeperApplication {

    public static void main(String[] args) {
        SpringApplication.run(DownstreamSleeperApplication.class, args);
    }

    @MeshTool(
        capability = "slow_downstream",
        description = "Sleeps for the requested number of seconds (regular tool, not task=true)."
    )
    public Map<String, Object> slowDownstream(
            @Param("user_id") String userId,
            @Param(value = "seconds", required = false) Integer seconds) {
        if (seconds != null && seconds < 0) {
            throw new IllegalArgumentException("seconds must be >= 0");
        }
        int totalSecs = seconds == null ? 30 : seconds;
        System.err.println("[downstream-sleeper-java] starting " + totalSecs
                + "s sleep for user=" + userId);
        try {
            Thread.sleep(totalSecs * 1000L);
        } catch (InterruptedException e) {
            // UNREACHABLE in practice — the Java SDK does not surface
            // inbound client-disconnect / cancel as interrupt today
            // (parallel to TS uc22 fixture's documented gap).
            System.err.println("[downstream-sleeper-java] sleep CANCELLED for user="
                    + userId + " (cancel token fired)");
            Thread.currentThread().interrupt();
            throw new RuntimeException("interrupted", e);
        }
        System.err.println("[downstream-sleeper-java] sleep completed for user="
                + userId + " (NOT cancelled)");
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("user_id", userId);
        result.put("slept", totalSecs);
        return result;
    }
}
