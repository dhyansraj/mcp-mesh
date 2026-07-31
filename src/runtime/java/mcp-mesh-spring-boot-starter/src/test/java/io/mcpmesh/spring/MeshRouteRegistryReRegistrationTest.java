package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshDependency;
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
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.method.HandlerMethod;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@code MeshRouteRegistry} must distinguish a re-registration of a handler from
 * a conflicting one, and must build its handler id the same way at registration
 * and at lookup (issue #1437 follow-ups).
 *
 * <p>Three separate defects, all in the same family — a guard keyed on something
 * narrower or wider than the thing it is actually protecting:
 *
 * <ul>
 *   <li>{@code indexHandler} failed the boot whenever a DIFFERENT INSTANCE of
 *       {@code RouteMetadata} claimed an already-registered {@code Method}, while
 *       {@code register} itself replaced in {@code routesByPath} without
 *       complaint. Two bean definitions of one controller class produce two
 *       distinct-but-equal metadata objects for the same method — not a
 *       duplicate. The guard now compares what a lookup here actually feeds: the
 *       (positional, since #1401) dependency list.</li>
 *   <li>{@code register} mutated {@code routesByPath} BEFORE running that guard,
 *       so a rejected registration left the path map already written.</li>
 *   <li>The interceptor's compatibility fallback built its lookup id from the
 *       HandlerMethod's BEAN TYPE while registration built it from the method's
 *       DECLARING class. Identical for a handler declared on the controller
 *       itself; divergent for one inherited from a base class — and the fallback
 *       then silently missed.</li>
 * </ul>
 *
 * <p>Note on the inherited case: {@code MeshRouteBeanPostProcessor} scans
 * {@code getDeclaredMethods()}, so an inherited handler is not auto-discovered
 * on the subclass bean. The divergence is therefore reached through the
 * string-id registration path — the public
 * {@code RouteMetadata(String, List, String, boolean)} constructor — which is
 * precisely the arrangement the interceptor's fallback exists to serve.
 *
 * <p>Placed in {@code io.mcpmesh.spring} so {@code MeshSettleState}'s
 * package-private test reset is visible — settled=true short-circuits the
 * settling-window wait, matching {@code MeshRouteOverloadedHandlerTest}.
 */
@DisplayName("MeshRouteRegistry: re-registration, ordering, and handler id alignment")
class MeshRouteRegistryReRegistrationTest {

    private MeshRouteRegistry registry;
    private MeshDependencyInjector injector;
    private MeshRouteHandlerInterceptor interceptor;

    private McpMeshTool alphaProxy;

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
        when(alphaProxy.isAvailable()).thenReturn(true);
        when(injector.getToolProxy("alpha")).thenReturn(alphaProxy);
    }

    // ─────────────────────────────────────────────────────────────────
    // Re-registration vs. conflict
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("A second scan of the same controller is idempotent, not a duplicate")
    void reScanningTheSameControllerDoesNotFailTheBoot() {
        MeshRouteBeanPostProcessor scanner = new MeshRouteBeanPostProcessor(registry);
        Method handle = handlerOf(ReScannedController.class);

        scanner.postProcessAfterInitialization(new ReScannedController(), "primary");
        MeshRouteRegistry.RouteMetadata first = registry.getByHandlerMethod(handle);
        assertNotNull(first);

        // A SECOND bean definition of the same controller class. The scanner
        // builds a fresh RouteMetadata and a fresh List<DependencySpec> from the
        // annotation every pass, so nothing is shared with the first pass.
        assertDoesNotThrow(
            () -> scanner.postProcessAfterInitialization(new ReScannedController(), "secondary"),
            "two bean definitions of one controller are not a duplicate handler");

        MeshRouteRegistry.RouteMetadata second = registry.getByHandlerMethod(handle);
        assertNotSame(first, second, "the incoming metadata must win the Method index");
        assertSame(second, registry.getByRoute("GET", "/rescan"),
            "and routesByPath must hold that same incoming instance");
    }

    @Test
    @DisplayName("The idempotency verdict rests on DependencySpec VALUE equality")
    void reRegistrationIsJudgedByDependencyValueEquality() {
        // This is what makes the narrowed guard a guard at all. DependencySpec
        // had no equals/hashCode, so List.equals fell through to element
        // IDENTITY — two separately-built specs could never compare equal and
        // the narrowed condition would be inert, i.e. indistinguishable from the
        // instance-identity check it replaced. Strip DependencySpec.equals and
        // both this test and reScanningTheSameControllerDoesNotFailTheBoot fail.
        MeshRouteBeanPostProcessor scanner = new MeshRouteBeanPostProcessor(registry);
        Method handle = handlerOf(ReScannedController.class);

        scanner.postProcessAfterInitialization(new ReScannedController(), "primary");
        List<MeshRouteRegistry.DependencySpec> firstDeps =
            registry.getByHandlerMethod(handle).getDependencies();
        scanner.postProcessAfterInitialization(new ReScannedController(), "secondary");
        List<MeshRouteRegistry.DependencySpec> secondDeps =
            registry.getByHandlerMethod(handle).getDependencies();

        assertNotSame(firstDeps, secondDeps);
        assertNotSame(firstDeps.get(0), secondDeps.get(0),
            "the two scans must produce SEPARATE spec objects — otherwise this "
                + "proves nothing about value equality");
        assertEquals(firstDeps, secondDeps,
            "equal declarations must compare equal BY VALUE");
        assertEquals(firstDeps.get(0).hashCode(), secondDeps.get(0).hashCode(),
            "equals without a matching hashCode is a broken contract");
    }

    @Test
    @DisplayName("A conflicting registration still fails the boot, naming both lists")
    void conflictingRegistrationStillFailsBoot() {
        Method handle = handlerOf(ReScannedController.class);
        registry.register("GET", "/first", new MeshRouteRegistry.RouteMetadata(
            handle, List.of(dep("alpha")), "", false));

        IllegalStateException boom = assertThrows(IllegalStateException.class, () ->
            registry.register("GET", "/second", new MeshRouteRegistry.RouteMetadata(
                handle, List.of(dep("beta")), "", false)),
            "narrowing the guard must not swallow a genuine conflict");

        // The diagnostic is the whole value of failing here rather than later, at
        // some request that silently got the other handler's proxies.
        assertTrue(boom.getMessage().contains("handler collision"), boom.getMessage());
        assertTrue(boom.getMessage().contains("[alpha]"),
            "the message must name the ALREADY-registered dependency list: " + boom.getMessage());
        assertTrue(boom.getMessage().contains("[beta]"),
            "the message must name the INCOMING dependency list: " + boom.getMessage());
    }

    // ─────────────────────────────────────────────────────────────────
    // Ordering
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("A rejected registration leaves routesByPath untouched")
    void rejectedRegistrationDoesNotMutateTheRouteMap() {
        Method handle = handlerOf(ReScannedController.class);
        MeshRouteRegistry.RouteMetadata accepted = new MeshRouteRegistry.RouteMetadata(
            handle, List.of(dep("alpha")), "", false);
        registry.register("GET", "/first", accepted);

        assertThrows(IllegalStateException.class, () ->
            registry.register("GET", "/second", new MeshRouteRegistry.RouteMetadata(
                handle, List.of(dep("beta")), "", false)));

        // The throw is not the assertion — this is. register() used to write
        // routesByPath BEFORE the guard ran, so a registration it then rejected
        // still left the path resolvable, and every path-keyed consumer
        // (getUniqueDependencySpecs, promoteCapabilityToRequired, the heartbeat
        // spec) saw a route the registry had refused.
        assertNull(registry.getByRoute("GET", "/second"),
            "the rejected route must not be resolvable by path");
        assertEquals(1, registry.getRouteCount(), "only the accepted route may be present");
        assertSame(accepted, registry.getByRoute("GET", "/first"));
    }

    // ─────────────────────────────────────────────────────────────────
    // Handler id alignment
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("An inherited handler's id agrees between registration and lookup")
    void inheritedHandlerIdMatchesAtLookup() throws Exception {
        // Registration derives the id from the method's DECLARING class, so a
        // handler inherited from a base class is registered under the BASE name.
        String registeredId = BaseUploadController.class.getName() + ".handle";
        MeshRouteRegistry.RouteMetadata metadata = new MeshRouteRegistry.RouteMetadata(
            registeredId, List.of(dep("alpha")), "", false);
        registry.register("GET", "/inherited", metadata);

        Method inherited = ConcreteUploadController.class.getMethod("handle", McpMeshTool.class);
        HandlerMethod handlerMethod = new HandlerMethod(new ConcreteUploadController(), inherited);
        // The divergence itself: these two are NOT the same class.
        assertEquals(BaseUploadController.class, inherited.getDeclaringClass());
        assertEquals(ConcreteUploadController.class, handlerMethod.getBeanType());

        // Metadata carries no Method identity, so preHandle must reach it through
        // the compatibility fallback — which is where the two id constructions
        // meet. Built from the bean type, the fallback looked up
        // "ConcreteUploadController.handle" and missed.
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/inherited");
        assertTrue(interceptor.preHandle(request, mock(HttpServletResponse.class), handlerMethod));
        assertEquals(List.of(alphaProxy), resolved(request),
            "the inherited handler must receive its declared dependency — on the "
                + "bean-type id the fallback missed and the route was served with none");
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private static Method handlerOf(Class<?> type) {
        try {
            return type.getDeclaredMethod("handle", McpMeshTool.class);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("No such handler", e);
        }
    }

    @SuppressWarnings("unchecked")
    private static List<McpMeshTool> resolved(HttpServletRequest request) {
        return (List<McpMeshTool>)
            request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
    }

    private static MeshRouteRegistry.DependencySpec dep(String capability) {
        return new MeshRouteRegistry.DependencySpec(
            capability, new String[0], "", capability);
    }

    /** Scanned twice, as two bean definitions of one controller class would be. */
    @RestController
    @SuppressWarnings("unused")
    public static class ReScannedController {

        @GetMapping("/rescan")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String handle(McpMeshTool one) {
            return "rescan";
        }
    }

    /** Declares the handler; the concrete controller below only inherits it. */
    @RestController
    @SuppressWarnings("unused")
    public abstract static class BaseUploadController {

        @GetMapping("/inherited")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String handle(McpMeshTool one) {
            return "inherited";
        }
    }

    /** Bean type = this class; declaring class of {@code handle} = the base. */
    @RestController
    public static class ConcreteUploadController extends BaseUploadController {
    }
}
