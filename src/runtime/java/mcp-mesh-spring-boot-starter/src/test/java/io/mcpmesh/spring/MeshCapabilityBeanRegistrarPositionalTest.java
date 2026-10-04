package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.beans.factory.support.RootBeanDefinition;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteHandlerInterceptor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.method.HandlerMethod;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1568 B: the early capability-bean registrar read each
 * {@code McpMeshTool<T>} parameter's type argument by matching the parameter's
 * {@code @MeshInject} value or NAME against the capability. Binding has been
 * positional since 3.4.0 (#1401), so when names and positions disagree the
 * registrar typed the bean off the wrong parameter. It must use the same
 * positional pairing the route and A2A resolvers use — and, since each consumer
 * now gets its own typed proxy, handler parameter types never fail the boot;
 * only two different explicit {@code expectedType}s do.
 */
@DisplayName("#1568 B: capability bean registrar pairs McpMeshTool<T> positionally")
class MeshCapabilityBeanRegistrarPositionalTest {

    record Alpha(String a) {}
    record Beta(String b) {}

    /**
     * Names deliberately crossed against positions: dependency[0] is "alpha"
     * and binds to the FIRST injectable parameter (named "beta", typed Alpha).
     */
    @RestController
    public static class CrossedNamesController {
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "alpha"),
            @MeshDependency(capability = "beta")
        })
        @GetMapping("/crossed")
        public String crossed(McpMeshTool<Alpha> beta, McpMeshTool<Beta> alpha) {
            return "ok";
        }
    }

    /** Same crossing on an A2A surface; the leading Map is the message, not a slot. */
    public static class CrossedNamesA2A {
        @MeshA2A(path = "/agents/crossed", skillId = "crossed", skillName = "Crossed",
                 dependencies = {
                     @MeshDependency(capability = "a2a_alpha"),
                     @MeshDependency(capability = "a2a_beta")
                 })
        public Map<String, Object> handle(Map<String, Object> message,
                                          McpMeshTool<Alpha> a2a_beta,
                                          McpMeshTool<Beta> a2a_alpha) {
            return message;
        }
    }

    @MeshDependsOn(@MeshDependency(capability = "alpha", expectedType = Alpha.class))
    public static class AgreesWithPosition {}

    @MeshDependsOn(@MeshDependency(capability = "alpha", expectedType = Beta.class))
    public static class AgreesWithName {}

    private DefaultListableBeanFactory factory;

    @BeforeEach
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        factory = new DefaultListableBeanFactory();
        factory.registerSingleton("meshDependencyInjector", new MeshDependencyInjector());
    }

    @AfterEach
    void tearDown() {
        MeshSettleState.resetForTests();
    }

    private void register(String name, Class<?> type) {
        factory.registerBeanDefinition(name, new RootBeanDefinition(type));
    }

    private Object proxyReturnType(String capability) {
        Object bean = factory.getBean(capability);
        assertTrue(bean instanceof McpMeshToolProxy<?>, "expected a proxy bean for " + capability);
        return ((McpMeshToolProxy<?>) bean).getReturnType();
    }

    @Test
    @DisplayName("@MeshRoute: bean type follows the parameter's POSITION, not its name")
    void routeBeanTypedByPosition() {
        register("controller", CrossedNamesController.class);
        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);

        assertEquals(Alpha.class, proxyReturnType("alpha"));
        assertEquals(Beta.class, proxyReturnType("beta"));
    }

    @Test
    @DisplayName("@MeshA2A: bean type follows the parameter's POSITION, not its name")
    void a2aBeanTypedByPosition() {
        register("a2a", CrossedNamesA2A.class);
        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);

        assertEquals(Alpha.class, proxyReturnType("a2a_alpha"));
        assertEquals(Beta.class, proxyReturnType("a2a_beta"));
    }

    @Test
    @DisplayName("explicit expectedType agreeing with the positional handler type boots")
    void explicitAgreeingWithPositionBoots() {
        register("controller", CrossedNamesController.class);
        register("agrees", AgreesWithPosition.class);
        assertDoesNotThrow(() -> new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory));
        assertEquals(Alpha.class, proxyReturnType("alpha"));
    }

    @Test
    @DisplayName("explicit expectedType differing from a handler's McpMeshTool<T> boots; explicit types the bean")
    void explicitVersusHandlerTypeBoots() {
        // dependency 'alpha' binds positionally to McpMeshTool<Alpha>, while
        // @MeshDependsOn declares expectedType=Beta. Handler parameter types
        // never take part in the hard check: each consumer is typed by its own
        // declaration (the route by Alpha at request time, the bean by Beta).
        register("controller", CrossedNamesController.class);
        register("explicit", AgreesWithName.class);
        assertDoesNotThrow(() -> new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory));
        assertEquals(Beta.class, proxyReturnType("alpha"));
    }

    @MeshDependsOn(@MeshDependency(capability = "alpha", expectedType = Alpha.class))
    public static class ExplicitAlpha {}

    @Test
    @DisplayName("two different EXPLICIT expectedTypes for one capability still fail fast")
    void explicitVersusExplicitFails() {
        register("alpha-explicit", ExplicitAlpha.class);
        register("beta-explicit", AgreesWithName.class);
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory));
        assertTrue(e.getMessage().contains("conflicting expectedType"), e.getMessage());
    }

    @RestController
    public static class TwoTypesController {
        @MeshRoute(dependencies = @MeshDependency(capability = "weather"))
        @GetMapping("/forecast")
        public String forecast(McpMeshTool<Alpha> w) {
            return "";
        }

        @MeshRoute(dependencies = @MeshDependency(capability = "weather"))
        @GetMapping("/raw-text")
        public String rawText(McpMeshTool<String> w) {
            return "";
        }
    }

    @RestController
    public static class AgreeingTypesController {
        @MeshRoute(dependencies = @MeshDependency(capability = "agreed"))
        @GetMapping("/a1")
        public String a1(McpMeshTool<Alpha> w) {
            return "";
        }

        @MeshRoute(dependencies = @MeshDependency(capability = "agreed"))
        @GetMapping("/a2")
        public String a2(McpMeshTool<Alpha> w) {
            return "";
        }
    }

    @Test
    @DisplayName("handlers disagreeing on McpMeshTool<T> boot; the bean is untyped, each route typed")
    void handlersWithDifferentTypesBootAndStayTyped() throws Exception {
        register("controller", TwoTypesController.class);
        assertDoesNotThrow(() -> new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory));
        assertNull(proxyReturnType("weather"), "disagreeing handlers leave the @Qualifier bean dynamic");

        // At request time each route resolves its own typed proxy.
        MeshDependencyInjector injector = factory.getBean(MeshDependencyInjector.class);
        injector.updateToolDependency("weather", "http://localhost:1", "weather_fn");
        MeshRouteRegistry routes = new MeshRouteRegistry();
        new MeshRouteBeanPostProcessor(routes)
            .postProcessAfterInitialization(new TwoTypesController(), "controller");
        @SuppressWarnings("unchecked")
        ObjectProvider<MeshDependencyInjector> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(injector);
        MeshRouteHandlerInterceptor interceptor = new MeshRouteHandlerInterceptor(routes, provider);

        assertEquals(Alpha.class, requestProxyType(interceptor, "/forecast", "forecast"));
        assertEquals(String.class, requestProxyType(interceptor, "/raw-text", "rawText"));
    }

    @Test
    @DisplayName("handlers agreeing on McpMeshTool<T> type the bean")
    void agreeingHandlersTypeTheBean() {
        register("controller", AgreeingTypesController.class);
        new MeshCapabilityBeanRegistrar().postProcessBeanDefinitionRegistry(factory);
        assertEquals(Alpha.class, proxyReturnType("agreed"));
    }

    private static Object requestProxyType(MeshRouteHandlerInterceptor interceptor,
                                           String path, String methodName) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", path);
        Method m = TwoTypesController.class.getMethod(methodName, McpMeshTool.class);
        interceptor.preHandle(request, new MockHttpServletResponse(),
            new HandlerMethod(new TwoTypesController(), m));
        List<?> deps = (List<?>) request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        return ((McpMeshToolProxy<?>) deps.get(0)).getReturnType();
    }
}
