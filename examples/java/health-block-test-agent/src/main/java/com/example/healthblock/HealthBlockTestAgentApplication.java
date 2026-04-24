package com.example.healthblock;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * health-block-test-agent (Java) — Regression coverage for /health responsiveness.
 *
 * <p>Java's MCP Mesh runtime is built on Spring Boot + embedded Tomcat. Tomcat
 * uses a thread-pool model where each incoming HTTP request is serviced on its
 * own worker thread. A long-running tool invocation that blocks on
 * {@link Thread#sleep(long)} therefore parks one worker thread — but the
 * remaining workers stay free to serve {@code /health} and {@code /ready}
 * probes.
 *
 * <p>The Python and TypeScript runtimes do <em>not</em> have this property
 * out of the box (single event loop). This agent exists so that future
 * refactors of the Java runtime (e.g. moving to a reactive / single-thread
 * model) cannot silently regress the current responsiveness guarantee.
 */
@MeshAgent(
    name = "health-block-test-agent",
    version = "1.0.0",
    description = "Regression coverage: Java /health stays responsive during blocking tool calls",
    port = 9097
)
@SpringBootApplication
public class HealthBlockTestAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(HealthBlockTestAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Health Block Test Agent (Java)...");
        SpringApplication.run(HealthBlockTestAgentApplication.class, args);
    }

    /**
     * Blocks the calling request thread for the requested number of seconds.
     * Mirrors the Python / TypeScript reproducers: time.sleep / sleep N.
     */
    @MeshTool(
        capability = "busy_tool_java",
        description = "Blocks the calling request thread via Thread.sleep — used to verify Tomcat keeps /health responsive"
    )
    public String busyToolJava(
        @Param(value = "seconds", description = "Seconds to block this request thread") int seconds
    ) {
        log.info("busyToolJava called with seconds={}", seconds);
        try {
            Thread.sleep(seconds * 1000L);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return "interrupted after partial sleep";
        }
        return "slept " + seconds + "s (blocking)";
    }

    /**
     * Sanity-check tool — returns immediately so the test can confirm
     * the agent is reachable before kicking off the blocking call.
     */
    @MeshTool(
        capability = "quick_tool_java",
        description = "Returns immediately — sanity check that the MCP endpoint is wired up"
    )
    public String quickToolJava() {
        return "ok";
    }
}
