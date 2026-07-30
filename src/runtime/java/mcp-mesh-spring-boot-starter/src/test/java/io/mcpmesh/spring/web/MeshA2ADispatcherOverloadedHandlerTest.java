package io.mcpmesh.spring.web;

import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.spring.MeshRuntime;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Two {@code @MeshA2A} handlers with the SAME method name must each get their
 * own argument plan (issue #1401).
 *
 * <p>{@code handlerMethodId} is {@code "ClassName.methodName"} — parameter types
 * are not part of it, so overloads share one id. {@link MeshA2ARegistry} dedupes
 * surfaces by {@code path}, not by handler id, so both overloads register as
 * distinct surfaces. Keying the plan cache by that id therefore handed the
 * second overload the FIRST one's plan: an out-of-bounds throw when the arities
 * differ, and silent misbinding when they agree. The cache is keyed by the
 * resolved {@link Method} instead.
 */
@DisplayName("MeshA2ADispatcher: overloaded @MeshA2A handlers get separate argument plans")
class MeshA2ADispatcherOverloadedHandlerTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private ObjectMapper mapper;
    private MeshA2ADispatcher dispatcher;

    private McpMeshTool alphaProxy;
    private McpMeshTool betaProxy;
    private MeshDependencyInjector injector;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        alphaProxy = mock(McpMeshTool.class, "alpha-proxy");
        betaProxy = mock(McpMeshTool.class, "beta-proxy");
        injector = mock(MeshDependencyInjector.class);
        when(injector.getToolProxy(anyString())).thenReturn(null);
        when(injector.getToolProxy("alpha")).thenReturn(alphaProxy);
        when(injector.getToolProxy("beta")).thenReturn(betaProxy);
        dispatcher = new MeshA2ADispatcher(registry, taskStore, mapper, provider(injector));
        OverloadBean.CAPTURES.remove();
        OverloadBean.SUBMITTERS.remove();
    }

    @AfterEach
    void tearDown() {
        OverloadBean.CAPTURES.remove();
        OverloadBean.SUBMITTERS.remove();
    }

    @Test
    @DisplayName("Overloads of differing arity: the wider one is not invoked with the narrower plan")
    void differingArityDoesNotReuseTheNarrowPlan() {
        register("/arity-two", "arity", "two", Map.class, McpMeshTool.class);
        register("/arity-three", "arity", "three", Map.class, Object.class, McpMeshTool.class);

        // Narrow overload first — it is what populates the cache.
        assertEquals("completed", dispatch("/arity-two", "t1"));
        assertSame(alphaProxy, captured("two").get(0));

        assertEquals("completed", dispatch("/arity-three", "t2"),
            "the 3-parameter overload must not be planned as if it had 2 parameters");
        List<Object> three = captured("three");
        assertNotNull(three, "the 3-parameter overload never ran");
        assertNull(three.get(0), "the Object spacer binds nothing");
        assertSame(betaProxy, three.get(1),
            "the 3-parameter overload's own dependency reaches its own slot");
    }

    @Test
    @DisplayName("Overloads of equal arity: a dependency at a different position is not misbound")
    void equalArityDoesNotMisbindTheDependency() {
        register("/shift-early", "shifted", "early", Map.class, McpMeshTool.class, Object.class);
        register("/shift-late", "shifted", "late", Map.class, Object.class, McpMeshTool.class);

        assertEquals("completed", dispatch("/shift-early", "t1"));
        List<Object> early = captured("early");
        assertSame(alphaProxy, early.get(0));
        assertNull(early.get(1));

        assertEquals("completed", dispatch("/shift-late", "t2"));
        List<Object> late = captured("late");
        assertNull(late.get(0),
            "the Object parameter is UNBOUND here — it must not receive the proxy the other "
                + "overload's plan puts at this position");
        assertSame(betaProxy, late.get(1), "the McpMeshTool parameter receives the dependency");
    }

    @Test
    @DisplayName("Overloads with the same role layout still resolve their OWN declared capability")
    void sameRoleLayoutStillUsesItsOwnCapabilities() {
        // Identical role layout ([MESSAGE, DEPENDENCY]) — only the declared
        // dependency differs, which lives on the surface and is baked into the
        // plan's binding. Nothing here can throw; a shared plan is silent.
        register("/caps-alpha", "caps", "alphaSide", Map.class, McpMeshTool.class);
        register("/caps-beta", "caps", "betaSide", Object.class, McpMeshTool.class);

        assertEquals("completed", dispatch("/caps-alpha", "t1"));
        assertSame(alphaProxy, captured("alphaSide").get(0));

        assertEquals("completed", dispatch("/caps-beta", "t2"));
        assertSame(betaProxy, captured("betaSide").get(0),
            "the second overload declares 'beta' and must receive the beta proxy");
    }

    @Test
    @DisplayName("Each overload gets a MeshJobSubmitter bound to ITS OWN capability")
    void jobSubmitterIsNotSharedAcrossOverloads() {
        // The submitter cache had the same collision as the plan cache, one
        // field away. Capability comes from the surface (first @MeshDependency,
        // else skillId kebab-to-snake), so a shared cache entry points the
        // second overload's submitter at the first overload's capability —
        // jobs get submitted under the wrong capability, silently.
        registerSubmitterSurface("/job-first", "job-first", Map.class);
        registerSubmitterSurface("/job-second", "job-second", Object.class);

        MeshRuntime runtime = mock(MeshRuntime.class);
        AgentSpec spec = new AgentSpec();
        spec.setAgentId("overload-agent");
        spec.setRegistryUrl("http://localhost:8000");
        when(runtime.getAgentSpec()).thenReturn(spec);
        dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, provider(injector), singletonProvider(runtime));

        assertEquals("completed", dispatch("/job-first", "t1"));
        assertEquals("job_first", submitter("first").capability());

        assertEquals("completed", dispatch("/job-second", "t2"));
        assertEquals("job_second", submitter("second").capability(),
            "the second overload's submitter must target its own skill's capability");
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    /**
     * Register one overload as its own surface. The declared dependency is
     * {@code alpha} for the first surface of each pair and {@code beta} for the
     * second, so a plan leak shows up as the wrong proxy.
     */
    private void register(String path, String methodName, String label, Class<?>... paramTypes) {
        Method method;
        try {
            method = OverloadBean.class.getDeclaredMethod(methodName, paramTypes);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("No such overload: " + methodName, e);
        }
        String capability = registry.size() == 0 ? "alpha" : "beta";
        registry.register(new MeshA2ARegistry.SurfaceMetadata(
            path, "skill-" + label, "skill-" + label, "", List.of(),
            List.of(new MeshRouteRegistry.DependencySpec(
                capability, new String[0], "", capability)),
            "",
            // The colliding key, built exactly as MeshA2ABeanPostProcessor does.
            OverloadBean.class.getName() + "." + methodName,
            new OverloadBean(), method));
    }

    /**
     * Register one {@code submitJob} overload as its own surface, with no
     * declared dependency so the submitter capability comes from {@code skillId}
     * (kebab-to-snake) and therefore differs between the two overloads.
     */
    private void registerSubmitterSurface(String path, String skillId, Class<?> messageParamType) {
        Method method;
        try {
            method = OverloadBean.class.getDeclaredMethod(
                "submitJob", messageParamType, MeshJobSubmitter.class);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("No such overload: submitJob", e);
        }
        registry.register(new MeshA2ARegistry.SurfaceMetadata(
            path, skillId, skillId, "", List.of(), List.of(), "",
            OverloadBean.class.getName() + ".submitJob",
            new OverloadBean(), method));
    }

    /** @return the task state from the JSON-RPC envelope. */
    private String dispatch(String path, String taskId) {
        ResponseEntity<String> resp = dispatcher.dispatch(path,
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", taskId, "message", Map.of("text", "hi"))));
        JsonNode env = mapper.readTree(resp.getBody());
        JsonNode result = env.get("result");
        assertNotNull(result, "no result in response: " + resp.getBody());
        String state = result.get("status").get("state").asText();
        if (!"completed".equals(state)) {
            // Surface the handler failure text — an out-of-bounds plan lookup
            // lands here as a state=failed task.
            return state + ": " + result.get("status").toString();
        }
        return state;
    }

    private List<Object> captured(String label) {
        Map<String, List<Object>> all = OverloadBean.CAPTURES.get();
        return all == null ? null : all.get(label);
    }

    private MeshJobSubmitter submitter(String label) {
        Map<String, MeshJobSubmitter> all = OverloadBean.SUBMITTERS.get();
        MeshJobSubmitter s = all == null ? null : all.get(label);
        assertNotNull(s, "no MeshJobSubmitter captured for '" + label + "'");
        return s;
    }

    private static ObjectProvider<MeshRuntime> singletonProvider(MeshRuntime runtime) {
        return new ObjectProvider<>() {
            @Override public MeshRuntime getObject() { return runtime; }
            @Override public MeshRuntime getObject(Object... args) { return runtime; }
            @Override public MeshRuntime getIfAvailable() { return runtime; }
            @Override public MeshRuntime getIfUnique() { return runtime; }
        };
    }

    private static ObjectProvider<MeshDependencyInjector> provider(MeshDependencyInjector injector) {
        return new ObjectProvider<>() {
            @Override public MeshDependencyInjector getObject() { return injector; }
            @Override public MeshDependencyInjector getObject(Object... args) { return injector; }
            @Override public MeshDependencyInjector getIfAvailable() { return injector; }
            @Override public MeshDependencyInjector getIfUnique() { return injector; }
        };
    }

    /** Overloaded handlers recording what landed in each non-message parameter. */
    @SuppressWarnings("unused")
    public static class OverloadBean {

        static final ThreadLocal<Map<String, List<Object>>> CAPTURES = new ThreadLocal<>();
        static final ThreadLocal<Map<String, MeshJobSubmitter>> SUBMITTERS = new ThreadLocal<>();

        public Object submitJob(Map<String, Object> message, MeshJobSubmitter submitter) {
            return captureSubmitter("first", submitter);
        }

        public Object submitJob(Object message, MeshJobSubmitter submitter) {
            return captureSubmitter("second", submitter);
        }

        public Object arity(Map<String, Object> message, McpMeshTool a) {
            return capture("two", a);
        }

        public Object arity(Map<String, Object> message, Object spacer, McpMeshTool b) {
            return capture("three", spacer, b);
        }

        public Object shifted(Map<String, Object> message, McpMeshTool a, Object spacer) {
            return capture("early", a, spacer);
        }

        public Object shifted(Map<String, Object> message, Object spacer, McpMeshTool b) {
            return capture("late", spacer, b);
        }

        public Object caps(Map<String, Object> message, McpMeshTool a) {
            return capture("alphaSide", a);
        }

        public Object caps(Object message, McpMeshTool b) {
            return capture("betaSide", b);
        }

        private static Object captureSubmitter(String label, MeshJobSubmitter submitter) {
            Map<String, MeshJobSubmitter> all = SUBMITTERS.get();
            if (all == null) {
                all = new HashMap<>();
                SUBMITTERS.set(all);
            }
            if (submitter == null) {
                throw new IllegalStateException("submitter was null for " + label);
            }
            all.put(label, submitter);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("ok", label);
            return result;
        }

        private static Object capture(String label, Object... args) {
            Map<String, List<Object>> all = CAPTURES.get();
            if (all == null) {
                all = new HashMap<>();
                CAPTURES.set(all);
            }
            all.put(label, new ArrayList<>(java.util.Arrays.asList(args)));
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("ok", label);
            return result;
        }
    }
}
