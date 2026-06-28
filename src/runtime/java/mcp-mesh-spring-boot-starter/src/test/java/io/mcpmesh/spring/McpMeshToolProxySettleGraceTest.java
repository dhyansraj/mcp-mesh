package io.mcpmesh.spring;

import io.mcpmesh.types.MeshToolUnavailableException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Type;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Settling-window grace on the {@code @MeshDependsOn} bean-injected proxy
 * path (issue #1193 extension).
 *
 * <p>An {@code McpMeshTool} proxy injected into a {@code @Service}/{@code @Component}
 * via {@code @MeshDependsOn} (registered by {@link MeshCapabilityBeanRegistrar})
 * is the SAME shared per-capability proxy the {@code @MeshRoute} path uses.
 * Before this fix, the bean-injected path got NO settle grace: the bean's
 * first {@code .call()} at startup hit {@link McpMeshToolProxy#call(Map)}
 * which threw {@link MeshToolUnavailableException} immediately, while the
 * route/tool paths waited out the settle budget.
 *
 * <p>These tests assert the proxy now performs the same bounded,
 * capability-keyed wait: a call firing while the proxy is unavailable and the
 * agent is still settling BLOCKS (bounded by the remaining settle budget) and
 * proceeds EARLY when the endpoint lands mid-wait — rather than throwing.
 * Once settled, the call fails fast exactly as before.
 *
 * <p>Mirrors the {@link MeshSettleStateTest} harness ({@code resetForTests},
 * a resolver thread that lands the endpoint mid-wait).
 */
class McpMeshToolProxySettleGraceTest {

    @AfterEach
    void resetSettleState() {
        MeshSettleState.resetForTests();
    }

    /** Stub HTTP client: returns a sentinel and records that it was invoked. */
    static class StubHttpClient extends McpHttpClient {
        static final String SENTINEL = "called-after-settle";
        final AtomicReference<String> lastEndpoint = new AtomicReference<>();

        @Override
        @SuppressWarnings("unchecked")
        public <T> T callTool(String endpoint, String functionName, Map<String, Object> params,
                              Type returnType) {
            lastEndpoint.set(endpoint);
            return (T) SENTINEL;
        }
    }

    @Test
    void beanInjectedProxy_waitsThenSucceeds_whenEndpointLandsMidWait() throws Exception {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        // @MeshDependsOn registers the capability key at bean-registration
        // time; the bean-injected proxy waits on the SAME capability key
        // that updateToolDependency.markResolved counts down.
        state.registerDeclared("remote_cap");

        StubHttpClient http = new StubHttpClient();
        McpMeshToolProxy<String> proxy = new McpMeshToolProxy<>("remote_cap", http);
        // Proxy starts unavailable (no endpoint) — exactly the startup state
        // a @MeshDependsOn bean sees before the first heartbeat resolves it.
        assertFalse(proxy.isAvailable());

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            // Mirror MeshDependencyInjector.updateToolDependency: make the
            // endpoint live, THEN count the capability latch down.
            proxy.updateEndpoint("http://localhost:1/mcp", "remote_fn");
            state.markResolved("remote_cap");
        });
        resolver.start();

        long start = System.nanoTime();
        // Pre-fix this threw MeshToolUnavailableException immediately.
        String result = proxy.call(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        assertEquals(StubHttpClient.SENTINEL, result,
            "bean-injected proxy must wait out the settle window and then call the resolved endpoint");
        assertEquals("http://localhost:1/mcp", http.lastEndpoint.get());
        assertTrue(elapsedMs >= 100, "expected an actual settle wait, got " + elapsedMs + "ms");
        assertTrue(elapsedMs < 5000, "unblocked by the resolution event, not the budget ceiling");
        assertTrue(state.getWaitCount() >= 1, "the unavailable proxy call must trigger the settle wait");
    }

    @Test
    void beanInjectedProxy_failsFastOnceSettled() {
        // timeout=0 → permanently settled. The grace must be a no-op and the
        // call must fail fast exactly as the pre-grace behavior.
        MeshSettleState.resetForTests(0.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("remote_cap");
        assertTrue(state.isSettled());

        McpMeshToolProxy<String> proxy = new McpMeshToolProxy<>("remote_cap", new StubHttpClient());

        long start = System.nanoTime();
        assertThrows(MeshToolUnavailableException.class, () -> proxy.call(Map.of("q", "x")),
            "settled agent: an unresolved dependency must fail fast, not wait");
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertTrue(elapsedMs < 50, "settled call must not wait, waited " + elapsedMs + "ms");
        assertEquals(0, state.getWaitCount(),
            "settled steady-state must never touch the wait primitives");
    }

    @Test
    void beanInjectedProxy_timesOutToUnavailableWhenEndpointNeverLands() {
        // The dep never resolves within the (tiny) budget → after the bounded
        // wait the call falls through to today's fail-fast unavailable error.
        MeshSettleState.resetForTests(0.3);
        MeshSettleState.getInstance().registerDeclared("remote_cap");

        McpMeshToolProxy<String> proxy = new McpMeshToolProxy<>("remote_cap", new StubHttpClient());

        long start = System.nanoTime();
        assertThrows(MeshToolUnavailableException.class, () -> proxy.call(Map.of("q", "x")));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertTrue(elapsedMs >= 200,
            "expected a wait toward the budget before failing, got " + elapsedMs + "ms");
    }

    @Test
    void availableProxy_neverWaits() {
        // Already-resolved proxy → the settle path is short-circuited; no
        // wait primitives touched even while the window is open.
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("remote_cap");

        StubHttpClient http = new StubHttpClient();
        McpMeshToolProxy<String> proxy = new McpMeshToolProxy<>("remote_cap", http);
        proxy.updateEndpoint("http://localhost:1/mcp", "remote_fn");

        long start = System.nanoTime();
        assertEquals(StubHttpClient.SENTINEL, proxy.call(Map.of("q", "x")));
        assertTrue((System.nanoTime() - start) / 1_000_000 < 100);
        assertEquals(0, state.getWaitCount(),
            "an available proxy must never touch the settle wait primitives");
    }
}
