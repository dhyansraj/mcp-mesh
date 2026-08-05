package io.mcpmesh.spring;

import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Unit tests for the probe endpoints (issue #1467).
 *
 * <p>The invariant under test: liveness and readiness are DIFFERENT signals.
 * {@code /ready} follows {@code runtime.isRunning()} so an agent whose runtime
 * is down is taken out of rotation; {@code /livez} answers 200 regardless, so
 * the same condition never causes a pod restart.
 */
class MeshHealthControllerTest {

    private static MeshRuntime runtimeWith(boolean running) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(running);
        return runtime;
    }

    @Test
    void livez_is200_whenRuntimeIsRunning() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(true));
        ResponseEntity<Map<String, Object>> response = controller.livez();

        assertEquals(200, response.getStatusCode().value());
        assertEquals(Boolean.TRUE, response.getBody().get("alive"));
        assertNotNull(response.getBody().get("timestamp"));
    }

    @Test
    void livez_is200_evenWhenRuntimeIsNotRunning() {
        // Unstubbed: isRunning() defaults to false AND the verify below proves
        // liveness never asked.
        MeshRuntime runtime = mock(MeshRuntime.class);
        MeshHealthController controller = new MeshHealthController(runtime);

        ResponseEntity<Map<String, Object>> response = controller.livez();

        assertEquals(200, response.getStatusCode().value(),
            "liveness must not restart an agent whose runtime is merely down/slow to boot");
        assertEquals(Boolean.TRUE, response.getBody().get("alive"));
        verify(runtime, never()).isRunning();
    }

    @Test
    void livez_is200_evenWithNoRuntimeAtAll() {
        MeshHealthController controller = new MeshHealthController(null);
        ResponseEntity<Map<String, Object>> response = controller.livez();

        assertEquals(200, response.getStatusCode().value());
        assertEquals(Boolean.TRUE, response.getBody().get("alive"));
    }

    @Test
    void livez_is200_whenTheLazyRuntimeProxyRaises() {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.getAgentSpec()).thenThrow(new IllegalStateException("bean not ready"));
        MeshHealthController controller = new MeshHealthController(runtime);

        ResponseEntity<Map<String, Object>> response = controller.livez();

        assertEquals(200, response.getStatusCode().value());
        assertEquals(Boolean.TRUE, response.getBody().get("alive"));
        assertFalse(response.getBody().containsKey("agent"));
    }

    @Test
    void livezHead_is200() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(false));
        assertEquals(200, controller.livezHead().getStatusCode().value());
    }

    @Test
    void ready_is200_whenRuntimeIsRunning() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(true));
        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(200, response.getStatusCode().value());
        assertEquals(Boolean.TRUE, response.getBody().get("ready"));
    }

    @Test
    void ready_is503_whenRuntimeIsNotRunning() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(false));
        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(503, response.getStatusCode().value());
        assertEquals(Boolean.FALSE, response.getBody().get("ready"));
        assertNotNull(response.getBody().get("reason"));
    }

    @Test
    void ready_is503_withNoRuntimeAtAll() {
        MeshHealthController controller = new MeshHealthController(null);
        assertEquals(503, controller.ready().getStatusCode().value());
    }

    @Test
    void readyHead_followsRuntimeState() {
        assertEquals(200, new MeshHealthController(runtimeWith(true)).readyHead()
            .getStatusCode().value());
        assertEquals(503, new MeshHealthController(runtimeWith(false)).readyHead()
            .getStatusCode().value());
    }

    @Test
    void livenessAndReadinessDivergeWhenTheRuntimeIsDown() {
        // The whole point of #1467: the same condition must be able to take an
        // agent out of rotation without restarting it.
        MeshHealthController controller = new MeshHealthController(runtimeWith(false));
        assertEquals(503, controller.ready().getStatusCode().value());
        assertEquals(200, controller.livez().getStatusCode().value());
    }

    @Test
    void health_isUnchanged() {
        assertEquals(200, new MeshHealthController(runtimeWith(true)).health()
            .getStatusCode().value());
        assertEquals(503, new MeshHealthController(runtimeWith(false)).health()
            .getStatusCode().value());
    }

    // ---- @MeshHealthCheck reflection (issue #1474) --------------------------

    private static MeshHealthCheckRegistry withVerdict(io.mcpmesh.MeshHealth health) {
        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        registry.store(health);
        return registry;
    }

    @Test
    void ready_is503_whenTheUserHealthCheckIsUnhealthy() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.unhealthy("anthropic API unreachable")));

        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(503, response.getStatusCode().value());
        assertEquals(Boolean.FALSE, response.getBody().get("ready"));
        assertEquals("unhealthy", response.getBody().get("status"));
        assertEquals("service is unhealthy", response.getBody().get("reason"));
        assertEquals(java.util.List.of("anthropic API unreachable"),
            response.getBody().get("errors"));
        assertEquals(503, controller.readyHead().getStatusCode().value());
    }

    @Test
    void ready_is503_whenTheUserHealthCheckIsDegraded() {
        // Python parity: build_ready_response / build_health_response are
        // `200 if status == "healthy" else 503`. Degraded therefore leaves the
        // load balancer while STILL heartbeating and staying in dependency
        // resolution — readiness is about new external traffic, the heartbeat
        // is about whether this is still a valid mesh provider.
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.degraded("elevated latency")));

        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(503, response.getStatusCode().value());
        assertEquals(Boolean.FALSE, response.getBody().get("ready"));
        assertEquals("degraded", response.getBody().get("status"));
        assertEquals("service is degraded", response.getBody().get("reason"));
        assertEquals(503, controller.health().getStatusCode().value());
    }

    @Test
    void ready_is503_whenTheRuntimeIsDownEvenIfTheCheckSaysHealthy() {
        // The runtime state is the FLOOR: a vendor probe says nothing about
        // whether this agent is registered and reachable.
        MeshHealthController controller = new MeshHealthController(runtimeWith(false),
            withVerdict(io.mcpmesh.MeshHealth.healthy()));

        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(503, response.getStatusCode().value());
        assertEquals("mesh runtime is not running", response.getBody().get("reason"));
    }

    @Test
    void health_carriesChecksAndErrors() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.unhealthy("ANTHROPIC_API_KEY not set")
                .withCheck("anthropic_api_key_present", false)));

        ResponseEntity<Map<String, Object>> response = controller.health();

        assertEquals(503, response.getStatusCode().value());
        assertEquals("unhealthy", response.getBody().get("status"));
        assertEquals(Map.of("anthropic_api_key_present", false),
            response.getBody().get("checks"));
        assertEquals(java.util.List.of("ANTHROPIC_API_KEY not set"),
            response.getBody().get("errors"));
        assertNotNull(response.getBody().get("timestamp"));
        assertEquals(503, controller.healthHead().getStatusCode().value());
    }

    @Test
    void probes_areUnaffectedBeforeTheFirstCheckRuns() {
        // Registry present but nothing stored yet (boot). The agent must not be
        // 503 just because its first health-check tick has not landed.
        MeshHealthController controller =
            new MeshHealthController(runtimeWith(true), new MeshHealthCheckRegistry());

        assertEquals(200, controller.ready().getStatusCode().value());
        assertEquals(200, controller.health().getStatusCode().value());
        assertFalse(controller.health().getBody().containsKey("checks"));
    }

    @Test
    void livez_is200_evenWhenTheUserHealthCheckIsUnhealthy() {
        // The #1467 invariant, extended: a vendor outage must never restart the
        // pod — a restart cannot fix the vendor and erases the evidence.
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.unhealthy("vendor down")));

        assertEquals(200, controller.livez().getStatusCode().value());
        assertEquals(200, controller.livezHead().getStatusCode().value());
        assertEquals(503, controller.ready().getStatusCode().value());
    }
}
