package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Characterization tests for {@code MeshA2ADispatcher.resolveDependency}'s
 * {@link McpMeshTool} branch — the {@code @MeshA2A} injection path (issue
 * #1401).
 *
 * <p><b>Why these exist.</b> Only the {@code MeshJobSubmitter} branch of the
 * dispatcher's argument binding had coverage;
 * {@link A2ATestFixtures} even carries a comment noting that "most tests don't
 * exercise {@code @MeshInject} parameter resolution". The conversion of
 * {@code @MeshA2A} from name-based to positional binding rewrites exactly this
 * code, so today's behaviour is pinned first — the rewrite of this file then
 * <b>is</b> the semantic change, made visible in a diff.
 *
 * <p><b>The contract being pinned:</b> the dispatcher derives a capability
 * <i>string</i> — {@code @MeshInject}'s value when non-empty, otherwise the raw
 * reflective parameter name — and linearly scans the surface's declared
 * dependencies for one whose capability or {@code DependencySpec} name equals
 * it. The parameter's position in the signature is never consulted.
 *
 * <p>Tests drive the real {@code tasks/send} dispatch path rather than calling
 * the private resolver, so what is pinned is the behaviour a user observes.
 */
@DisplayName("MeshA2ADispatcher: today's by-NAME dependency binding (issue #1401 characterization)")
class MeshA2ADispatcherDependencyBindingCharacterizationTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private ObjectMapper mapper;

    private McpMeshTool alphaProxy;
    private McpMeshTool betaProxy;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        alphaProxy = mock(McpMeshTool.class, "alpha-proxy");
        betaProxy = mock(McpMeshTool.class, "beta-proxy");
        CapturingBean.ARGS.remove();
    }

    @AfterEach
    void tearDown() {
        CapturingBean.ARGS.remove();
    }

    // ─────────────────────────────────────────────────────────────────
    // The pins
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshInject values agreeing with declaration order: each parameter gets its own proxy")
    void agreeingInjectValuesResolveToTheirOwnCapability() {
        dispatch("agreeing", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1));
    }

    @Test
    @DisplayName("PIN: @MeshInject value WINS over parameter position — declaration order is ignored")
    void nameBeatsPositionToday() {
        // Declaration order is [alpha, beta]; positional binding would give the
        // first injectable parameter the alpha proxy. Today the name decides.
        dispatch("disagreeing", List.of(dep("alpha"), dep("beta")));

        assertSame(betaProxy, CapturingBean.ARGS.get().get(0),
            "parameter annotated @MeshInject(\"beta\") must receive the beta proxy today");
        assertSame(alphaProxy, CapturingBean.ARGS.get().get(1),
            "parameter annotated @MeshInject(\"alpha\") must receive the alpha proxy today");
    }

    @Test
    @DisplayName("@MeshInject value matching no declared capability: null, dispatch still succeeds")
    void undeclaredInjectValueResolvesToNull() {
        dispatch("undeclared", List.of(dep("alpha"), dep("beta")));

        assertNull(CapturingBean.ARGS.get().get(0),
            "an unmatched capability is a debug-and-inject-null, not a failure");
    }

    @Test
    @DisplayName("No @MeshInject: the PARAMETER NAME is the lookup key")
    void parameterNameIsTheFallbackKey() {
        dispatch("parameterNameFallback", List.of(dep("alpha")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("No @MeshInject, kebab-case capability: the camelCased DependencySpec name matches")
    void camelCasedDependencySpecNameMatches() {
        // DependencySpec.fromAnnotation defaults the spec name to the camelCased
        // capability, and the dispatcher scans that field too.
        when(injector().getToolProxy("base-cap")).thenReturn(alphaProxy);
        dispatch("camelCasedParameterName",
            List.of(new MeshRouteRegistry.DependencySpec(
                "base-cap", new String[0], "", "baseCap")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("Declared dependency with no parameter naming it: simply unbound, no error")
    void surplusDeclaredDependencyIsIgnored() {
        dispatch("parameterNameFallback", List.of(dep("alpha"), dep("beta")));

        assertEquals(1, CapturingBean.ARGS.get().size(),
            "handler has one injectable slot; the second declared dependency binds nowhere");
        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("@MeshInject on a NON-McpMeshTool parameter is also a dependency slot on the A2A path")
    void meshInjectOnNonProxyTypeIsStillASlot() {
        // Divergence from @MeshRoute: the dispatcher owns the whole argument
        // array, so @MeshInject claims any parameter type. The injector returns
        // an McpMeshTool, which is then assigned into an Object slot.
        dispatch("injectOnObjectParam", List.of(dep("alpha")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private MeshDependencyInjector injectorMock;

    private MeshDependencyInjector injector() {
        if (injectorMock == null) {
            injectorMock = mock(MeshDependencyInjector.class);
            when(injectorMock.getToolProxy(anyString())).thenReturn(null);
            when(injectorMock.getToolProxy("alpha")).thenReturn(alphaProxy);
            when(injectorMock.getToolProxy("beta")).thenReturn(betaProxy);
        }
        return injectorMock;
    }

    private void dispatch(String handlerMethod, List<MeshRouteRegistry.DependencySpec> deps) {
        MeshDependencyInjector injector = injector();
        registry.register(surfaceFor("/svc", "skill-" + handlerMethod, handlerMethod, deps));
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, provider(injector));
        dispatcher.dispatch("/svc", A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t1", "message", Map.of("text", "hi"))));
    }

    private static MeshA2ARegistry.SurfaceMetadata surfaceFor(
            String path, String skillId, String handlerMethod,
            List<MeshRouteRegistry.DependencySpec> deps) {

        Method method = null;
        for (Method m : CapturingBean.class.getDeclaredMethods()) {
            if (m.getName().equals(handlerMethod)) {
                method = m;
            }
        }
        if (method == null) {
            throw new AssertionError("No such handler: " + handlerMethod);
        }
        return new MeshA2ARegistry.SurfaceMetadata(
            path, skillId, skillId, "", List.of(), deps, "",
            "CapturingBean." + handlerMethod, new CapturingBean(), method);
    }

    private static MeshRouteRegistry.DependencySpec dep(String capability) {
        return new MeshRouteRegistry.DependencySpec(
            capability, new String[0], "", capability);
    }

    private static ObjectProvider<MeshDependencyInjector> provider(MeshDependencyInjector injector) {
        return new ObjectProvider<>() {
            @Override public MeshDependencyInjector getObject() { return injector; }
            @Override public MeshDependencyInjector getObject(Object... args) { return injector; }
            @Override public MeshDependencyInjector getIfAvailable() { return injector; }
            @Override public MeshDependencyInjector getIfUnique() { return injector; }
        };
    }

    /**
     * Handler bean recording exactly what landed in each injectable slot, in
     * signature order.
     */
    @SuppressWarnings("unused")
    public static class CapturingBean {

        static final ThreadLocal<List<Object>> ARGS = new ThreadLocal<>();

        public Object agreeing(
                Map<String, Object> message,
                @MeshInject("alpha") McpMeshTool a,
                @MeshInject("beta") McpMeshTool b) {
            return capture(a, b);
        }

        public Object disagreeing(
                Map<String, Object> message,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return capture(first, second);
        }

        public Object undeclared(
                Map<String, Object> message,
                @MeshInject("nope") McpMeshTool ghost) {
            return capture(ghost);
        }

        public Object parameterNameFallback(Map<String, Object> message, McpMeshTool alpha) {
            return capture(alpha);
        }

        public Object camelCasedParameterName(Map<String, Object> message, McpMeshTool baseCap) {
            return capture(baseCap);
        }

        public Object injectOnObjectParam(
                Map<String, Object> message,
                @MeshInject("alpha") Object anything) {
            return capture(anything);
        }

        private static Object capture(Object... args) {
            List<Object> captured = new ArrayList<>();
            for (Object arg : args) {
                captured.add(arg);
            }
            ARGS.set(captured);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("ok", true);
            return result;
        }
    }
}
