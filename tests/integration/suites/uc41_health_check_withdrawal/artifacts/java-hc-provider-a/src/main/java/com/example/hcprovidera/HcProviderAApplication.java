package com.example.hcprovidera;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Map;

/**
 * java-hc-provider-a — the provider whose health check the test drives (#1480).
 *
 * <p>Java twin of py-hc-provider-a / ts-hc-provider-a. Same contract, same flag
 * file, same trace file: the three runtimes are meant to be behaviourally
 * identical here, and divergence is exactly what keeps getting found.
 *
 * <h2>File-toggled, not invocation-counting</h2>
 *
 * <p>{@code @MeshHealthCheck} re-reads {@code /workspace/health-flag} on every
 * tick so the test controls WHEN the transition happens and can poll for it:
 *
 * <pre>
 *   ok (or file absent) -&gt; healthy    heartbeats, stays resolvable
 *   fail                -&gt; unhealthy  heartbeat suppressed -&gt; registry withdraws
 *   throw               -&gt; throws     must map to DEGRADED, must NOT withdraw
 * </pre>
 *
 * <h2>Every invocation is traced</h2>
 *
 * <p>One line is appended to {@code /workspace/hc-invocations.log} BEFORE the
 * throw branch throws. Without it the negative test would pass vacuously: a
 * health check that stopped running also fails to withdraw the agent, and "the
 * agent is still resolvable" cannot tell that apart from what we want.
 */
@SpringBootApplication
@MeshAgent(
    name = "hc-provider-a-java",
    version = "1.0.0",
    description = "Provider whose health check withdraws it from resolution (#1480)",
    port = 3431
)
public class HcProviderAApplication {

    static final String AGENT_NAME = "hc-provider-a-java";

    private static final Path FLAG_FILE = Path.of(
        System.getenv().getOrDefault("HC_FLAG_FILE", "/workspace/health-flag"));
    private static final Path TRACE_FILE = Path.of(
        System.getenv().getOrDefault("HC_TRACE_FILE", "/workspace/hc-invocations.log"));

    public static void main(String[] args) {
        SpringApplication.run(HcProviderAApplication.class, args);
    }

    @MeshTool(
        capability = "hc_probe_java",
        description = "Report which provider instance served this call",
        tags = {"hc-withdrawal"}
    )
    public Map<String, Object> probeA() {
        // pid is self-reported from inside the JVM, so it cannot go stale the
        // way a pid FILE can — and unlike meshctl's pid file it names the JVM
        // rather than the `mvn spring-boot:run` wrapper that forked it.
        // Baseline and post-recovery answers carrying the same pid is the
        // proof that recovery did not restart anything.
        return Map.of("served_by", AGENT_NAME, "pid", ProcessHandle.current().pid());
    }

    /**
     * Simulated upstream-vendor probe, driven by the flag file.
     *
     * <p>ttlSeconds = 2 so a withdrawal costs ~1 TTL plus the registry staleness
     * window rather than the 15s default; the test's registry runs at a matching
     * 5s/2s.
     */
    @MeshHealthCheck(ttlSeconds = 2)
    public MeshHealth vendorHealth() {
        String flag = readFlag();

        if ("fail".equals(flag)) {
            trace(flag, "unhealthy");
            return MeshHealth.unhealthy("simulated vendor outage (health-flag=fail)")
                .withCheck("vendor_api_reachable", false);
        }

        if ("throw".equals(flag)) {
            // Traced BEFORE throwing — see the class javadoc.
            trace(flag, "raised");
            throw new IllegalStateException(
                "simulated broken health check (health-flag=throw)");
        }

        trace(flag, "healthy");
        return MeshHealth.healthy().withCheck("vendor_api_reachable", true);
    }

    /** Current fault state. A missing file means healthy, so the agent boots green. */
    private static String readFlag() {
        try {
            String raw = Files.readString(FLAG_FILE, StandardCharsets.UTF_8).trim();
            return raw.isEmpty() ? "ok" : raw.toLowerCase();
        } catch (Exception e) {
            return "ok";
        }
    }

    /** Best-effort: a trace write that fails must not change the verdict. */
    private static void trace(String flag, String verdict) {
        String line = Instant.now() + " agent=" + AGENT_NAME
            + " flag=" + flag + " verdict=" + verdict + System.lineSeparator();
        try {
            Files.writeString(TRACE_FILE, line, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Exception ignored) {
            // ignore
        }
    }
}
