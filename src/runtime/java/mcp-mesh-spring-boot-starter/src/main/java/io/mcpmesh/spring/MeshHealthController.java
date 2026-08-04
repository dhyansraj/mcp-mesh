package io.mcpmesh.spring;

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
 * 200 unconditionally, while {@code /ready} reports whether the mesh runtime is
 * up.
 */
@Controller
public class MeshHealthController {

    private final MeshRuntime runtime;

    public MeshHealthController(MeshRuntime runtime) {
        this.runtime = runtime;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        boolean running = runtime != null && runtime.isRunning();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", running ? "healthy" : "unhealthy");
        if (runtime != null && runtime.getAgentSpec() != null) {
            body.put("agent", runtime.getAgentSpec().getName());
        }
        return ResponseEntity.status(running ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/health", method = RequestMethod.HEAD)
    public ResponseEntity<Void> healthHead() {
        boolean running = runtime != null && runtime.isRunning();
        return ResponseEntity.status(running ? 200 : 503).build();
    }

    /**
     * Kubernetes readiness probe.
     *
     * <p>The Java runtime has no user-supplied health check (unlike Python), so
     * the only honest readiness signal available is whether the mesh runtime is
     * running — the same condition {@code /health} reports. It does NOT reflect
     * the health of anything the agent depends on.
     */
    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        boolean running = runtime != null && runtime.isRunning();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ready", running);
        if (!running) {
            body.put("reason", "mesh runtime is not running");
        }
        return ResponseEntity.status(running ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/ready", method = RequestMethod.HEAD)
    public ResponseEntity<Void> readyHead() {
        boolean running = runtime != null && runtime.isRunning();
        return ResponseEntity.status(running ? 200 : 503).build();
    }

    /**
     * Kubernetes liveness probe — always 200 while the application is serving.
     *
     * <p>Deliberately does NOT consult {@link MeshRuntime#isRunning()}: the mesh
     * runtime starts late in the Spring lifecycle, so a liveness probe gated on
     * it would restart-loop an agent through a slow boot. Reaching this handler
     * at all proves the servlet container is alive, which is the only failure a
     * restart can actually repair.
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
