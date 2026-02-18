package io.mcpmesh.spring;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.stereotype.Controller;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Health endpoint controller for MCP Mesh Java agents.
 *
 * <p>Provides {@code GET /health} and {@code HEAD /health} for Kubernetes probes,
 * load balancers, and Docker Compose healthchecks.
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
}
