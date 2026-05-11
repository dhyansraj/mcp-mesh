package io.mcpmesh.spring.web;

import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshRuntime;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link MeshA2ADispatcher}'s framework auto-injection of
 * {@link MeshJobSubmitter} parameter slots on {@code @MeshA2A} handlers
 * (issue #936).
 *
 * <p>Mirrors what TS coverage of the same feature asserts on
 * {@code mesh.a2a.mount(...)}:
 *
 * <ul>
 *   <li>A handler declaring a {@code MeshJobSubmitter} parameter gets a
 *       non-null instance at call time (no more {@code @Lazy MeshRuntime}
 *       autowire dance in user code).</li>
 *   <li>The submitter's {@code capability} defaults to the first declared
 *       {@code @MeshDependency} entry when present.</li>
 *   <li>Otherwise the capability defaults to {@code skillId} with
 *       {@code '-'} replaced by {@code '_'} — the canonical
 *       kebab-to-snake mapping that matches the existing
 *       producer-report-agent example (skill {@code "generate-report"} →
 *       capability {@code "generate_report"}).</li>
 *   <li>{@code submittedBy} equals the {@link MeshRuntime}'s agent id.</li>
 *   <li>{@code registryUrl} is sourced from the agent spec.</li>
 *   <li>The dispatcher caches one submitter per surface (calls do not
 *       reconstruct a fresh instance for every request).</li>
 *   <li>When the {@link MeshRuntime} provider is null OR returns null
 *       (transient startup), the parameter is filled with {@code null}
 *       rather than crashing the dispatch.</li>
 * </ul>
 */
@DisplayName("MeshA2ADispatcher: framework MeshJobSubmitter injection (issue #936)")
class MeshA2ADispatcherJobSubmitterInjectionTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private ObjectMapper mapper;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        SubmitterCapturingBean.LAST_SUBMITTER.set(null);
    }

    @AfterEach
    void tearDown() {
        SubmitterCapturingBean.LAST_SUBMITTER.set(null);
    }

    @Test
    @DisplayName("Handler with MeshJobSubmitter param: framework injects non-null bound to skill-derived capability")
    void injectsMeshJobSubmitterFromSkillIdFallback() throws Exception {
        registry.register(surfaceFor("/svc", "generate-report", List.of()));

        MeshRuntime runtime = mockRuntime("report-a2a-agent-abcd1234", "http://localhost:8000");
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider(),
            singletonProvider(runtime));

        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t1", "message", Map.of()));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);

        assertEquals(200, resp.getStatusCode().value());
        MeshJobSubmitter submitter = SubmitterCapturingBean.LAST_SUBMITTER.get();
        assertNotNull(submitter, "Framework must inject a non-null MeshJobSubmitter");
        // Skill-id fallback: "generate-report" -> "generate_report".
        assertEquals("generate_report", submitter.capability(),
            "Default capability must be skillId with '-' replaced by '_'");
        assertEquals("report-a2a-agent-abcd1234", submitter.submittedBy(),
            "submittedBy must equal the runtime's agentId");
    }

    @Test
    @DisplayName("Handler with declared @MeshDependency: submitter capability matches first dep")
    void firstDeclaredDependencyWinsOverSkillIdFallback() throws Exception {
        registry.register(surfaceFor("/svc", "generate-report",
            List.of(stubDep("custom_task_cap"))));

        MeshRuntime runtime = mockRuntime("report-a2a-agent-xyz", "http://localhost:8000");
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider(),
            singletonProvider(runtime));

        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t1", "message", Map.of()));
        dispatcher.dispatch("/svc", body);

        MeshJobSubmitter submitter = SubmitterCapturingBean.LAST_SUBMITTER.get();
        assertNotNull(submitter);
        assertEquals("custom_task_cap", submitter.capability(),
            "Declared @MeshDependency capability must override the skillId fallback");
    }

    @Test
    @DisplayName("Submitter is cached per surface — repeat calls reuse the same instance")
    void submitterIsCachedPerSurface() throws Exception {
        registry.register(surfaceFor("/svc", "generate-report", List.of()));

        MeshRuntime runtime = mockRuntime("agent-1", "http://localhost:8000");
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider(),
            singletonProvider(runtime));

        dispatcher.dispatch("/svc", A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t1", "message", Map.of())));
        MeshJobSubmitter first = SubmitterCapturingBean.LAST_SUBMITTER.get();

        dispatcher.dispatch("/svc", A2ATestFixtures.jsonRpcBody(2, "tasks/send",
            Map.of("id", "t2", "message", Map.of())));
        MeshJobSubmitter second = SubmitterCapturingBean.LAST_SUBMITTER.get();

        assertNotNull(first);
        assertSame(first, second,
            "MeshJobSubmitter must be cached per surface (one instance reused across requests)");
    }

    @Test
    @DisplayName("MeshRuntime unavailable: param injected as null, dispatch still succeeds")
    void runtimeUnavailable_fallsBackToNull() throws Exception {
        registry.register(surfaceFor("/svc", "generate-report", List.of()));

        // Provider that always returns null — simulates the runtime not
        // yet being available (e.g. mid-startup).
        ObjectProvider<MeshRuntime> nullProvider = new ObjectProvider<>() {
            @Override public MeshRuntime getObject() { return null; }
            @Override public MeshRuntime getObject(Object... args) { return null; }
            @Override public MeshRuntime getIfAvailable() { return null; }
            @Override public MeshRuntime getIfUnique() { return null; }
        };
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider(),
            nullProvider);

        ResponseEntity<String> resp = dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", "t1", "message", Map.of())));

        assertEquals(200, resp.getStatusCode().value());
        // The handler stashes null on the slot — it must not crash; user
        // code surfaces the missing-submitter case as a failed Task.
        // SubmitterCapturingBean#handler treats a null submitter as a
        // controlled error → state=failed.
        JsonNode env = mapper.readTree(resp.getBody());
        String state = env.get("result").get("status").get("state").asText();
        assertEquals("failed", state,
            "Handler observing null submitter must surface state=failed (not 500)");
    }

    @Test
    @DisplayName("Class load + dispatch resilient when runtimeProvider.getIfAvailable() throws")
    void dispatcherClassLoadIsIndependentOfRuntimeProviderHealth() throws Exception {
        // Regression for the BLOCKER review finding: the dispatcher used to
        // construct a static sentinel MeshJobSubmitter at class load via
        // an unguarded constructor call. If MeshJobSubmitter ever started
        // doing real work in its constructor (FFI load, registry registration,
        // etc.), class load would cascade-fail with ExceptionInInitializerError
        // and brick the entire A2A starter — even for surfaces that don't use
        // MeshJobSubmitter at all.
        //
        // The two-collection refactor eliminates that risk: we no longer
        // construct a sentinel statically. This test asserts the contract
        // structurally by wiring a runtime provider whose getIfAvailable()
        // raises — equivalent in effect to "MeshJobSubmitter ctor would
        // explode" without our test needing to depend on the ctor's health.
        // The dispatcher must:
        //   (a) construct without throwing,
        //   (b) handle the explosion from getIfAvailable() gracefully,
        //   (c) inject null into the MeshJobSubmitter slot,
        //   (d) NOT memoize this transient failure (next call retries).
        registry.register(surfaceFor("/svc", "generate-report", List.of()));

        AtomicReference<Integer> providerCalls = new AtomicReference<>(0);
        ObjectProvider<MeshRuntime> faultyProvider = new ObjectProvider<>() {
            @Override public MeshRuntime getObject() { throw new IllegalStateException("bean init failed"); }
            @Override public MeshRuntime getObject(Object... args) { throw new IllegalStateException("bean init failed"); }
            @Override public MeshRuntime getIfAvailable() {
                providerCalls.updateAndGet(v -> v + 1);
                throw new IllegalStateException("simulated bean-init failure");
            }
            @Override public MeshRuntime getIfUnique() { throw new IllegalStateException("bean init failed"); }
        };

        // (a) Dispatcher constructs cleanly even though the provider would
        // throw if asked.
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider(),
            faultyProvider);
        assertNotNull(dispatcher);

        // (b) + (c) First call falls through to null injection without
        // crashing the dispatch. The handler bean treats null submitter as
        // a controlled error → state=failed.
        ResponseEntity<String> resp = dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", "t1", "message", Map.of())));
        assertEquals(200, resp.getStatusCode().value(),
            "Dispatcher must not surface provider faults as HTTP errors");
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals("failed", env.get("result").get("status").get("state").asText());
        assertEquals(1, providerCalls.get(),
            "Provider must have been consulted exactly once on the first call");

        // (d) Second call also invokes the provider — the provider fault is
        // treated as transient, NOT memoized as permanent-unbuildable.
        ResponseEntity<String> resp2 = dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(2, "tasks/send",
                Map.of("id", "t2", "message", Map.of())));
        assertEquals(200, resp2.getStatusCode().value());
        assertEquals(2, providerCalls.get(),
            "Transient provider fault must NOT be cached — provider must be retried on the next call");
    }

    @Test
    @DisplayName("Three-arg dispatcher constructor: handler with submitter param gets null (back-compat)")
    void legacyConstructor_doesNotCrashOnMeshJobSubmitterParam() throws Exception {
        registry.register(surfaceFor("/svc", "generate-report", List.of()));

        // Use the legacy four-arg constructor (no MeshRuntime provider).
        MeshA2ADispatcher dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper,
            A2ATestFixtures.emptyInjectorProvider());

        ResponseEntity<String> resp = dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", "t1", "message", Map.of())));

        assertEquals(200, resp.getStatusCode().value(),
            "Legacy constructor must not crash on MeshJobSubmitter params");
        JsonNode env = mapper.readTree(resp.getBody());
        // Handler gets null submitter and surfaces failed — same fallback
        // as the runtime-unavailable case.
        assertEquals("failed", env.get("result").get("status").get("state").asText());
    }

    // ────────────────────────────────────────────────────────────────────
    // Fixtures
    // ────────────────────────────────────────────────────────────────────

    /**
     * Build a surface metadata that points at
     * {@link SubmitterCapturingBean#handler(Map, MeshJobSubmitter)}.
     */
    private static MeshA2ARegistry.SurfaceMetadata surfaceFor(
            String path,
            String skillId,
            List<MeshRouteRegistry.DependencySpec> deps) {
        SubmitterCapturingBean bean = new SubmitterCapturingBean();
        Method method;
        try {
            method = SubmitterCapturingBean.class.getDeclaredMethod(
                "handler", Map.class, MeshJobSubmitter.class);
        } catch (NoSuchMethodException e) {
            throw new AssertionError(e);
        }
        return new MeshA2ARegistry.SurfaceMetadata(
            path,
            skillId,
            skillId,
            "",
            List.of(),
            deps,
            "",
            "SubmitterCapturingBean.handler[" + skillId + "]",
            bean,
            method
        );
    }

    private static MeshRuntime mockRuntime(String agentId, String registryUrl) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        AgentSpec spec = new AgentSpec();
        spec.setAgentId(agentId);
        spec.setRegistryUrl(registryUrl);
        when(runtime.getAgentSpec()).thenReturn(spec);
        return runtime;
    }

    private static ObjectProvider<MeshRuntime> singletonProvider(MeshRuntime runtime) {
        return new ObjectProvider<>() {
            @Override public MeshRuntime getObject() { return runtime; }
            @Override public MeshRuntime getObject(Object... args) { return runtime; }
            @Override public MeshRuntime getIfAvailable() { return runtime; }
            @Override public MeshRuntime getIfUnique() { return runtime; }
        };
    }

    private static MeshRouteRegistry.DependencySpec stubDep(String capability) {
        return new MeshRouteRegistry.DependencySpec(
            capability, new String[0], "", capability);
    }

    /**
     * Test handler bean that captures the injected {@link MeshJobSubmitter}
     * for inspection. Returns "ok" on success, throws when the submitter
     * is null so the dispatcher emits state=failed (a structured signal
     * the test can assert on without resorting to log scraping).
     */
    public static class SubmitterCapturingBean {

        static final AtomicReference<MeshJobSubmitter> LAST_SUBMITTER = new AtomicReference<>();

        public Object handler(Map<String, Object> message, MeshJobSubmitter submitter) {
            LAST_SUBMITTER.set(submitter);
            if (submitter == null) {
                throw new IllegalStateException("submitter was null");
            }
            return "ok";
        }
    }
}
