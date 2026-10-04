package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshA2ABeanPostProcessor;
import io.mcpmesh.spring.web.MeshA2ARegistry;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteHandlerInterceptor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.beans.factory.support.RootBeanDefinition;
import org.springframework.cglib.proxy.Enhancer;
import org.springframework.cglib.proxy.NoOp;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1569: {@code @MeshRoute} / {@code @MeshA2A} handlers declared on a base
 * class are served by Spring MVC (which walks the full method set) but were
 * invisible to mesh, whose three scanners used {@code getDeclaredMethods()}. The
 * route answered, its {@code McpMeshTool} was injected {@code null}, and the
 * dependency was never advertised. {@code @MeshTool} had the same defect and was
 * fixed with {@code MethodIntrospector}; these tests pin the same for the web
 * scanners, including the duplicate traps (an override annotated on both levels,
 * generic bridge methods, a CGLIB subclass).
 */
@DisplayName("#1569: inherited @MeshRoute / @MeshA2A handlers register with mesh")
class MeshWebHandlerInheritanceScanTest {

    record Report(String text) {}

    // ── @MeshRoute fixtures ────────────────────────────────────────────

    public abstract static class BaseReportController {
        @MeshRoute(dependencies = @MeshDependency(capability = "report_lookup"))
        @PostMapping("/report")
        public String report(McpMeshTool<Report> lookup) {
            return "ok";
        }
    }

    @RestController
    @RequestMapping("/api")
    public static class InheritingController extends BaseReportController {}

    @RestController
    public static class OverridingController extends BaseReportController {
        @Override
        @MeshRoute(dependencies = @MeshDependency(capability = "report_lookup"))
        @PostMapping("/report")
        public String report(McpMeshTool<Report> lookup) {
            return "override";
        }
    }

    public abstract static class GenericBaseController<T> {
        @MeshRoute(dependencies = @MeshDependency(capability = "generic_cap"))
        @PostMapping("/generic")
        public abstract String handle(T body, McpMeshTool<Report> tool);
    }

    @RestController
    public static class GenericController extends GenericBaseController<String> {
        @Override
        public String handle(String body, McpMeshTool<Report> tool) {
            return body;
        }
    }

    // ── inherited generic handler fixtures ─────────────────────────────

    public abstract static class GenericLookupBase<T> {
        @MeshRoute(dependencies = @MeshDependency(capability = "lookup"))
        @PostMapping("/lookup")
        public String lookup(McpMeshTool<T> tool) {
            return "ok";
        }
    }

    @RestController
    @RequestMapping("/alpha")
    public static class AlphaLookup extends GenericLookupBase<Report> {}

    @RestController
    @RequestMapping("/beta")
    public static class BetaLookup extends GenericLookupBase<List<Report>> {}

    @RestController
    @RequestMapping("/raw")
    @SuppressWarnings("rawtypes")
    public static class RawLookup extends GenericLookupBase {}

    /** Source of a reflected {@code List<Report>} to compare against. */
    @SuppressWarnings("unused")
    private static List<Report> listOfReport;

    /** Same base, never scanned: its requests match none of the registered bindings. */
    public static class UnregisteredLookup extends GenericLookupBase<String> {}

    // ── self-referential bounds ────────────────────────────────────────

    public abstract static class EnumBase<E extends Enum<E>> {
        @MeshRoute(dependencies = @MeshDependency(capability = "enum_cap"))
        @PostMapping("/enum")
        public String handle(McpMeshTool<E> tool) {
            return "ok";
        }
    }

    @RestController
    @SuppressWarnings("rawtypes")
    public static class RawEnumController extends EnumBase {}

    @RestController
    public static class GenericMethodController {
        @MeshRoute(dependencies = @MeshDependency(capability = "cmp_cap"))
        @PostMapping("/cmp")
        public <T extends Comparable<T>> String handle(McpMeshTool<T> tool) {
            return "ok";
        }
    }

    // ── @MeshA2A fixtures ──────────────────────────────────────────────

    public abstract static class BaseA2AComponent {
        @MeshA2A(path = "/agents/base", skillId = "base-skill", skillName = "Base",
                 dependencies = @MeshDependency(capability = "a2a_lookup"))
        public Map<String, Object> handle(Map<String, Object> message, McpMeshTool<Report> lookup) {
            return message;
        }
    }

