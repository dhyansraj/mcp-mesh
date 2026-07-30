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
 * Characterization tests for {@code MeshA2ADispatcher}'s argument binding — the
 * {@code @MeshA2A} injection path (issue #1401).
 *
 * <p><b>What changed.</b> This file previously pinned by-NAME binding: the
 * dispatcher derived a capability string from {@code @MeshInject}'s value or the
 * reflective parameter name and linearly scanned the surface's declared
 * dependencies for a match, so the parameter's position was never consulted. It
 * now pins the POSITIONAL contract: the Nth injectable parameter in signature
 * order receives the Nth declared {@code @MeshDependency}, and no name is
 * consulted at dispatch time. The diff against the previous revision of this
 * file <b>is</b> the semantic change.
 *
 * <p>What did <i>not</i> change, and is re-pinned here because the rewrite of
 * {@code invokeHandler} could easily have broken it: A2A's slot rules are wider
 * than the route's ({@code @MeshInject} claims any parameter type), and the four
 * parameter roles have a precedence order that used to be implicit in an if/else
 * chain and is now written out.
 *
 * <p>Tests drive the real {@code tasks/send} dispatch path rather than calling
 * the private resolver, so what is pinned is the behaviour a user observes.
 */
@DisplayName("MeshA2ADispatcher: POSITIONAL dependency binding (issue #1401)")
class MeshA2ADispatcherDependencyBindingCharacterizationTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private ObjectMapper mapper;

    private McpMeshTool alphaProxy;
    private McpMeshTool betaProxy;
    private McpMeshTool gammaProxy;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        alphaProxy = mock(McpMeshTool.class, "alpha-proxy");
        betaProxy = mock(McpMeshTool.class, "beta-proxy");
        gammaProxy = mock(McpMeshTool.class, "gamma-proxy");
        CapturingBean.ARGS.remove();
    }

    @AfterEach
    void tearDown() {
        CapturingBean.ARGS.remove();
    }

    // ─────────────────────────────────────────────────────────────────
    // The contract
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("The Nth injectable parameter receives the Nth declared dependency")
    void slotOrdinalSelectsTheDependency() {
        dispatch("agreeing", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1));
    }

    @Test
    @DisplayName("PIN: POSITION wins — a reversed @MeshInject value does not swap the proxies")
    void positionBeatsName() {
        // Declaration order is [alpha, beta]. The first injectable parameter is
        // annotated @MeshInject("beta"), which under the pre-3.4 rule handed it
        // the beta proxy. Position decides now — and this exact shape is refused
        // at boot, so the value can never be a lie in practice.
        dispatch("disagreeing", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0),
            "slot 0 takes dependency[0] regardless of what @MeshInject says");
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1),
            "slot 1 takes dependency[1] regardless of what @MeshInject says");
    }

    @Test
    @DisplayName("PIN: a parameter NAME matching another capability does not redirect the binding")
    void parameterNameIsNotConsulted() {
        // The first injectable parameter is literally named "beta".
        dispatch("misleadingNames", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1));
    }

    @Test
    @DisplayName("PIN: @MeshInject is inert at dispatch time — even a value naming nothing binds")
    void annotationIsInertAtDispatchTime() {
        dispatch("undeclared", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0),
            "@MeshInject(\"nope\") on slot 0 still receives dependency[0]");
    }

    @Test
    @DisplayName("A kebab-case capability needs no camelCase parameter name to bind")
    void kebabCaseCapabilityBindsWithoutANameMatch() {
        when(injector().getToolProxy("base-cap")).thenReturn(alphaProxy);
        dispatch("camelCasedParameterName",
            List.of(new MeshRouteRegistry.DependencySpec(
                "base-cap", new String[0], "", "baseCap")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("Declared dependency with no parameter to reach it: simply unbound, no error")
    void surplusDeclaredDependencyIsIgnored() {
        dispatch("parameterNameFallback", List.of(dep("alpha"), dep("beta")));

        assertEquals(1, CapturingBean.ARGS.get().size(),
            "handler has one injectable slot; the second declared dependency binds nowhere");
        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("More injectable parameters than dependencies: the surplus is null")
    void surplusSlotIsNull() {
        dispatch("three", List.of(dep("alpha"), dep("beta")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1));
        assertNull(CapturingBean.ARGS.get().get(2),
            "no dependency is declared at index 2");
    }

    // ─────────────────────────────────────────────────────────────────
    // Slot preservation (issue #1390)
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("SLOT PRESERVATION: an unresolvable MIDDLE dependency does not shift the later ones")
    void unresolvedMiddleDependencyHoldsItsOwnSlot() {
        // 'beta_down' resolves to null through the injector — the provider is
        // gone. Every other parameter must keep its own proxy.
        dispatch("three", List.of(dep("alpha"), dep("beta_down"), dep("gamma")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0), "slot 0 keeps its own proxy");
        assertNull(CapturingBean.ARGS.get().get(1),
            "the unresolvable dependency leaves ITS OWN slot null");
        assertSame(gammaProxy, CapturingBean.ARGS.get().get(2),
            "slot 2 must still receive gamma — it must not slide up into slot 1");
    }

    @Test
    @DisplayName("SLOT PRESERVATION: only the middle dependency resolvable fills only the middle slot")
    void resolvedMiddleDependencyDoesNotSlideDown() {
        dispatch("three", List.of(dep("alpha_down"), dep("beta"), dep("gamma_down")));

        assertNull(CapturingBean.ARGS.get().get(0));
        assertSame(betaProxy, CapturingBean.ARGS.get().get(1),
            "the single resolvable dependency lands in ITS slot, not slot 0");
        assertNull(CapturingBean.ARGS.get().get(2));
    }

    // ─────────────────────────────────────────────────────────────────
    // A2A's slot rules and role precedence — unchanged, re-pinned
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshInject on a NON-McpMeshTool parameter is still a dependency slot on the A2A path")
    void meshInjectOnNonProxyTypeIsStillASlot() {
        // Divergence from @MeshRoute: the dispatcher owns the whole argument
        // array, so @MeshInject claims any parameter type. It consumes a
        // positional slot like any other.
        dispatch("injectOnObjectParam", List.of(dep("alpha")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
    }

    @Test
    @DisplayName("A dependency slot at index 0 does not steal the message: it moves to the Map")
    void dependencySlotAndMessageCoexist() {
        dispatch("injectBeforeMessage", List.of(dep("alpha")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0),
            "the dependency role outranks the message's index-0 fallback");
        assertEquals("message", CapturingBean.ARGS.get().get(1),
            "the message still finds the first UNCLAIMED Map parameter");
    }

    @Test
    @DisplayName("An McpMeshTool at parameter 0 beats the message's index-0 fallback")
    void dependencySlotBeatsTheIndexZeroMessageFallback() {
        // The message's "parameter 0 if nothing else claimed it" fallback and a
        // dependency slot both want index 0. Slots win — previously only
        // because the dependency branch was tested first.
        dispatch("proxyFirstNoMap", List.of(dep("alpha")));

        assertSame(alphaProxy, CapturingBean.ARGS.get().get(0));
        assertNull(CapturingBean.ARGS.get().get(1),
            "the non-Map parameter 1 is not eligible for the index-0 fallback");
    }

    @Test
    @DisplayName("A non-Map parameter 0 still takes the message when nothing else claimed it")
    void indexZeroFallbackStillApplies() {
        dispatch("pojoMessage", List.of(dep("alpha")));

        assertEquals("message", CapturingBean.ARGS.get().get(0),
            "parameter 0 takes the message even though it is not a Map");
        assertSame(alphaProxy, CapturingBean.ARGS.get().get(1));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private MeshDependencyInjector injectorMock;

    private MeshDependencyInjector injector() {
        if (injectorMock == null) {
            injectorMock = mock(MeshDependencyInjector.class);
            // Anything ending in _down is an unresolvable capability.
            when(injectorMock.getToolProxy(anyString())).thenReturn(null);
            when(injectorMock.getToolProxy("alpha")).thenReturn(alphaProxy);
            when(injectorMock.getToolProxy("beta")).thenReturn(betaProxy);
            when(injectorMock.getToolProxy("gamma")).thenReturn(gammaProxy);
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
     * Handler bean recording exactly what landed in each captured slot, in
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

        public Object misleadingNames(
                Map<String, Object> message,
                McpMeshTool beta,
                McpMeshTool alpha) {
            return capture(beta, alpha);
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

        public Object three(
                Map<String, Object> message,
                McpMeshTool a,
                McpMeshTool b,
                McpMeshTool c) {
            return capture(a, b, c);
        }

        public Object injectOnObjectParam(
                Map<String, Object> message,
                @MeshInject("alpha") Object anything) {
            return capture(anything);
        }

        public Object injectBeforeMessage(
                @MeshInject("alpha") Object claimed,
                Map<String, Object> message) {
            return capture(claimed, message == null ? null : "message");
        }

        public Object proxyFirstNoMap(McpMeshTool a, String notAMessage) {
            return capture(a, notAMessage);
        }

        public Object pojoMessage(Object message, McpMeshTool a) {
            return capture(message == null ? null : "message", a);
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
