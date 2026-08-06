package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshStartupCheck;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.lang.reflect.Method;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * {@code GET}/{@code HEAD} {@code /startupz} — RFC #1502.
 *
 * <p>Java serves every agent type from one controller, so unlike Python and
 * TypeScript there is a single site to pin. What that costs is that the
 * per-agent-type rules live in branches rather than in separate files — the
 * gateway case below is asserted here rather than in a second test class.
 */
class MeshStartupzControllerTest {

    static class Checks {

        @MeshStartupCheck
        public boolean passes() {
            return true;
        }

        @MeshStartupCheck
        public boolean fails() {
            return false;
        }

        @MeshStartupCheck
        public boolean throwsUp() {
            throw new IllegalStateException("ANTHROPIC_API_KEY is not set");
        }

        @MeshStartupCheck
        public MeshHealth unhealthyWithDetail() {
            return MeshHealth.unhealthy("no key").withCheck("api_key_present", false);
        }
    }

    private static MeshStartupCheckRegistry withCheck(String methodName) {
        try {
            MeshStartupCheckRegistry registry = new MeshStartupCheckRegistry();
            Method method = Checks.class.getMethod(methodName);
            registry.register(new Checks(), method);
            return registry;
        } catch (NoSuchMethodException e) {
            throw new AssertionError(e);
        }
    }

    private static MeshRuntime runtimeOf(String agentType, boolean running) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(running);
        io.mcpmesh.core.AgentSpec spec = new io.mcpmesh.core.AgentSpec();
        spec.setName("agent");
        spec.setAgentType(agentType);
        when(runtime.getAgentSpec()).thenReturn(spec);
        return runtime;
    }

    private static MeshHealthController controller(MeshStartupCheckRegistry startup) {
        return new MeshHealthController(runtimeOf("mcp", true), null, startup);
    }

    @Test
    void noCheckDeclared_is200() {
        MeshHealthController c = controller(new MeshStartupCheckRegistry());
        ResponseEntity<Map<String, Object>> response = c.startupz();

        assertEquals(200, response.getStatusCode().value(),
            "an agent that declares no startup check must behave exactly as it does today");
        assertEquals(Boolean.TRUE, response.getBody().get("started"));
        assertEquals("agent", response.getBody().get("agent"));
        assertNotNull(response.getBody().get("timestamp"));
    }

    @Test
    void noRegistryAtAll_is200() {
        // The two-argument constructor (tests, hand-wiring) means no check.
        MeshHealthController c = new MeshHealthController(runtimeOf("mcp", true), null);
        assertEquals(200, c.startupz().getStatusCode().value());
        assertEquals(200, c.startupzHead().getStatusCode().value());
    }

    @Test
    void passingCheck_is200() {
        assertEquals(200, controller(withCheck("passes")).startupz().getStatusCode().value());
    }

    @Test
    void failingCheck_is503WithAReason() {
        ResponseEntity<Map<String, Object>> response =
            controller(withCheck("fails")).startupz();

        assertEquals(503, response.getStatusCode().value());
        assertEquals(Boolean.FALSE, response.getBody().get("started"));
        assertEquals("Startup check failed", response.getBody().get("reason"));
        assertNotNull(response.getBody().get("errors"));
    }

    @Test
    void throwingCheck_is503_notA500() {
        // The endpoint must not propagate the throw, and unlike health_check a
        // throw does NOT degrade into a pass.
        ResponseEntity<Map<String, Object>> response =
            controller(withCheck("throwsUp")).startupz();

        assertEquals(503, response.getStatusCode().value());
        assertTrue(response.getBody().get("errors").toString()
            .contains("ANTHROPIC_API_KEY is not set"));
    }

    @Test
    void theBodyCarriesEnoughToDiagnose() {
        ResponseEntity<Map<String, Object>> response =
            controller(withCheck("unhealthyWithDetail")).startupz();

        assertEquals(503, response.getStatusCode().value());
        @SuppressWarnings("unchecked")
        Map<String, Object> checks = (Map<String, Object>) response.getBody().get("checks");
        assertEquals(Boolean.FALSE, checks.get("api_key_present"));
        assertTrue(response.getBody().get("errors").toString().contains("no key"));
    }

    @Test
    void headMatchesGet() {
        MeshHealthController passing = controller(withCheck("passes"));
        assertEquals(passing.startupz().getStatusCode().value(),
            passing.startupzHead().getStatusCode().value());
        assertEquals(200, passing.startupzHead().getStatusCode().value());

        MeshHealthController failing = controller(withCheck("fails"));
        assertEquals(failing.startupz().getStatusCode().value(),
            failing.startupzHead().getStatusCode().value());
        assertEquals(503, failing.startupzHead().getStatusCode().value());
    }

    @Test
    void gatewaysAreNotExempt_unlikeTheHealthCheck() {
        // #1488 exempts api/a2a agents from readiness withdrawal by their own
        // health check. startup_check withdraws nothing — it only stops a
        // misconfigured gateway from coming up — so the exemption does not
        // apply to it.
        for (String agentType : java.util.List.of("api", "a2a")) {
            MeshHealthController c = new MeshHealthController(
                runtimeOf(agentType, true), null, withCheck("fails"));
            assertEquals(503, c.startupz().getStatusCode().value(),
                "'" + agentType + "' gateway with a broken config must not come up");
        }
    }

    @Test
    void doesNotConsultTheRuntime() {
        // The mesh runtime starts late in the Spring lifecycle, and startupProbe
        // exists to cover exactly that window. Flooring on isRunning() would
        // fail the probe for the whole boot it is meant to be waiting through.
        MeshRuntime runtime = mock(MeshRuntime.class);
        MeshHealthController c =
            new MeshHealthController(runtime, null, withCheck("passes"));

        assertEquals(200, c.startupz().getStatusCode().value());
        verify(runtime, never()).isRunning();
    }

    @Test
    void is200_whenTheLazyRuntimeProxyRaises() {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.getAgentSpec()).thenThrow(new IllegalStateException("bean not ready"));
        MeshHealthController c =
            new MeshHealthController(runtime, null, withCheck("passes"));

        ResponseEntity<Map<String, Object>> response = c.startupz();
        assertEquals(200, response.getStatusCode().value());
        assertNull(response.getBody().get("agent"));
    }

    @Test
    void livezStaysUnconditional() {
        MeshHealthController c = controller(withCheck("fails"));
        assertEquals(200, c.livez().getStatusCode().value());
        assertEquals(200, c.livezHead().getStatusCode().value());
    }

    @Test
    void readyIsUnchangedByAFailingStartupCheck() {
        // Step 1 is additive: /ready keeps reflecting the health verdict only.
        MeshHealthController c = controller(withCheck("fails"));
        assertEquals(200, c.ready().getStatusCode().value());
        assertEquals(200, c.health().getStatusCode().value());
    }
}
