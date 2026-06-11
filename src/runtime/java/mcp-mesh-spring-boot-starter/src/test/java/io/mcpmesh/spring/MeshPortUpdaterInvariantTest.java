package io.mcpmesh.spring;

import io.mcpmesh.core.AgentSpec;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.server.WebServer;
import org.springframework.boot.web.server.context.WebServerInitializedEvent;
import org.springframework.context.ApplicationListener;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the registered-port == bound-port invariant for the Java runtime
 * (issue #1194).
 *
 * <p>Java relies on two mechanisms for the invariant:
 *
 * <ol>
 *   <li>Spring Boot fails startup loudly on a port conflict (the web server
 *       binds during {@code WebServerStartStopLifecycle}); the failed context
 *       stops {@link MeshRuntime}, which closes the mesh handle and withdraws
 *       any registration. No silent phantom endpoint survives.</li>
 *   <li>The {@code meshPortUpdater} {@link ApplicationListener} converges the
 *       registered port to the ACTUAL bound port whenever the web server
 *       reports a port different from the spec (covers {@code server.port=0}
 *       auto-assignment and any other divergence).</li>
 * </ol>
 *
 * <p>This test pins mechanism (2) — the mcp-mesh-owned half.
 */
class MeshPortUpdaterInvariantTest {

    private ApplicationListener<WebServerInitializedEvent> listener(MeshRuntime runtime) {
        return new MeshAutoConfiguration().meshPortUpdater(runtime);
    }

    private WebServerInitializedEvent eventWithPort(int actualPort) {
        WebServer webServer = mock(WebServer.class);
        when(webServer.getPort()).thenReturn(actualPort);
        WebServerInitializedEvent event = mock(WebServerInitializedEvent.class);
        when(event.getWebServer()).thenReturn(webServer);
        return event;
    }

    private MeshRuntime runtimeWithSpecPort(int specPort) {
        AgentSpec spec = new AgentSpec();
        spec.setHttpPort(specPort);
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.getAgentSpec()).thenReturn(spec);
        return runtime;
    }

    @Test
    void updatesRegistryWhenActualPortDiffersFromSpec() {
        MeshRuntime runtime = runtimeWithSpecPort(9000);

        listener(runtime).onApplicationEvent(eventWithPort(54321));

        // The actual bound port is authoritative — the registry must be
        // converged to it, never left advertising the spec port.
        verify(runtime).updatePort(54321);
    }

    @Test
    void updatesRegistryForPortZeroAutoAssignment() {
        MeshRuntime runtime = runtimeWithSpecPort(0);

        listener(runtime).onApplicationEvent(eventWithPort(43210));

        verify(runtime).updatePort(43210);
    }

    @Test
    void noUpdateWhenSpecAlreadyMatchesBoundPort() {
        MeshRuntime runtime = runtimeWithSpecPort(8080);

        listener(runtime).onApplicationEvent(eventWithPort(8080));

        // No update call at all — not merely "no update with this value".
        verify(runtime, never()).updatePort(anyInt());
    }
}
