package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteHandlerInterceptor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.spring.web.MeshRouteUtils;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.method.HandlerMethod;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * The {@code @MeshRoute} half of the positional-binding conversion (issue
 * #1401), covering the three pieces the argument resolver's own tests cannot
 * reach: what the interceptor <i>stores</i>, what {@link MeshRouteUtils} reads
 * back out of it, and what {@code enrichDependencyReturnTypes} stamps onto each
 * dependency spec.
 *
 * <p>Placed in {@code io.mcpmesh.spring} so the package-private
 * {@code MeshSettleState} reset hook is visible (settled=true short-circuits the
 * settling-window wait, so an unavailable dependency is judged immediately).
 */
@DisplayName("@MeshRoute positional binding: attribute shape, MeshRouteUtils, return types")
class MeshRoutePositionalBindingTest {

    private MeshRouteRegistry registry;
    private MeshDependencyInjector injector;
    private MeshRouteHandlerInterceptor interceptor;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        registry = new MeshRouteRegistry();
        injector = mock(MeshDependencyInjector.class);
        ObjectProvider<MeshDependencyInjector> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(injector);
        interceptor = new MeshRouteHandlerInterceptor(registry, provider);
    }

    // ─────────────────────────────────────────────────────────────────
    // What the interceptor stores
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("The request attribute is a list aligned 1:1 with the declared dependencies")
    void attributeIsPositional() throws Exception {
        McpMeshTool a = live("a");
        McpMeshTool b = live("b");
        MockHttpServletRequest request = route("/all", "handler", "a", "b");

        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class),
            handler("handler")));

        assertEquals(Arrays.asList(a, b), resolved(request));
    }

    @Test
    @DisplayName("NULL-PADDING: an unavailable MIDDLE dependency leaves later slots in place")
    void unavailableMiddleDependencyIsNullPadded() throws Exception {
        // The trap this conversion must not reintroduce (#1390): the pre-3.4
        // interceptor inserted map entries only for AVAILABLE dependencies. Port
        // that to a list with add() and every later slot shifts by one.
        McpMeshTool a = live("a");
        McpMeshTool c = live("c");
        when(injector.getToolProxy("b")).thenReturn(null);
        MockHttpServletRequest request = route("/gap", "handler3", "a", "b", "c");

        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class),
            handler("handler3")));

        List<McpMeshTool> deps = resolved(request);
        assertEquals(3, deps.size(), "the list is pre-sized to the DECLARED count");
        assertSame(a, deps.get(0));
        assertNull(deps.get(1), "the unavailable dependency holds its own slot");
        assertSame(c, deps.get(2), "'c' must stay at index 2 — never compacted to index 1");
    }

    @Test
    @DisplayName("NULL-PADDING: a dependency that throws during resolution also holds its slot")
    void throwingDependencyIsNullPadded() throws Exception {
        McpMeshTool c = live("c");
        when(injector.getToolProxy("b")).thenThrow(new IllegalStateException("boom"));
        MockHttpServletRequest request = route("/throw", "handler3", "a", "b", "c");
        when(injector.getToolProxy("a")).thenReturn(null);

        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class),
            handler("handler3")));

        List<McpMeshTool> deps = resolved(request);
        assertNull(deps.get(0));
        assertNull(deps.get(1));
        assertSame(c, deps.get(2));
    }

    @Test
    @DisplayName("A proxy that exists but reports unavailable is null, not the proxy")
    void unavailableProxyIsNotStored() throws Exception {
        McpMeshTool down = mock(McpMeshTool.class);
        when(down.isAvailable()).thenReturn(false);
        when(injector.getToolProxy("a")).thenReturn(down);
        McpMeshTool b = live("b");
        MockHttpServletRequest request = route("/down", "handler", "a", "b");

        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class),
            handler("handler")));

        assertEquals(Arrays.asList(null, b), resolved(request));
    }

    // ─────────────────────────────────────────────────────────────────
    // MeshRouteUtils still works after the attribute type change
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("MeshRouteUtils rebuilds the capability-keyed view from the positional list")
    void routeUtilsGetDependencies() throws Exception {
        McpMeshTool a = live("a");
        McpMeshTool b = live("b");
        MockHttpServletRequest request = route("/utils", "handler", "a", "b");
        interceptor.preHandle(request, mock(HttpServletResponse.class), handler("handler"));

        Map<String, McpMeshTool> byCapability = MeshRouteUtils.getDependencies(request);

        assertSame(a, byCapability.get("a"));
        assertSame(b, byCapability.get("b"));
        assertSame(a, MeshRouteUtils.getDependency(request, "a"));
        assertSame(b, MeshRouteUtils.requireDependency(request, "b"));
        assertTrue(MeshRouteUtils.hasDependency(request, "a"));
    }

    @Test
    @DisplayName("MeshRouteUtils: an unavailable dependency is absent, and requireDependency throws")
    void routeUtilsOnAnUnavailableDependency() throws Exception {
        when(injector.getToolProxy("b")).thenReturn(null);
        McpMeshTool a = live("a");
        MockHttpServletRequest request = route("/utils2", "handler", "a", "b");
        interceptor.preHandle(request, mock(HttpServletResponse.class), handler("handler"));

        assertEquals(1, MeshRouteUtils.getDependencies(request).size());
        assertNull(MeshRouteUtils.getDependency(request, "b"));
        assertSame(a, MeshRouteUtils.getDependency(request, "a"),
            "the surviving dependency is still reachable by ITS capability");
        assertThrows(IllegalStateException.class,
            () -> MeshRouteUtils.requireDependency(request, "b"));
    }

    @Test
    @DisplayName("MeshRouteUtils: the @MeshDependency name alias is a secondary key")
    void routeUtilsAliasKey() throws Exception {
        McpMeshTool baseCap = live("base-cap");
        MockHttpServletRequest request = route("/alias", "handler1", "base-cap");
        interceptor.preHandle(request, mock(HttpServletResponse.class), handler("handler1"));

        assertSame(baseCap, MeshRouteUtils.getDependency(request, "base-cap"));
        assertSame(baseCap, MeshRouteUtils.getDependency(request, "baseCap"),
            "DependencySpec defaults its name to the camelCased capability");
    }

    @Test
    @DisplayName("MeshRouteUtils: the declaration-index accessor mirrors parameter injection")
    void routeUtilsByIndex() throws Exception {
        McpMeshTool a = live("a");
        McpMeshTool c = live("c");
        when(injector.getToolProxy("b")).thenReturn(null);
        MockHttpServletRequest request = route("/index", "handler3", "a", "b", "c");
        interceptor.preHandle(request, mock(HttpServletResponse.class), handler("handler3"));

        assertSame(a, MeshRouteUtils.getDependency(request, 0));
        assertNull(MeshRouteUtils.getDependency(request, 1));
        assertSame(c, MeshRouteUtils.getDependency(request, 2));
        assertNull(MeshRouteUtils.getDependency(request, 3), "out of range");
        assertNull(MeshRouteUtils.getDependency(request, -1));
    }

    @Test
    @DisplayName("MeshRouteUtils on a non-@MeshRoute request: empty map, no exception")
    void routeUtilsWithoutTheAttribute() {
        MockHttpServletRequest request = new MockHttpServletRequest();

        assertTrue(MeshRouteUtils.getDependencies(request).isEmpty());
        assertNull(MeshRouteUtils.getDependency(request, "a"));
        assertNull(MeshRouteUtils.getDependency(request, 0));
    }

    // ─────────────────────────────────────────────────────────────────
    // Return-type enrichment: the generic must follow the POSITION
    // ─────────────────────────────────────────────────────────────────

    /** Distinct payload types so a mis-assigned generic is visible. */
    public record Alpha(String a) {}

    /** Second payload type. */
    public record Beta(int b) {}

    @RestController
    @SuppressWarnings("unused")
    public static class TypedController {

        /** Declaration order matches the parameters. */
        @GetMapping("/typed")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "alpha"),
            @MeshDependency(capability = "beta")})
        public String typed(McpMeshTool<Alpha> first, McpMeshTool<Beta> second) {
            return "";
        }

        /**
         * The SAME parameters with the declaration list reordered. Positional
         * binding gives parameter 0 the 'beta' edge, so 'beta' must carry
         * {@code Alpha} as its response type — the generic follows the
         * parameter, not the capability name.
         */
        @GetMapping("/reordered")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "beta"),
            @MeshDependency(capability = "alpha")})
        public String reordered(McpMeshTool<Alpha> first, McpMeshTool<Beta> second) {
            return "";
        }

        /** A raw McpMeshTool in the middle must not shift the later generic. */
        @GetMapping("/raw-middle")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "alpha"),
            @MeshDependency(capability = "raw"),
            @MeshDependency(capability = "beta")})
        public String rawMiddle(
                McpMeshTool<Alpha> first,
                @SuppressWarnings("rawtypes") McpMeshTool second,
                McpMeshTool<Beta> third) {
            return "";
        }
    }

    @Test
    @DisplayName("Each McpMeshTool<T> generic lands on the dependency its PARAMETER binds to")
    void returnTypesFollowPosition() {
        Map<String, java.lang.reflect.Type> types = enrich("typed");

        assertEquals(Alpha.class, types.get("alpha"));
        assertEquals(Beta.class, types.get("beta"));
    }

    @Test
    @DisplayName("REORDERED: the generic follows the position, so response deserialization matches")
    void returnTypesFollowPositionAfterAReorder() {
        // The by-name enrichment this replaced would have given 'alpha' the
        // Alpha type even though parameter 1 — the McpMeshTool<Beta> — is what
        // binds to it, deserializing every response into the wrong type.
        Map<String, java.lang.reflect.Type> types = enrich("reordered");

        assertEquals(Alpha.class, types.get("beta"),
            "dependency[0] 'beta' binds to parameter 0, which is McpMeshTool<Alpha>");
        assertEquals(Beta.class, types.get("alpha"),
            "dependency[1] 'alpha' binds to parameter 1, which is McpMeshTool<Beta>");
    }

    @Test
    @DisplayName("A raw McpMeshTool consumes its slot without stealing the next generic")
    void rawParameterHoldsItsSlot() {
        Map<String, java.lang.reflect.Type> types = enrich("rawMiddle");

        assertEquals(Alpha.class, types.get("alpha"));
        assertNull(types.get("raw"), "a raw McpMeshTool contributes no type");
        assertEquals(Beta.class, types.get("beta"),
            "the third parameter's generic must not slide onto 'raw'");
    }

    @Test
    @DisplayName("The enriched type reaches the injector as the proxy's response type")
    void enrichedTypeIsUsedToBuildTheProxy() throws Exception {
        MeshRouteBeanPostProcessor processor = new MeshRouteBeanPostProcessor(registry);
        processor.postProcessAfterInitialization(new TypedController(), "typedController");

        McpMeshTool proxy = mock(McpMeshTool.class);
        when(proxy.isAvailable()).thenReturn(true);
        when(injector.getToolProxy(any(String.class), any(java.lang.reflect.Type.class)))
            .thenReturn(proxy);

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/reordered");
        interceptor.preHandle(request, mock(HttpServletResponse.class),
            new HandlerMethod(new TypedController(), methodOf(TypedController.class, "reordered")));

        // dependency[0] is 'beta' and binds to the McpMeshTool<Alpha> parameter.
        org.mockito.Mockito.verify(injector).getToolProxy(eq("beta"), eq(Alpha.class));
        org.mockito.Mockito.verify(injector).getToolProxy(eq("alpha"), eq(Beta.class));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    /** Sample controller whose method IDs back the registered route metadata. */
    @SuppressWarnings("unused")
    static class SampleController {
        public String handler1() { return "ok"; }
        public String handler() { return "ok"; }
        public String handler3() { return "ok"; }
    }

    private McpMeshTool live(String capability) {
        McpMeshTool tool = mock(McpMeshTool.class, capability);
        when(tool.isAvailable()).thenReturn(true);
        when(injector.getToolProxy(capability)).thenReturn(tool);
        return tool;
    }

    /** Register a route and build the matching request. */
    private MockHttpServletRequest route(String path, String methodName, String... capabilities) {
        List<MeshRouteRegistry.DependencySpec> deps = new ArrayList<>();
        for (String capability : capabilities) {
            deps.add(MeshRouteRegistry.DependencySpec.fromAnnotation(
                dependencyAnnotation(capability)));
        }
        registry.register("GET", path, new MeshRouteRegistry.RouteMetadata(
            SampleController.class.getName() + "." + methodName, deps, "test", false));
        return new MockHttpServletRequest("GET", path);
    }

    private HandlerMethod handler(String methodName) {
        return new HandlerMethod(new SampleController(),
            methodOf(SampleController.class, methodName));
    }

    @SuppressWarnings("unchecked")
    private static List<McpMeshTool> resolved(HttpServletRequest request) {
        return (List<McpMeshTool>)
            request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
    }

    /** Run the bean post-processor and read back capability → enriched return type. */
    private Map<String, java.lang.reflect.Type> enrich(String methodName) {
        MeshRouteRegistry local = new MeshRouteRegistry();
        new MeshRouteBeanPostProcessor(local)
            .postProcessAfterInitialization(new TypedController(), "typedController");
        MeshRouteRegistry.RouteMetadata metadata = local.getByHandlerMethodId(
            TypedController.class.getName() + "." + methodName);
        Map<String, java.lang.reflect.Type> types = new java.util.LinkedHashMap<>();
        for (MeshRouteRegistry.DependencySpec dep : metadata.getDependencies()) {
            types.put(dep.getCapability(), dep.getReturnType());
        }
        return types;
    }

    private static Method methodOf(Class<?> type, String name) {
        for (Method m : type.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("No such method: " + name);
    }

    /** A synthetic {@code @MeshDependency} so specs get their real defaults. */
    private static MeshDependency dependencyAnnotation(String capability) {
        return DepHolder.of(capability);
    }

    /** Holder supplying real {@code @MeshDependency} instances by reflection. */
    @SuppressWarnings("unused")
    private static final class DepHolder {
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "a"),
            @MeshDependency(capability = "b"),
            @MeshDependency(capability = "c"),
            @MeshDependency(capability = "base-cap")})
        static void shapes() {}

        static MeshDependency of(String capability) {
            try {
                MeshRoute route = DepHolder.class
                    .getDeclaredMethod("shapes").getAnnotation(MeshRoute.class);
                for (MeshDependency dep : route.dependencies()) {
                    if (dep.capability().equals(capability)) {
                        return dep;
                    }
                }
            } catch (NoSuchMethodException e) {
                throw new AssertionError(e);
            }
            throw new AssertionError("No @MeshDependency fixture for " + capability);
        }
    }
}
