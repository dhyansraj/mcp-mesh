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
}
