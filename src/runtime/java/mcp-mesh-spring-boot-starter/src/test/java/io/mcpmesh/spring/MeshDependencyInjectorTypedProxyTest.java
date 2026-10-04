package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Issue #1568 A: {@link MeshDependencyInjector#getToolProxy(String, Type)} used
 * to hand every caller the SAME per-capability proxy and overwrite its return
 * type on each call. Two consumers of one capability that declare different
 * {@code McpMeshTool<T>} — two route handlers, a route and a {@code @Qualifier}
 * bean, two {@code @MeshService} view methods — then raced on the
 * deserialization type. Each declared type must now govern its own calls, while
 * endpoint and availability changes still reach every typed handle.
 */
@DisplayName("#1568 A: injector hands out per-return-type proxies over one shared endpoint")
class MeshDependencyInjectorTypedProxyTest {

    record Alpha(String a) {}
    record Beta(String b) {}

    /** Echoes the return type it was asked to deserialize into, and the endpoint. */
    static class TypeEchoClient extends McpHttpClient {
        @Override
        @SuppressWarnings("unchecked")
        public <T> T callTool(String endpoint, String functionName, Map<String, Object> params,
                              Type returnType) {
            return (T) new Seen(endpoint, functionName, returnType);
        }
    }

    record Seen(String endpoint, String functionName, Type returnType) {}

    private MeshDependencyInjector injector;

    @BeforeEach
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        McpHttpClient client = new TypeEchoClient();
        McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
        injector = new MeshDependencyInjector(client, factory, new ToolInvoker(factory));
    }

    @AfterEach
    void tearDown() {
        MeshSettleState.resetForTests();
    }

    private static Seen call(McpMeshTool<?> tool) {
        return (Seen) tool.call(Map.of());
    }

    @Test
    @DisplayName("a later consumer's type does not rewrite an earlier consumer's proxy")
    void laterTypeDoesNotRewriteEarlierProxy() {
        injector.updateToolDependency("cap", "http://ep-1", "fn");

        McpMeshTool<?> alpha = injector.getToolProxy("cap", Alpha.class);
        McpMeshTool<?> beta = injector.getToolProxy("cap", Beta.class);

        assertEquals(Alpha.class, call(alpha).returnType(),
            "the Alpha consumer's call must deserialize into Alpha, not the type the "
                + "Beta consumer requested afterwards");
        assertEquals(Beta.class, call(beta).returnType());
    }

    @Test
    @DisplayName("interleaved concurrent consumers of one capability each keep their own type")
    void interleavedConcurrentConsumersKeepTheirType() throws Exception {
        injector.updateToolDependency("cap", "http://ep-1", "fn");
        int iterations = 2_000;
        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch start = new CountDownLatch(1);
        try {
            List<Future<Integer>> results = new ArrayList<>();
            for (Type type : List.of(Alpha.class, Beta.class)) {
                results.add(pool.submit(() -> {
                    start.await();
                    int wrong = 0;
                    for (int i = 0; i < iterations; i++) {
                        // The per-request shape of MeshRouteHandlerInterceptor:
                        // look the proxy up, then call it.
                        McpMeshTool<?> tool = injector.getToolProxy("cap", type);
                        if (!type.equals(call(tool).returnType())) {
                            wrong++;
                        }
                    }
                    return wrong;
                }));
            }
            start.countDown();
            for (Future<Integer> f : results) {
                assertEquals(0, f.get(30, TimeUnit.SECONDS),
                    "a call deserialized into the other consumer's type");
            }
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("same type yields the same stable instance; distinct types yield distinct ones")
    void instanceIdentity() {
        assertSame(injector.getToolProxy("cap", Alpha.class), injector.getToolProxy("cap", Alpha.class));
        assertNotSame(injector.getToolProxy("cap", Alpha.class), injector.getToolProxy("cap", Beta.class));
        // Untyped, null and Object.class all deserialize dynamically — one handle.
        assertSame(injector.getToolProxy("cap"), injector.getToolProxy("cap", null));
        assertSame(injector.getToolProxy("cap"), injector.getToolProxy("cap", Object.class));
        assertNull(((McpMeshToolProxy<?>) injector.getToolProxy("cap")).getReturnType(),
            "a typed request must never leak its type into the untyped handle");
    }

    @Test
    @DisplayName("resolve / rebind / unavailable / re-resolve reach every typed handle")
    void topologyChangesReachEveryTypedHandle() {
        // Handles created BEFORE the dependency resolves (bean registration time).
        McpMeshTool<?> untyped = injector.getToolProxy("cap");
        McpMeshTool<?> alpha = injector.getToolProxy("cap", Alpha.class);
        assertFalse(alpha.isAvailable());
        assertFalse(injector.isDependencyAvailable("cap"));

        injector.updateToolDependency("cap", "http://ep-1", "fn");
        // A handle created AFTER resolution must see the live endpoint too.
        McpMeshTool<?> beta = injector.getToolProxy("cap", Beta.class);
        for (McpMeshTool<?> t : List.of(untyped, alpha, beta)) {
            assertTrue(t.isAvailable());
            assertEquals("http://ep-1", call(t).endpoint());
        }
        assertTrue(injector.isDependencyAvailable("cap"));

        injector.updateToolDependency("cap", "http://ep-2", "fn2");
        for (McpMeshTool<?> t : List.of(untyped, alpha, beta)) {
            Seen seen = call(t);
            assertEquals("http://ep-2", seen.endpoint());
            assertEquals("fn2", seen.functionName());
        }
        assertEquals(Alpha.class, call(alpha).returnType());

        injector.updateToolDependency("cap", null, null);
        for (McpMeshTool<?> t : List.of(untyped, alpha, beta)) {
            assertFalse(t.isAvailable(), "an unavailable dependency must not leave a typed handle live");
        }
        assertFalse(injector.isDependencyAvailable("cap"));

        injector.updateToolDependency("cap", "http://ep-3", "fn");
        for (McpMeshTool<?> t : List.of(untyped, alpha, beta)) {
            assertEquals("http://ep-3", call(t).endpoint());
        }
    }

    @Test
    @DisplayName("a tracer set after a typed view exists reaches the view")
    void tracerReachesExistingViews() throws Exception {
        McpMeshToolProxy<?> base = (McpMeshToolProxy<?>) injector.getToolProxy("cap");
        McpMeshToolProxy<?> alpha = (McpMeshToolProxy<?>) injector.getToolProxy("cap", Alpha.class);
        io.mcpmesh.spring.tracing.ExecutionTracer tracer =
            org.mockito.Mockito.mock(io.mcpmesh.spring.tracing.ExecutionTracer.class);
        base.setTracer(tracer);
        java.lang.reflect.Field f = McpMeshToolProxy.class.getDeclaredField("tracerRef");
        f.setAccessible(true);
        assertSame(tracer, ((java.util.concurrent.atomic.AtomicReference<?>) f.get(alpha)).get());
    }

    @Test
    @DisplayName("typed handles of different capabilities stay independent")
    void capabilitiesStayIndependent() {
        McpMeshTool<?> a = injector.getToolProxy("cap-a", Alpha.class);
        McpMeshTool<?> b = injector.getToolProxy("cap-b", Alpha.class);
        injector.updateToolDependency("cap-a", "http://a", "fn");
        assertTrue(a.isAvailable());
        assertFalse(b.isAvailable());
    }
}
