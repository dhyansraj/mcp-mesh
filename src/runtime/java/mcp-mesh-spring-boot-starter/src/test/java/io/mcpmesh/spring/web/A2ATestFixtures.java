package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import org.springframework.beans.factory.ObjectProvider;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Shared helpers for the A2A producer test suite. Centralises:
 * <ul>
 *   <li>a no-op {@link ObjectProvider} that resolves to {@code null}
 *       (most tests don't exercise {@code @MeshInject} parameter resolution);</li>
 *   <li>a canonical {@link ObjectMapper} matching the production
 *       {@code tools.jackson} import path;</li>
 *   <li>a {@link MeshA2ARegistry.SurfaceMetadata} builder bound to a real
 *       Java method on an inner {@code TestHandlerBean} so the dispatcher's
 *       reflective invocation has something to call.</li>
 * </ul>
 *
 * <p>Test classes use {@link A2ATestFixtures} purely as a static helper —
 * never extended or instantiated. Each test still owns its own per-test
 * fixtures (BeforeEach) for isolation; this class only provides the
 * common factories.
 */
final class A2ATestFixtures {

    private A2ATestFixtures() {}

    /** Real Jackson ObjectMapper matching the production
     *  {@code tools.jackson} surface used by the dispatcher. */
    static ObjectMapper objectMapper() {
        return JsonMapper.builder().build();
    }

    /** Empty {@link ObjectProvider} that resolves to {@code null} on every
     *  lookup — appropriate when the test doesn't exercise dependency
     *  injection paths. */
    static ObjectProvider<MeshDependencyInjector> emptyInjectorProvider() {
        return new ObjectProvider<>() {
            @Override
            public MeshDependencyInjector getObject() { return null; }
            @Override
            public MeshDependencyInjector getObject(Object... args) { return null; }
            @Override
            public MeshDependencyInjector getIfAvailable() { return null; }
            @Override
            public MeshDependencyInjector getIfUnique() { return null; }
        };
    }

    /**
     * Build a {@link MeshA2ARegistry.SurfaceMetadata} that points at the
     * named method on a fresh {@link TestHandlerBean}. The handler is
     * implemented in plain Java so the dispatcher can reflectively invoke
     * it without any Spring machinery.
     */
    static MeshA2ARegistry.SurfaceMetadata surfaceOf(String path, String skillId, String handlerMethod) {
        TestHandlerBean bean = new TestHandlerBean();
        Method method;
        try {
            method = TestHandlerBean.class.getDeclaredMethod(handlerMethod, Map.class);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("Test bean has no handler method: " + handlerMethod, e);
        }
        return new MeshA2ARegistry.SurfaceMetadata(
            path,
            skillId,
            skillId, // skillName — required non-empty
            "",      // description
            List.of(),
            List.of(),
            "",      // auth
            "TestHandlerBean." + handlerMethod,
            bean,
            method
        );
    }

    /** Build a JSON-RPC request body string with the given method + params map.
     *
     *  <p>Uses {@link HashMap} (not {@link Map#of}) so {@code null} is allowed
     *  as the id value — the JSON-RPC 2.0 spec permits {@code "id": null} for
     *  notifications, and the dispatcher's parse-error responses also emit
     *  {@code id: null}. Coercing {@code null} to {@code ""} (the old
     *  behaviour) lost the notification/null-id semantics the producer must
     *  round-trip exactly. */
    static String jsonRpcBody(Object id, String method, Map<String, Object> params) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("jsonrpc", "2.0");
            body.put("id", id); // null is a legal JSON-RPC id; keep it.
            body.put("method", method);
            body.put("params", params == null ? Map.of() : params);
            return objectMapper().writeValueAsString(body);
        } catch (Exception e) {
            throw new AssertionError("Failed to serialize JSON-RPC body", e);
        }
    }

    /**
     * Test handler bean — all methods take a {@code Map} message and return
     * something the dispatcher can serialize. Switch on the message {@code op}
     * field to control behaviour for {@code tasks/send} tests:
     * <ul>
     *   <li>{@code "echo"} — returns the message verbatim;</li>
     *   <li>{@code "string"} — returns a fixed string;</li>
     *   <li>{@code "raise"} — throws RuntimeException with the message
     *       {@code text} field as error text;</li>
     *   <li>any other / missing op — returns "ok".</li>
     * </ul>
     */
    public static class TestHandlerBean {

        public Object syncHandler(Map<String, Object> message) {
            Object op = message != null ? message.get("op") : null;
            if ("raise".equals(op)) {
                Object text = message.get("text");
                throw new RuntimeException(text != null ? text.toString() : "boom");
            }
            if ("string".equals(op)) {
                return "fixed string result";
            }
            if ("echo".equals(op)) {
                return message;
            }
            return "ok";
        }

        /**
         * Returns a {@link io.mcpmesh.JobProxy} when the test wants to
         * exercise the long-running branch. The proxy is injected via a
         * static slot set by the test before invocation.
         */
        public Object longRunningHandler(Map<String, Object> message) {
            io.mcpmesh.JobProxy p = PROXY_SLOT.get();
            if (p == null) {
                throw new IllegalStateException(
                    "Test setup error: PROXY_SLOT not populated before longRunningHandler invocation");
            }
            return p;
        }

        /** Sleep-free handler that always throws — for sendSubscribe
         *  exception path tests. */
        public Object alwaysRaises(Map<String, Object> message) {
            throw new RuntimeException("handler exploded");
        }

        /** Static slot the test populates before invoking longRunningHandler.
         *  Each test must clear it in @AfterEach for isolation. */
        public static final ThreadLocal<io.mcpmesh.JobProxy> PROXY_SLOT = new ThreadLocal<>();
    }
}
