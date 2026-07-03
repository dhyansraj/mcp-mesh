package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshRouteHandlerInterceptor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.method.HandlerMethod;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Issue #1249 perimeter: the {@code @MeshRoute} interceptor returns 503 with
 * {@code {"error":"dependency_unavailable","capability":"<cap>"}} — BEFORE the
 * controller runs — when a dependency declared {@code required=true} has no
 * available proxy at call time. Optional (default) deps keep soft-fail
 * semantics: with {@code failOnMissingDependency=false} the handler still runs
 * with a {@code null} dependency.
 *
 * <p>Mirrors the Python route wrapper contract. Placed in
 * {@code io.mcpmesh.spring} so the package-private {@code MeshSettleState}
 * reset hooks are visible (settled=true short-circuits the settling-window
 * wait so unavailable deps are judged immediately).
 */
class MeshRouteRequiredPerimeterTest {

    // Sample controller whose method IDs back the registered route metadata.
    static class SampleController {
        public String requiredRoute() { return "ok"; }
        public String optionalRoute() { return "ok"; }
    }

    private MeshRouteRegistry registry;
    private MeshDependencyInjector injector;
    private MeshRouteHandlerInterceptor interceptor;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        // timeout 0.0 → isSettled() returns true immediately, so the
        // interceptor does not block on the per-capability settle latch.
        MeshSettleState.resetForTests(0.0);

        registry = new MeshRouteRegistry();
        injector = mock(MeshDependencyInjector.class);
        ObjectProvider<MeshDependencyInjector> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(injector);
        interceptor = new MeshRouteHandlerInterceptor(registry, provider);
    }

    private static Method method(String name) {
        for (Method m : SampleController.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError(name);
    }

    private static String handlerId(String methodName) {
        return SampleController.class.getName() + "." + methodName;
    }

    private void registerRoute(String httpMethod, String path, String methodName,
                               List<MeshRouteRegistry.DependencySpec> deps,
                               boolean failOnMissing) {
        MeshRouteRegistry.RouteMetadata metadata = new MeshRouteRegistry.RouteMetadata(
            handlerId(methodName), deps, "test", failOnMissing);
        registry.register(httpMethod, path, metadata);
    }

    private HandlerMethod handler(String methodName) {
        return new HandlerMethod(new SampleController(), method(methodName));
    }

    @Test
    void requiredDependencyUnavailable_returns503_handlerNotInvoked() throws Exception {
        registerRoute("POST", "/req", "requiredRoute", List.of(
            new MeshRouteRegistry.DependencySpec("req_cap", new String[0], "", "reqCap",
                null, io.mcpmesh.SchemaMode.NONE, true)), true);

        // Required cap has no live proxy → unavailable.
        when(injector.getToolProxy("req_cap")).thenReturn(null);

        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/req");
        HttpServletResponse response = mock(HttpServletResponse.class);
        StringWriter body = new StringWriter();
        when(response.getWriter()).thenReturn(new PrintWriter(body));

        boolean proceed = interceptor.preHandle(request, response, handler("requiredRoute"));

        assertFalse(proceed, "preHandle must return false so the controller is NOT invoked");
        verify(response).setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
        assertEquals(
            "{\"error\":\"dependency_unavailable\",\"capability\":\"req_cap\"}",
            body.toString());
    }

    @Test
    void requiredDependencyAvailable_proceeds() throws Exception {
        registerRoute("POST", "/req2", "requiredRoute", List.of(
            new MeshRouteRegistry.DependencySpec("req_cap", new String[0], "", "reqCap",
                null, io.mcpmesh.SchemaMode.NONE, true)), true);

        McpMeshTool live = mock(McpMeshTool.class);
        when(live.isAvailable()).thenReturn(true);
        when(injector.getToolProxy("req_cap")).thenReturn(live);

        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/req2");
        HttpServletResponse response = mock(HttpServletResponse.class);

        boolean proceed = interceptor.preHandle(request, response, handler("requiredRoute"));

        assertTrue(proceed, "available required dep must let the controller run");
        verify(response, never()).setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
    }

    @Test
    void optionalDependencyUnavailable_softFail_handlerRuns() throws Exception {
        // Optional (default required=false) dep + failOnMissingDependency=false
        // → soft-fail: the handler runs with a null dependency, no 503.
        registerRoute("GET", "/opt", "optionalRoute", List.of(
            new MeshRouteRegistry.DependencySpec("opt_cap", new String[0], "", "optCap")), false);

        when(injector.getToolProxy("opt_cap")).thenReturn(null);

        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("GET");
        when(request.getRequestURI()).thenReturn("/opt");
        HttpServletResponse response = mock(HttpServletResponse.class);

        boolean proceed = interceptor.preHandle(request, response, handler("optionalRoute"));

        assertTrue(proceed, "unavailable OPTIONAL dep must not trip the perimeter 503");
        verify(response, never()).setStatus(anyInt());
    }

    @Test
    void requiredWins_evenWhenFailOnMissingIsFalse() throws Exception {
        // A required dep must 503 with the dependency_unavailable body even
        // when the route opted out of the coarse failOnMissingDependency check.
        registerRoute("POST", "/mix", "requiredRoute", List.of(
            new MeshRouteRegistry.DependencySpec("req_cap", new String[0], "", "reqCap",
                null, io.mcpmesh.SchemaMode.NONE, true)), false);

        when(injector.getToolProxy("req_cap")).thenReturn(null);

        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/mix");
        HttpServletResponse response = mock(HttpServletResponse.class);
        StringWriter body = new StringWriter();
        when(response.getWriter()).thenReturn(new PrintWriter(body));

        boolean proceed = interceptor.preHandle(request, response, handler("requiredRoute"));

        assertFalse(proceed);
        verify(response).setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
        assertTrue(body.toString().contains("\"capability\":\"req_cap\""));
    }
}
