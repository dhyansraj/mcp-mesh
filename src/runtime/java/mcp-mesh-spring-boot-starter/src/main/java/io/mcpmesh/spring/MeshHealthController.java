package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.stereotype.Controller;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Health endpoint controller for MCP Mesh Java agents.
 *
 * <p>Provides {@code GET}/{@code HEAD} for {@code /health}, {@code /ready} and
 * {@code /livez} for Kubernetes probes, load balancers, and Docker Compose
 * healthchecks.
 *
 * <p>Liveness and readiness are deliberately DIFFERENT endpoints (issue #1467).
 * When both probes share a URL, anything that makes an agent unready also makes
 * Kubernetes restart it — a remedy that cannot fix a dependency outage and that
 * erases the evidence the agent was failing. {@code /livez} therefore answers
 * 200 unconditionally, while {@code /ready} reports whether the agent should be
 * receiving traffic.
 *
 * <p>Since issue #1474 {@code /ready} also reflects the user's
 * {@link io.mcpmesh.MeshHealthCheck}, and {@code /health} carries its
 * {@code checks} and {@code errors} so an operator can see WHICH probe failed.
 * The runtime state remains the floor: an agent whose mesh runtime is not up is
 * not ready regardless of what the user's check says.
 */
@Controller
public class MeshHealthController {

    private final MeshRuntime runtime;
    private final MeshHealthCheckRegistry healthChecks;

    public MeshHealthController(MeshRuntime runtime) {
        this(runtime, null);
    }

    public MeshHealthController(MeshRuntime runtime, MeshHealthCheckRegistry healthChecks) {
        this.runtime = runtime;
        this.healthChecks = healthChecks;
    }

    /**
     * The effective verdict: the user's health check, floored by the mesh
     * runtime state.
     *
     * <p>The floor is not redundant with the user's check. A check that probes
     * a vendor API says nothing about whether this agent is registered and
     * reachable; a runtime that is down means no traffic should arrive here
     * whatever the vendor's status is. Taking the worse of the two is the only
     * answer that is true in both directions.
     */
    private MeshHealthStatus effectiveStatus() {
        boolean running = runtime != null && runtime.isRunning();
        if (!running) {
            return MeshHealthStatus.UNHEALTHY;
        }
        MeshHealth latest = latestHealth();
        return latest == null ? MeshHealthStatus.HEALTHY : latest.status();
    }

    private MeshHealth latestHealth() {
        if (healthChecks == null) {
            return null;
        }
        MeshHealthCheckRegistry.Result result = healthChecks.latest();
        return result == null ? null : result.health();
    }

    /**
     * Whether the probes answer 200. Only {@link MeshHealthStatus#HEALTHY}
     * does — exactly Python's {@code build_health_response} /
     * {@code build_ready_response}, which are {@code 200 if status ==
     * "healthy" else 503}.
     *
     * <p>So {@code degraded} answers 503 here while the agent keeps
     * heartbeating and stays in dependency resolution. That asymmetry is
     * Python's and is deliberate on both sides: readiness is a load-balancer
     * decision about NEW external traffic, while the heartbeat is a statement
     * about whether this agent is still a valid provider for the mesh. An
     * impaired agent can honestly answer "stop adding load" without also
     * withdrawing itself from a mesh that may have no other provider.
     */
    private static boolean serving(MeshHealthStatus status) {
        return status == MeshHealthStatus.HEALTHY;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        MeshHealthStatus status = effectiveStatus();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", status.wireValue());
        if (runtime != null && runtime.getAgentSpec() != null) {
            body.put("agent", runtime.getAgentSpec().getName());
        }
        MeshHealthCheckRegistry.Result result =
            healthChecks == null ? null : healthChecks.latest();
        if (result != null) {
            body.put("checks", result.health().checks());
            body.put("errors", result.health().errors());
            body.put("timestamp", result.timestamp().toString());
        }
        return ResponseEntity.status(serving(status) ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/health", method = RequestMethod.HEAD)
    public ResponseEntity<Void> healthHead() {
        return ResponseEntity.status(serving(effectiveStatus()) ? 200 : 503).build();
    }

    /**
     * Kubernetes readiness probe.
     *
     * <p>Reports whether traffic should be routed here: the mesh runtime is up
     * AND the user's {@link io.mcpmesh.MeshHealthCheck} (if any) is not
     * reporting unhealthy. It does NOT restart anything — see the class comment
     * on why this is a separate endpoint from {@code /livez}.
     */
    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        boolean running = runtime != null && runtime.isRunning();
        MeshHealthStatus status = effectiveStatus();
        boolean ready = serving(status);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ready", ready);
        body.put("status", status.wireValue());
        if (!ready) {
            body.put("reason", running
                ? "service is " + status.wireValue()
                : "mesh runtime is not running");
            MeshHealth latest = latestHealth();
            if (latest != null && !latest.errors().isEmpty()) {
                body.put("errors", latest.errors());
            }
        }
        return ResponseEntity.status(ready ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/ready", method = RequestMethod.HEAD)
    public ResponseEntity<Void> readyHead() {
        return ResponseEntity.status(serving(effectiveStatus()) ? 200 : 503).build();
    }

    /**
     * Kubernetes liveness probe — always 200 while the application is serving.
     *
     * <p>Deliberately does NOT consult {@link MeshRuntime#isRunning()} or the
     * user's health check: the mesh runtime starts late in the Spring
     * lifecycle, so a liveness probe gated on it would restart-loop an agent
     * through a slow boot, and a restart cannot fix a vendor outage — it only
     * erases the evidence. Reaching this handler at all proves the servlet
     * container is alive, which is the only failure a restart can repair.
     */
    @GetMapping("/livez")
    public ResponseEntity<Map<String, Object>> livez() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("alive", true);
        // Best-effort agent name. `runtime` is a lazy proxy — resolving it can
        // raise while the context is still coming up, and liveness must answer
        // 200 regardless of whether the name is available.
        try {
            if (runtime != null && runtime.getAgentSpec() != null) {
                body.put("agent", runtime.getAgentSpec().getName());
            }
        } catch (Exception ignored) {
            // Name is decoration; liveness is not conditional on it.
        }
        body.put("timestamp", Instant.now().toString());
        return ResponseEntity.ok(body);
    }

    @RequestMapping(value = "/livez", method = RequestMethod.HEAD)
    public ResponseEntity<Void> livezHead() {
        return ResponseEntity.ok().build();
    }
}
