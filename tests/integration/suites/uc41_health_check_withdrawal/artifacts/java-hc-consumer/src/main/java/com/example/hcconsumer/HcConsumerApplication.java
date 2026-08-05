package com.example.hcconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * java-hc-consumer — reports which provider the mesh routed it to (#1480).
 *
 * <p>{@code who_served} injects {@code hc_probe_java} and returns the
 * provider's payload verbatim. Started ONCE and never restarted, so the only
 * way its answer can move from provider A to provider B and back is a genuine
 * re-resolution — the withdrawal / recovery chain under test.
 *
 * <p>The MCP tool name is the METHOD name verbatim — {@code @MeshTool} has no
 * {@code name()} attribute and does not snake_case anything — so the test
 * calls {@code hc-consumer-java:whoServed}, not {@code who_served}. Same
 * convention as uc38's {@code getRejectCount}.
 *
 * <p>An unresolved dependency reports {@code served_by: "UNRESOLVED"} rather
 * than throwing. The test's failover poll then keeps polling through a
 * transient gap instead of tripping on it, and a PERMANENT gap still fails the
 * run because {@code "UNRESOLVED"} never becomes a provider name.
 */
@SpringBootApplication
@MeshAgent(
    name = "hc-consumer-java",
    version = "1.0.0",
    description = "Consumer that must fail over when provider A withdraws (#1480)",
    port = 3433
)
public class HcConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(HcConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "who_served_java",
        description = "Call hc_probe_java and report which provider answered",
        tags = {"hc-withdrawal"},
        dependencies = {@Selector(capability = "hc_probe_java")}
    )
    public Map<String, Object> whoServed(McpMeshTool<Map<String, Object>> probe) {
        if (probe == null || !probe.isAvailable()) {
            return Map.of("served_by", "UNRESOLVED");
        }
        try {
            Map<String, Object> payload = probe.call(Map.of());
            if (payload == null || !payload.containsKey("served_by")) {
                return Map.of("served_by", "UNRESOLVED", "raw", String.valueOf(payload));
            }
            return new LinkedHashMap<>(payload);
        } catch (Exception e) {
            return Map.of("served_by", "UNRESOLVED", "error", String.valueOf(e.getMessage()));
        }
    }
}