    public static class InheritingA2AComponent extends BaseA2AComponent {}

    public static class OverridingA2AComponent extends BaseA2AComponent {
        @Override
        @MeshA2A(path = "/agents/base", skillId = "base-skill", skillName = "Base",
                 dependencies = @MeshDependency(capability = "a2a_lookup"))
        public Map<String, Object> handle(Map<String, Object> message, McpMeshTool<Report> lookup) {
            return Map.of();
        }
    }

    private MeshRouteRegistry routeRegistry;
    private MeshA2ARegistry a2aRegistry;

    @BeforeEach
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        routeRegistry = new MeshRouteRegistry();
        a2aRegistry = new MeshA2ARegistry();
    }

    @AfterEach
    void tearDown() {
        MeshSettleState.resetForTests();
    }

    private void scanRoutes(Object bean) {
        new MeshRouteBeanPostProcessor(routeRegistry).postProcessAfterInitialization(bean, "bean");
    }

    private void scanA2A(Object bean) {
        new MeshA2ABeanPostProcessor(a2aRegistry).postProcessAfterInitialization(bean, "bean");
    }

    private static Method baseReport() throws NoSuchMethodException {
        return BaseReportController.class.getMethod("report", McpMeshTool.class);
    }

    // ── route ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("route declared on a base controller registers, under the subclass's base path")
    void inheritedRouteRegisters() throws Exception {
        scanRoutes(new InheritingController());

        MeshRouteRegistry.RouteMetadata md = routeRegistry.getByRoute("POST", "/api/report");
        assertNotNull(md, "the inherited handler is served by Spring MVC, so mesh must register it");
        // Spring MVC's HandlerMethod for an inherited handler is the base-class
        // Method; the interceptor looks metadata up by exactly that identity.
        assertNotNull(routeRegistry.getByHandlerMethod(baseReport()));
        assertEquals(1, md.getDependencies().size());
        assertEquals(Report.class, md.getDependencies().get(0).getReturnType());
        assertEquals(List.of("report_lookup"),
            routeRegistry.getUniqueDependencySpecs().stream().map(d -> d.getCapability()).toList(),
            "the inherited handler's dependency must be advertised to the registry");
    }

    @Test
    @DisplayName("override annotated on both levels registers exactly once, keyed by the override")
    void overrideAnnotatedTwiceRegistersOnce() throws Exception {
        scanRoutes(new OverridingController());

        assertEquals(1, routeRegistry.getRouteCount());
        Method override = OverridingController.class.getMethod("report", McpMeshTool.class);
        assertNotNull(routeRegistry.getByHandlerMethod(override));
    }

    @Test
    @DisplayName("generic base: the specialised override registers once, no bridge duplicate")
    void genericBridgeRegistersOnce() throws Exception {
        scanRoutes(new GenericController());

        assertEquals(1, routeRegistry.getRouteCount());
        Method specific = GenericController.class.getMethod("handle", String.class, McpMeshTool.class);
        assertNotNull(routeRegistry.getByHandlerMethod(specific));
    }

    @Test
    @DisplayName("CGLIB subclass: registers against the user-class Method, not the generated override")
    void cglibSubclassRegistersUserMethod() throws Exception {
        Enhancer enhancer = new Enhancer();
        enhancer.setSuperclass(InheritingController.class);
        enhancer.setCallback(NoOp.INSTANCE);
        Object proxy = enhancer.create();
        assertTrue(proxy.getClass().getName().contains("$$"), "fixture must be a CGLIB subclass");

        scanRoutes(proxy);

        assertEquals(1, routeRegistry.getRouteCount());
        assertNotNull(routeRegistry.getByHandlerMethod(baseReport()));
    }

    @Test
    @DisplayName("inherited generic handler: T resolves per subclass; one Method, separate bindings")
    void inheritedGenericHandlerResolvesPerSubclass() throws Exception {
        scanRoutes(new AlphaLookup());
        scanRoutes(new BetaLookup());
        scanRoutes(new RawLookup());
        Method base = GenericLookupBase.class.getMethod("lookup", McpMeshTool.class);
        java.lang.reflect.Type listOfReportType =
            MeshWebHandlerInheritanceScanTest.class.getDeclaredField("listOfReport").getGenericType();

        assertEquals(Report.class,
            routeRegistry.getByHandlerMethod(AlphaLookup.class, base).getDependencies().get(0).getReturnType(),
            "T must resolve against the controller class, not register as the variable T");
        java.lang.reflect.Type beta =
            routeRegistry.getByHandlerMethod(BetaLookup.class, base).getDependencies().get(0).getReturnType();
        assertEquals(listOfReportType, beta);
        assertEquals(listOfReportType.hashCode(), beta.hashCode());
        assertNull(routeRegistry.getByHandlerMethod(RawLookup.class, base).getDependencies().get(0).getReturnType(),
            "an unresolved T falls back to its bound (Object) — the untyped proxy");
        assertNull(routeRegistry.getByHandlerMethod(base),
            "one Method bound three ways must not resolve without the controller class");

        // The resolved type keys the injector's view cache by value: it shares a
        // view with an equal reflected type and never with another "T".
        MeshDependencyInjector injector = new MeshDependencyInjector();
        assertSame(injector.getToolProxy("lookup", beta), injector.getToolProxy("lookup", listOfReportType));
        assertNotSame(injector.getToolProxy("lookup", beta), injector.getToolProxy("lookup", Report.class));
        java.lang.reflect.Type rawT = base.getGenericParameterTypes()[0];
        java.lang.reflect.Type variable = ((java.lang.reflect.ParameterizedType) rawT).getActualTypeArguments()[0];
        assertSame(injector.getToolProxy("lookup"), injector.getToolProxy("lookup", variable),
            "an unresolved type variable must never get (or share) a typed view");
    }

    @Test
    @DisplayName("inherited generic handler: the early @Qualifier bean is typed by the resolved T")
    void registrarResolvesInheritedGenericType() {
        DefaultListableBeanFactory factory = new DefaultListableBeanFactory();
        factory.registerSingleton("meshDependencyInjector", new MeshDependencyInjector());
        factory.registerBeanDefinition("alpha", new RootBeanDefinition(AlphaLookup.class));

        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);

        assertEquals(Report.class, ((McpMeshToolProxy<?>) factory.getBean("lookup")).getReturnType());
    }

    @Test
    @DisplayName("self-referential bounds (E extends Enum<E>, T extends Comparable<T>) erase, no StackOverflow")
    void selfReferentialBoundsErase() {
        scanRoutes(new RawEnumController());
        scanRoutes(new GenericMethodController());
        assertEquals(Enum.class,
            routeRegistry.getByRoute("POST", "/enum").getDependencies().get(0).getReturnType());
        assertEquals(Comparable.class,
            routeRegistry.getByRoute("POST", "/cmp").getDependencies().get(0).getReturnType());

        DefaultListableBeanFactory factory = new DefaultListableBeanFactory();
        factory.registerBeanDefinition("enum", new RootBeanDefinition(RawEnumController.class));
        factory.registerBeanDefinition("cmp", new RootBeanDefinition(GenericMethodController.class));
        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);
        assertTrue(factory.containsBeanDefinition("enum_cap"));
        assertTrue(factory.containsBeanDefinition("cmp_cap"));
    }

    private MeshRouteHandlerInterceptor lookupInterceptor(MeshDependencyInjector injector) {
        scanRoutes(new AlphaLookup());
        scanRoutes(new BetaLookup());
        injector.updateToolDependency("lookup", "http://localhost:1", "lookup_fn");
        @SuppressWarnings("unchecked")
        ObjectProvider<MeshDependencyInjector> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(injector);
        return new MeshRouteHandlerInterceptor(routeRegistry, provider);
    }

    private static Object injectedType(MockHttpServletRequest request) {
        List<?> deps = (List<?>) request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        return ((McpMeshToolProxy<?>) deps.get(0)).getReturnType();
    }

    @Test
    @DisplayName("interceptor: one inherited Method serves each controller with its own typed deps")
    void interceptorResolvesPerController() throws Exception {
        MeshRouteHandlerInterceptor interceptor = lookupInterceptor(new MeshDependencyInjector());
        Method base = GenericLookupBase.class.getMethod("lookup", McpMeshTool.class);
        java.lang.reflect.Type listOfReportType =
            MeshWebHandlerInheritanceScanTest.class.getDeclaredField("listOfReport").getGenericType();

        MockHttpServletRequest alpha = new MockHttpServletRequest("POST", "/alpha/lookup");
        assertTrue(interceptor.preHandle(alpha, new MockHttpServletResponse(),
            new HandlerMethod(new AlphaLookup(), base)));
        assertEquals(Report.class, injectedType(alpha));

        MockHttpServletRequest beta = new MockHttpServletRequest("POST", "/beta/lookup");
        assertTrue(interceptor.preHandle(beta, new MockHttpServletResponse(),
            new HandlerMethod(new BetaLookup(), base)));
        assertEquals(listOfReportType, injectedType(beta));
    }

    @Test
    @DisplayName("interceptor: an ambiguous inherited route that matches no controller fails closed (503)")
    void interceptorFailsClosedWhenUnresolvable() throws Exception {
        MeshRouteHandlerInterceptor interceptor = lookupInterceptor(new MeshDependencyInjector());
        Method base = GenericLookupBase.class.getMethod("lookup", McpMeshTool.class);

        for (int i = 0; i < 2; i++) {
            MockHttpServletRequest request = new MockHttpServletRequest("POST", "/x/lookup");
            MockHttpServletResponse response = new MockHttpServletResponse();
            assertFalse(interceptor.preHandle(request, response,
                new HandlerMethod(new UnregisteredLookup(), base)),
                "the handler must not run with null McpMeshTools");
            assertEquals(503, response.getStatus());
            assertTrue(response.getContentAsString().contains("route_binding_unresolved"),
                response.getContentAsString());
            assertNull(request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR));
        }
    }

    @Test
    @DisplayName("registry: a class-less registration then a classed one with different deps still collides")
    void legacyThenClassedCollisionThrows() throws Exception {
        Method base = GenericLookupBase.class.getMethod("lookup", McpMeshTool.class);
        routeRegistry.register("POST", "/legacy", new MeshRouteRegistry.RouteMetadata(base,
            List.of(new MeshRouteRegistry.DependencySpec("one", new String[0], "", "one")), "", false));
        org.junit.jupiter.api.Assertions.assertThrows(IllegalStateException.class, () ->
            routeRegistry.register("POST", "/classed", new MeshRouteRegistry.RouteMetadata(AlphaLookup.class, base,
                List.of(new MeshRouteRegistry.DependencySpec("two", new String[0], "", "two")), "", false)));
    }

    // ── A2A ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshA2A declared on a base class registers and advertises its dependency")
    void inheritedA2ARegisters() {
        scanA2A(new InheritingA2AComponent());

        assertEquals(1, a2aRegistry.getAllSurfaces().size());
        MeshA2ARegistry.SurfaceMetadata md = a2aRegistry.getByPath("/agents/base");
        assertNotNull(md);
        assertEquals("a2a_lookup", md.dependencies().get(0).getCapability());
    }

    @Test
    @DisplayName("@MeshA2A override annotated on both levels registers once (no path collision)")
    void a2aOverrideRegistersOnce() throws Exception {
        scanA2A(new OverridingA2AComponent());

        assertEquals(1, a2aRegistry.getAllSurfaces().size());
        assertEquals(OverridingA2AComponent.class.getMethod("handle", Map.class, McpMeshTool.class),
            a2aRegistry.getByPath("/agents/base").method());
    }

    // ── early bean registrar ───────────────────────────────────────────

    @Test
    @DisplayName("capability bean registrar sees inherited @MeshRoute / @MeshA2A dependencies")
    void registrarSeesInheritedDependencies() {
        DefaultListableBeanFactory factory = new DefaultListableBeanFactory();
        factory.registerBeanDefinition("controller", new RootBeanDefinition(InheritingController.class));
        factory.registerBeanDefinition("a2a", new RootBeanDefinition(InheritingA2AComponent.class));

        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);

        assertTrue(factory.containsBeanDefinition("report_lookup"),
            "@Qualifier(\"report_lookup\") injection must resolve for an inherited route dependency");
        assertTrue(factory.containsBeanDefinition("a2a_lookup"));
    }
}
