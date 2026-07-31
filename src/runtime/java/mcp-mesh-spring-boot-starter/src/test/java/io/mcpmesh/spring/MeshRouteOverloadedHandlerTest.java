package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInjectArgumentResolver;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteHandlerInterceptor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.MethodParameter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.ServletWebRequest;
import org.springframework.web.method.HandlerMethod;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Two overloaded {@code @MeshRoute} handlers must each receive their OWN
 * declared dependencies (issue #1437).
 *
 * <p>{@code MeshRouteRegistry} indexed handlers by
 * {@code "ClassName.methodName"} — no parameter types — and wrote them with a
 * bare {@code put}. Overloads collide on that id, and since the registry is
 * keyed per HANDLER while routes are keyed per MAPPING, both overloads register
 * on their own paths and the second silently replaced the first.
 * {@code MeshRouteHandlerInterceptor.preHandle} rebuilt the same id and built
 * the injected dependency list from whatever came back, so a request to
 * {@code /a} was served {@code /b}'s proxies.
 *
 * <p>The list is <b>positional</b> since #1401, which is what makes the swap
 * invisible: two overloads declaring the same two capabilities in opposite
 * order produce a list of the same length holding the same objects, and only
 * the parameter each one lands in changes. {@link #parametersReceiveTheirOwnDependencies()}
 * pins it at the parameter, through the real argument resolver.
 *
 * <p>Placed in {@code io.mcpmesh.spring} so {@code MeshSettleState}'s
 * package-private test reset is visible — settled=true short-circuits the
 * settling-window wait.
 */
@DisplayName("@MeshRoute: overloaded handlers get their own dependency lists")
class MeshRouteOverloadedHandlerTest {

    private MeshRouteRegistry registry;
    private MeshDependencyInjector injector;
    private MeshRouteHandlerInterceptor interceptor;

    private McpMeshTool alphaProxy;
    private McpMeshTool betaProxy;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        registry = new MeshRouteRegistry();
        injector = mock(MeshDependencyInjector.class);
        ObjectProvider<MeshDependencyInjector> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(injector);
        interceptor = new MeshRouteHandlerInterceptor(registry, provider);

        alphaProxy = mock(McpMeshTool.class, "alpha-proxy");
        betaProxy = mock(McpMeshTool.class, "beta-proxy");
        when(alphaProxy.isAvailable()).thenReturn(true);
        when(betaProxy.isAvailable()).thenReturn(true);
        when(injector.getToolProxy("alpha")).thenReturn(alphaProxy);
        when(injector.getToolProxy("beta")).thenReturn(betaProxy);
    }

    // ─────────────────────────────────────────────────────────────────
    // The collision
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Each overload resolves ITS OWN declared dependency order")
    void eachOverloadResolvesItsOwnDependencies() throws Exception {
        scan();

        MockHttpServletRequest requestA = new MockHttpServletRequest("GET", "/a");
        assertTrue(interceptor.preHandle(requestA, mock(HttpServletResponse.class), handlerA()));

        // /a declares [alpha, beta]. On the colliding id it was served /b's
        // metadata, which declares [beta, alpha] — same size, same two proxies,
        // opposite order. Nothing about the shape of the list says so.
        assertEquals(Arrays.asList(alphaProxy, betaProxy), resolved(requestA),
            "the 2-parameter overload must get ITS OWN [alpha, beta], not the "
                + "3-parameter overload's [beta, alpha]");

        MockHttpServletRequest requestB = new MockHttpServletRequest("GET", "/b");
        assertTrue(interceptor.preHandle(requestB, mock(HttpServletResponse.class), handlerB()));
        assertEquals(Arrays.asList(betaProxy, alphaProxy), resolved(requestB));
    }

    @Test
    @DisplayName("POSITIONAL: the swap is only visible at the parameter it binds")
    void parametersReceiveTheirOwnDependencies() throws Exception {
        scan();

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/a");
        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class), handlerA()));

        // Drive the REAL argument resolver: injectable slot 0 of the 2-parameter
        // overload is parameter 0, and dependencies[0] of ITS list is 'alpha'.
        MeshInjectArgumentResolver resolver = new MeshInjectArgumentResolver();
        Method handle = overload(McpMeshTool.class, McpMeshTool.class);

        assertSame(alphaProxy, resolve(resolver, request, handle, 0),
            "parameter 0 of the 2-parameter overload binds dependencies[0] = 'alpha'; "
                + "on the shared id it received 'beta' — the other overload's slot 0");
        assertSame(betaProxy, resolve(resolver, request, handle, 1));
    }

    @Test
    @DisplayName("A registered overload does not make the other one unresolvable")
    void bothOverloadsAreRegisteredAndAddressable() {
        scan();

        MeshRouteRegistry.RouteMetadata narrow =
            registry.getByHandlerMethod(overload(McpMeshTool.class, McpMeshTool.class));
        MeshRouteRegistry.RouteMetadata wide = registry.getByHandlerMethod(
            overload(String.class, McpMeshTool.class, McpMeshTool.class));

        // Issue #1443: three distinctly-mapped handlers are three routes. This
        // controller is the issue's PROBE-C measurement, which reported four —
        // the fourth being a phantom GET / whose winner was whichever handler
        // getDeclaredMethods() happened to hand over last.
        assertEquals(3, registry.getRouteCount());
        assertNull(registry.getByRoute("GET", "/"),
            "no handler is mapped at the controller base path");

        assertNotNull(narrow);
        assertNotNull(wide);
        assertEquals(List.of("alpha", "beta"), capabilities(narrow));
        assertEquals(List.of("beta", "alpha"), capabilities(wide));
        assertSame(narrow, registry.getByRoute("GET", "/a"));
        assertSame(wide, registry.getByRoute("GET", "/b"));
    }

    @Test
    @DisplayName("The Method key is value-based — a fresh reflective copy still hits")
    void freshMethodCopiesAreEqualKeys() {
        // The assumption the whole re-key rests on, and the one
        // MeshInjectArgumentResolver's Map<Method, int[]> already relies on:
        // getDeclaredMethods() hands back a NEW Method object every call, and
        // Method.equals/hashCode are value-based over (declaringClass, name,
        // returnType, parameterTypes). Registration and lookup never share an
        // instance — Spring MVC resolves its own.
        Method one = overload(McpMeshTool.class, McpMeshTool.class);
        Method two = overload(McpMeshTool.class, McpMeshTool.class);
        assertNotSame(one, two, "getDeclaredMethod returns a fresh copy each call");
        assertEquals(one, two);
        assertEquals(one.hashCode(), two.hashCode());
        assertNotEquals(one, overload(String.class, McpMeshTool.class, McpMeshTool.class),
            "the overloads must NOT be equal — parameter types are part of the identity");

        scan();
        assertSame(registry.getByHandlerMethod(one), registry.getByHandlerMethod(two));
    }

    // ─────────────────────────────────────────────────────────────────
    // The public string accessor
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("getByHandlerMethodId refuses an id that names more than one handler")
    @SuppressWarnings("deprecation")
    void ambiguousHandlerMethodIdIsRefused() {
        scan();

        assertNull(registry.getByHandlerMethodId(
                OverloadedController.class.getName() + ".handle"),
            "the id names both overloads — it must not resolve to an arbitrary one");
    }

    @Test
    @DisplayName("getByHandlerMethodId still answers for a handler that is not overloaded")
    @SuppressWarnings("deprecation")
    void unambiguousHandlerMethodIdStillResolves() {
        scan();

        MeshRouteRegistry.RouteMetadata metadata = registry.getByHandlerMethodId(
            OverloadedController.class.getName() + ".solo");
        assertNotNull(metadata, "a non-overloaded handler is still addressable by id");
        assertEquals(List.of("alpha"), capabilities(metadata));
    }

    // ─────────────────────────────────────────────────────────────────
    // The boot guard
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("A genuine duplicate registration fails at boot")
    void duplicateHandlerRegistrationFailsBoot() {
        Method handle = overload(McpMeshTool.class, McpMeshTool.class);

        registry.register("GET", "/first", new MeshRouteRegistry.RouteMetadata(
            handle, List.of(dep("alpha")), "", false));

        IllegalStateException boom = assertThrows(IllegalStateException.class, () ->
            registry.register("GET", "/second", new MeshRouteRegistry.RouteMetadata(
                handle, List.of(dep("beta")), "", false)));
        assertTrue(boom.getMessage().contains("handler collision"), boom.getMessage());
    }

    @Test
    @DisplayName("Overloads are NOT duplicates — the guard does not fire on them")
    void overloadsDoNotTripTheBootGuard() {
        // The whole point: two DIFFERENT methods sharing one id are legal and
        // must boot. Only the same method registered twice with different
        // metadata is a duplicate.
        scan();

        assertNotSame(
            registry.getByHandlerMethod(overload(McpMeshTool.class, McpMeshTool.class)),
            registry.getByHandlerMethod(
                overload(String.class, McpMeshTool.class, McpMeshTool.class)),
            "each overload keeps its own metadata");
    }

    @Test
    @DisplayName("One handler on several mappings is NOT a duplicate")
    void severalMappingsOnOneHandlerDoNotTripTheBootGuard() throws Exception {
        // Registration is per MAPPING with one shared metadata instance —
        // @GetMapping + @PostMapping on the same handler registers twice.
        new MeshRouteBeanPostProcessor(registry)
            .postProcessAfterInitialization(new MultiMappedController(), "multiMapped");

        // Exactly two — issue #1443: the scan also registered a phantom
        // GET <base path> for every handler, so this controller yielded three.
        assertEquals(2, registry.getRouteCount(),
            "one handler on two mappings is two routes, not three");
        assertNotNull(registry.getByRoute("GET", "/multi"));
        assertSame(registry.getByRoute("GET", "/multi"), registry.getByRoute("POST", "/multi"),
            "both mappings share ONE metadata instance — that is not a duplicate handler");

        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/multi");
        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class),
            new HandlerMethod(new MultiMappedController(),
                MultiMappedController.class.getDeclaredMethod("both", McpMeshTool.class))));
        assertEquals(List.of(alphaProxy), resolved(request));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    /** Run the real bean post-processor over the overloaded controller. */
    private void scan() {
        new MeshRouteBeanPostProcessor(registry)
            .postProcessAfterInitialization(new OverloadedController(), "overloadedController");
    }

    private HandlerMethod handlerA() {
        return new HandlerMethod(new OverloadedController(),
            overload(McpMeshTool.class, McpMeshTool.class));
    }

    private HandlerMethod handlerB() {
        return new HandlerMethod(new OverloadedController(),
            overload(String.class, McpMeshTool.class, McpMeshTool.class));
    }

    private static Method overload(Class<?>... paramTypes) {
        try {
            // A FRESH reflective copy every call — Method.equals is value-based
            // over (declaringClass, name, returnType, parameterTypes), which is
            // what makes a Method-keyed registry lookup work at all.
            return OverloadedController.class.getDeclaredMethod("handle", paramTypes);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("No such overload", e);
        }
    }

    private static Object resolve(MeshInjectArgumentResolver resolver, HttpServletRequest request,
                                  Method method, int parameterIndex) {
        MethodParameter parameter = new MethodParameter(method, parameterIndex);
        assertTrue(resolver.supportsParameter(parameter),
            "parameter " + parameterIndex + " must be an injectable slot");
        return resolver.resolveArgument(parameter, null,
            new ServletWebRequest(request), null);
    }

    @SuppressWarnings("unchecked")
    private static List<McpMeshTool> resolved(HttpServletRequest request) {
        return (List<McpMeshTool>)
            request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
    }

    private static List<String> capabilities(MeshRouteRegistry.RouteMetadata metadata) {
        return metadata.getDependencies().stream()
            .map(MeshRouteRegistry.DependencySpec::getCapability)
            .toList();
    }

    private static MeshRouteRegistry.DependencySpec dep(String capability) {
        return new MeshRouteRegistry.DependencySpec(
            capability, new String[0], "", capability);
    }

    /**
     * Two {@code handle} overloads on different mappings, declaring the SAME two
     * capabilities in OPPOSITE order — so a leaked dependency list is the same
     * length and holds the same proxies, and only the binding differs.
     */
    @RestController
    @SuppressWarnings("unused")
    public static class OverloadedController {

        @GetMapping("/a")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "alpha"),
            @MeshDependency(capability = "beta")})
        public String handle(McpMeshTool one, McpMeshTool two) {
            return "a";
        }

        @GetMapping("/b")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "beta"),
            @MeshDependency(capability = "alpha")})
        public String handle(String query, McpMeshTool one, McpMeshTool two) {
            return "b";
        }

        @GetMapping("/solo")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String solo(McpMeshTool one) {
            return "solo";
        }
    }

    /** One handler, two mappings — registered twice with ONE metadata instance. */
    @RestController
    @SuppressWarnings("unused")
    public static class MultiMappedController {

        @GetMapping("/multi")
        @PostMapping("/multi")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String both(McpMeshTool one) {
            return "multi";
        }
    }
}
