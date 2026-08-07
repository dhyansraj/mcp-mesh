package io.mcpmesh.spring;

import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Unit tests for the probe endpoints (issue #1467, RFC #1502).
 *
 * <p>Two invariants, and they are separate:
 *
 * <ul>
 *   <li>liveness and readiness are DIFFERENT signals. {@code /ready} follows
 *       {@code runtime.isRunning()} so an agent whose runtime is down is taken
 *       out of rotation; {@code /livez} answers 200 regardless, so the same
 *       condition never causes a pod restart (#1467).
 *   <li>readiness and the health VERDICT are different signals too. The
 *       runtime state is all {@code /ready} reports, on every agent type; a
 *       failing {@link io.mcpmesh.MeshHealthCheck} withdraws the agent by
 *       pausing the heartbeat and never touches this probe (RFC #1502). It
 *       still drives {@code /health}, which nothing probes.
 * </ul>
 */
class MeshHealthControllerTest {

    private static MeshRuntime runtimeWith(boolean running) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(running);
        return runtime;
    }

    /** A runtime of a given agent type, as the probes see it. */
    private static MeshRuntime runtimeOf(String agentType, boolean running) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(running);
        io.mcpmesh.core.AgentSpec spec = new io.mcpmesh.core.AgentSpec();
        spec.setName("gateway");
        spec.setAgentType(agentType);
        when(runtime.getAgentSpec()).thenReturn(spec);
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
    void ready_is200_whenTheUserHealthCheckIsUnhealthy() {
        // RFC #1502. The heartbeat pause is the whole withdrawal mechanism; a
        // 503 here would ALSO empty the Kubernetes Service the mesh routes
        // through, so a consumer calling the withdrawn agent before the
        // registry sweeps gets a connection error instead of a failover.
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.unhealthy("anthropic API unreachable")));

        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(200, response.getStatusCode().value());
        assertEquals(Boolean.TRUE, response.getBody().get("ready"));
        assertFalse(response.getBody().containsKey("reason"));
        assertFalse(response.getBody().containsKey("errors"),
            "/ready must not carry the health check's errors — it did not consult it");
        assertEquals(200, controller.readyHead().getStatusCode().value());

        // ...and the verdict is still visible where an operator looks for it.
        assertEquals(503, controller.health().getStatusCode().value());
        assertEquals("unhealthy", controller.health().getBody().get("status"));
    }

    @Test
    void ready_is200_whenTheUserHealthCheckIsDegraded() {
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.degraded("elevated latency")));

        assertEquals(200, controller.ready().getStatusCode().value());
        assertEquals(200, controller.readyHead().getStatusCode().value());

        // /health is unchanged: Python parity, `200 if status == "healthy"
        // else 503`. Nothing probes it, so the status code is free to carry
        // the verdict.
        assertEquals(503, controller.health().getStatusCode().value());
        assertEquals("degraded", controller.health().getBody().get("status"));
    }

    @Test
    void ready_is503_whenTheRuntimeIsDownEvenIfTheCheckSaysHealthy() {
        // The runtime state is all readiness reports, and it is not vestigial:
        // MeshStartupCheck defaults to passing, so /startupz answers 200 before
        // the mesh runtime has started in the Spring lifecycle. Without this a
        // pod would go Ready with no runtime behind it, and /livez — which
        // consults nothing — would never notice a runtime that died either.
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

    // ---- no agent type is taken out of Service endpoints by its own check ----
    //
    // These started as the #1488 gateway carve-out. RFC #1502 generalised it:
    // the rule is the same for every agent type now, so the pairs below assert
    // the SAME behaviour for gateways and providers. They are kept apart
    // because a future change that reintroduces a per-type branch has to fail
    // one of them, and which one it fails names the direction of the mistake.

    @Test
    void gateway_ready_is200_whenTheUserHealthCheckIsUnhealthy() {
        // A gateway is a fan-out point. Suppressing its heartbeat is already
        // forbidden (MeshAgentTypes.isGateway); answering 503 on /ready reaches the same
        // outcome by another route, because the chart's readiness probe points
        // there and Kubernetes drops the pod from its Service endpoints.
        for (String agentType : java.util.List.of("api", "a2a")) {
            MeshHealthController controller = new MeshHealthController(
                runtimeOf(agentType, true),
                withVerdict(io.mcpmesh.MeshHealth.unhealthy("upstream down")));

            ResponseEntity<Map<String, Object>> response = controller.ready();

            assertEquals(200, response.getStatusCode().value(),
                "'" + agentType + "' agent must stay in Service endpoints");
            assertEquals(Boolean.TRUE, response.getBody().get("ready"));
            assertEquals(200, controller.readyHead().getStatusCode().value(),
                "HEAD /ready must agree with GET on an '" + agentType + "' agent");
        }
    }

    @Test
    void gateway_ready_is200_whenTheUserHealthCheckIsDegraded() {
        for (String agentType : java.util.List.of("api", "a2a")) {
            MeshHealthController controller = new MeshHealthController(
                runtimeOf(agentType, true),
                withVerdict(io.mcpmesh.MeshHealth.degraded("elevated latency")));

            assertEquals(200, controller.ready().getStatusCode().value(),
                "'" + agentType + "' agent must stay in Service endpoints");
            assertEquals(200, controller.readyHead().getStatusCode().value());
        }
    }

    @Test
    void gateway_health_stillCarriesTheVerdict() {
        // /health is the one place an operator can see what a gateway's check
        // reports. Nothing probes it — the chart points startup and liveness at
        // /livez and readiness at /ready — so carrying the verdict costs nothing.
        for (String agentType : java.util.List.of("api", "a2a")) {
            MeshHealthController controller = new MeshHealthController(
                runtimeOf(agentType, true),
                withVerdict(io.mcpmesh.MeshHealth.unhealthy("upstream down")
                    .withCheck("upstream_reachable", false)));

            ResponseEntity<Map<String, Object>> response = controller.health();

            assertEquals(503, response.getStatusCode().value());
            assertEquals("unhealthy", response.getBody().get("status"));
            assertEquals(Map.of("upstream_reachable", false),
                response.getBody().get("checks"));
            assertEquals(java.util.List.of("upstream down"),
                response.getBody().get("errors"));
            assertEquals(503, controller.healthHead().getStatusCode().value());
        }
    }

    @Test
    void gateway_ready_is503_whenTheRuntimeIsNotRunning() {
        // The runtime state is still the floor: a gateway whose mesh runtime is
        // down cannot serve, and that is not the user's check talking.
        MeshHealthController controller = new MeshHealthController(
            runtimeOf("api", false), withVerdict(io.mcpmesh.MeshHealth.healthy()));

        ResponseEntity<Map<String, Object>> response = controller.ready();

        assertEquals(503, response.getStatusCode().value());
        assertEquals("mesh runtime is not running", response.getBody().get("reason"));
        assertEquals(503, controller.readyHead().getStatusCode().value());
    }

    @Test
    void nonGateway_ready_is200_whenTheUserHealthCheckIsUnhealthy() {
        // A provider withdraws by GOING QUIET, not by leaving its Service. The
        // registry ages it out on the missing heartbeat and resolution stops
        // selecting it; the pod keeps its endpoint so an in-flight consumer
        // gets an answer rather than a refused connection.
        for (String agentType : java.util.List.of("mcp", "mcp_agent")) {
            MeshHealthController controller = new MeshHealthController(
                runtimeOf(agentType, true),
                withVerdict(io.mcpmesh.MeshHealth.unhealthy("vendor 503")));

            ResponseEntity<Map<String, Object>> response = controller.ready();

            assertEquals(200, response.getStatusCode().value(),
                "'" + agentType + "' agent must stay in Service endpoints");
            assertEquals(Boolean.TRUE, response.getBody().get("ready"));
            assertEquals(200, controller.readyHead().getStatusCode().value());
            assertEquals(503, controller.health().getStatusCode().value(),
                "'" + agentType + "' agent's /health must still carry the verdict");
        }
    }

    @Test
    void everyProbeIsUnmovedByAnUnhealthyCheckExceptHealth() {
        // The #1467 invariant, extended by RFC #1502: a vendor outage must move
        // exactly ONE endpoint. Asserted together so a change that quietly
        // rewires any of the four has to edit this line.
        MeshHealthController controller = new MeshHealthController(runtimeWith(true),
            withVerdict(io.mcpmesh.MeshHealth.unhealthy("vendor down")));

        assertEquals(200, controller.livez().getStatusCode().value(),
            "a restart cannot fix the vendor and erases the evidence");
        assertEquals(200, controller.livezHead().getStatusCode().value());
        assertEquals(200, controller.ready().getStatusCode().value(),
            "the heartbeat pause withdraws the agent; readiness must not also "
                + "empty the Service the mesh routes through");
        assertEquals(200, controller.startupz().getStatusCode().value(),
            "startup answers the 'will this ever work' question, not this one");
        assertEquals(503, controller.health().getStatusCode().value(),
            "the diagnostic view is where the verdict shows");
    }
}
