package io.mcpmesh.spring.a2a;

import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.spring.A2AConsumerBeanPostProcessor;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.BeanInitializationException;
import org.springframework.core.env.Environment;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.mock.env.MockEnvironment;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #923: unit tests for {@link A2AConsumerBeanPostProcessor}.
 *
 * <p>Covers the boot-time validation, A2AClient caching, Spring
 * property placeholder resolution, and the migration error fired when
 * a method still uses the marker-only form.
 */
class A2AConsumerBeanPostProcessorTest {

    // -------- Stub beans --------

    public static class GoodBean {
        @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
        @A2AConsumer(url = "http://localhost:9090/agents/date", skillId = "get-date")
        public String currentDate(A2AClient a2a) {
            return "ok";
        }
    }

    public static class MarkerOnlyBean {
        // Pre-#923 marker-only usage with no url() — must be rejected at boot.
        @MeshTool(capability = "broken")
        @A2AConsumer(url = "")
        public String broken(A2AClient a2a) {
            return "x";
        }
    }

    public static class BothAuthBean {
        @MeshTool(capability = "broken-auth")
        @A2AConsumer(url = "http://x", authBearerEnv = "FOO", authBearerToken = "bar")
        public String brokenAuth(A2AClient a2a) {
            return "x";
        }
    }

    public static class ZeroTimeoutBean {
        @MeshTool(capability = "broken-timeout")
        @A2AConsumer(url = "http://x", timeoutSeconds = 0)
        public String brokenTimeout(A2AClient a2a) {
            return "x";
        }
    }

    public static class NegativeTimeoutBean {
        @MeshTool(capability = "neg-timeout")
        @A2AConsumer(url = "http://x", timeoutSeconds = -1)
        public String negTimeout(A2AClient a2a) {
            return "x";
        }
    }

    public static class NoMeshToolBean {
        // @A2AConsumer without @MeshTool — must be a no-op (skipped by
        // the post-processor) so we don't construct an A2AClient that
        // no dispatch path will ever consult.
        @A2AConsumer(url = "http://x", skillId = "skill")
        public String orphan(A2AClient a2a) {
            return "x";
        }
    }

    public static class MissingClientParamBean {
        @MeshTool(capability = "missing")
        @A2AConsumer(url = "http://x")
        public String missing() {
            return "x";
        }
    }

    public static class TwoClientParamsBean {
        @MeshTool(capability = "two")
        @A2AConsumer(url = "http://x")
        public String two(A2AClient a, A2AClient b) {
            return "x";
        }
    }

    public static class PlaceholderBean {
        @MeshTool(capability = "placeholder")
        @A2AConsumer(url = "${weather.a2a.url}", skillId = "get-weather")
        public String weather(A2AClient a2a) {
            return "ok";
        }
    }

    public static class TwoMethodsSameConfigBean {
        @MeshTool(capability = "first")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill")
        public String first(A2AClient a2a) {
            return "1";
        }

        @MeshTool(capability = "second")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill")
        public String second(A2AClient a2a) {
            return "2";
        }
    }

    public static class TwoMethodsDifferentConfigBean {
        @MeshTool(capability = "first")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill")
        public String first(A2AClient a2a) {
            return "1";
        }

        @MeshTool(capability = "second")
        @A2AConsumer(url = "http://x/agents/z", skillId = "skill")
        public String second(A2AClient a2a) {
            return "2";
        }
    }

    public static class CapabilityFallbackSkillBean {
        @MeshTool(capability = "current-date")
        @A2AConsumer(url = "http://x/agents/y")     // skillId left unset
        public String currentDate(A2AClient a2a) {
            return "ok";
        }
    }

    public static class ResolvedToBlankUrlBean {
        // Spring property defaulted to empty string — placeholder
        // resolves successfully but yields blank url. Distinct error
        // message from the marker-only migration path.
        @MeshTool(capability = "blank-url")
        @A2AConsumer(url = "${some.url:}", skillId = "x")
        public String blank(A2AClient a2a) {
            return "x";
        }
    }

    public static class AuthlessBean {
        @MeshTool(capability = "auth-none")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill")
        public String none(A2AClient a2a) {
            return "x";
        }
    }

    public static class AuthEnvBean {
        @MeshTool(capability = "auth-env")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill", authBearerEnv = "MY_TOKEN")
        public String env(A2AClient a2a) {
            return "x";
        }
    }

    public static class AuthLiteralBean {
        @MeshTool(capability = "auth-literal")
        @A2AConsumer(url = "http://x/agents/y", skillId = "skill", authBearerToken = "literal")
        public String literal(A2AClient a2a) {
            return "x";
        }
    }

    // Track every processor produced via newProcessor() so the
    // @AfterEach cleanup hook can shutdown() each one. Each A2AClient
    // owns a JDK HttpClient + selector thread pool; without explicit
    // shutdown the pools accumulate across tests and risk an FD leak
    // on long suites (CodeRabbit Fix 6).
    private final List<A2AConsumerBeanPostProcessor> processors = new ArrayList<>();

    private A2AConsumerBeanPostProcessor newProcessor(Environment env) {
        A2AConsumerBeanPostProcessor proc = new A2AConsumerBeanPostProcessor(env);
        processors.add(proc);
        return proc;
    }

    private A2AConsumerBeanPostProcessor newProcessor() {
        return newProcessor(new StandardEnvironment());
    }

    @AfterEach
    void cleanupProcessors() {
        for (A2AConsumerBeanPostProcessor proc : processors) {
            try {
                proc.shutdown();
            } catch (Exception ignored) {
                // best-effort cleanup
            }
        }
        processors.clear();
    }

    // -------- Validation --------

    @Test
    void boot_failsWithMigrationMessage_whenUrlMissing() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new MarkerOnlyBean(), "marker"));
        // Migration message must spell out the issue link + example syntax
        // so users who upgraded mid-PR get a real fix path, not a stack trace.
        assertTrue(ex.getMessage().contains("requires the 'url' field"),
            "must mention the missing url field, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("#923"),
            "must reference the migration issue, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("@A2AConsumer(url"),
            "must show the new annotation syntax, got: " + ex.getMessage());
    }

    @Test
    void boot_failsWhenBothAuthFieldsSet() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new BothAuthBean(), "both"));
        assertTrue(ex.getMessage().contains("mutually exclusive"),
            "must call out auth field conflict, got: " + ex.getMessage());
    }

    @Test
    void boot_failsWhenTimeoutZeroOrNegative() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        BeanInitializationException ex1 = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new ZeroTimeoutBean(), "zero"));
        assertTrue(ex1.getMessage().contains("timeoutSeconds"),
            "must call out invalid timeout for zero, got: " + ex1.getMessage());

        // Negative timeouts take the same code path as zero (timeoutSeconds <= 0)
        // but cover them explicitly so a future split of the validation
        // doesn't silently drop one branch.
        BeanInitializationException ex2 = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new NegativeTimeoutBean(), "negative"));
        assertTrue(ex2.getMessage().contains("timeoutSeconds"),
            "must call out invalid timeout for negative, got: " + ex2.getMessage());
    }

    @Test
    void boot_failsWhenA2AClientParamMissing() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new MissingClientParamBean(), "missing"));
        assertTrue(ex.getMessage().contains("A2AClient parameter"),
            "must call out the missing injection slot, got: " + ex.getMessage());
    }

    @Test
    void boot_failsWhenTwoA2AClientParamsDeclared() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new TwoClientParamsBean(), "two"));
        assertTrue(ex.getMessage().contains("more than one A2AClient"),
            "must reject the multi-slot signature, got: " + ex.getMessage());
    }

    @Test
    void boot_skipsMethodWithoutMeshTool() {
        // CodeRabbit Fix 2: an @A2AConsumer that is NOT paired with
        // @MeshTool has nothing to bridge — the post-processor must
        // skip it cleanly rather than construct an A2AClient that no
        // dispatch path will ever consult.
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new NoMeshToolBean(), "orphan");
        assertEquals(0, proc.cacheSize(),
            "no-MeshTool method must NOT trigger A2AClient construction");
        assertEquals(0, proc.bindings().size(),
            "no-MeshTool method must NOT record a MethodBinding");
    }

    // -------- Wiring --------

    @Test
    void boot_wiresGoodBean_andRecordsBinding() throws Exception {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new GoodBean(), "good");

        Method m = GoodBean.class.getMethod("currentDate", A2AClient.class);
        A2AConsumerBeanPostProcessor.MethodBinding binding = proc.bindingFor(m);
        assertNotNull(binding, "binding must be present after post-processing");
        assertEquals(0, binding.a2aParamIndex(),
            "A2AClient is the sole param at position 0");
        assertNotNull(binding.client(), "cached A2AClient must be non-null");
        assertEquals("http://localhost:9090/agents/date", binding.key().url());
        assertEquals("get-date", binding.key().skillId());
        assertEquals(30, binding.key().timeoutSeconds(),
            "default timeout (30s) must round-trip into the key");
    }

    @Test
    void boot_resolvesSpringPropertyPlaceholderInUrl() throws Exception {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("weather.a2a.url", "http://upstream:9999/agents/weather");
        A2AConsumerBeanPostProcessor proc = newProcessor(env);
        proc.postProcessAfterInitialization(new PlaceholderBean(), "ph");

        Method m = PlaceholderBean.class.getMethod("weather", A2AClient.class);
        A2AConsumerBeanPostProcessor.MethodBinding binding = proc.bindingFor(m);
        assertNotNull(binding);
        assertEquals("http://upstream:9999/agents/weather", binding.key().url(),
            "placeholder must be resolved against the Spring Environment");
    }

    @Test
    void boot_failsWhenUrlPlaceholderUnresolved() {
        // No property set — resolveRequiredPlaceholders should raise.
        A2AConsumerBeanPostProcessor proc = newProcessor(new MockEnvironment());
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new PlaceholderBean(), "ph"));
        assertTrue(ex.getMessage().contains("placeholder"),
            "must call out the unresolved placeholder, got: " + ex.getMessage());
    }

    @Test
    void boot_skillIdDefaultsToCapability_whenAnnotationSkillIdBlank() throws Exception {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new CapabilityFallbackSkillBean(), "fallback");

        Method m = CapabilityFallbackSkillBean.class.getMethod("currentDate", A2AClient.class);
        A2AConsumerBeanPostProcessor.MethodBinding binding = proc.bindingFor(m);
        assertNotNull(binding);
        assertEquals("current-date", binding.key().skillId(),
            "blank skillId must fall back to the @MeshTool capability (Python parity)");
    }

    // Note: a "blank skillId AND blank @MeshTool capability" scenario was
    // previously asserted via a no-@MeshTool stub bean. With CodeRabbit
    // Fix 2 the post-processor now early-returns for any @A2AConsumer
    // without @MeshTool, so that scenario is no longer reachable from
    // user code (@MeshTool.capability() has no default, so a present
    // @MeshTool always carries a non-blank capability). The defensive
    // validation in processConsumerMethod remains as belt-and-suspenders.

    @Test
    void boot_failsWhenUrlPlaceholderResolvesToBlank() {
        // Fix 3: a placeholder like ${some.url:} that resolves to empty
        // must surface a property-pointing message, NOT the marker-only
        // migration message (which would mislead the user — they did
        // set a url, the property is just empty).
        MockEnvironment env = new MockEnvironment();
        // Don't set any property — ${some.url:} default is "".
        A2AConsumerBeanPostProcessor proc = newProcessor(env);
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new ResolvedToBlankUrlBean(), "blank"));
        assertTrue(ex.getMessage().contains("resolved to empty"),
            "must call out the blank resolution, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("Spring property"),
            "must point at the property, not the migration link, got: " + ex.getMessage());
        assertFalse(ex.getMessage().contains("#923"),
            "must NOT show the marker-only migration message — the user did set a url, "
                + "got: " + ex.getMessage());
    }

    // -------- Caching --------

    @Test
    void cache_sharesA2AClientAcrossMethodsWithIdenticalConfig() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new TwoMethodsSameConfigBean(), "same");

        assertEquals(1, proc.cacheSize(),
            "two methods with identical config must share a single cached A2AClient");
        assertEquals(2, proc.bindings().size(),
            "but each method gets its own MethodBinding entry");

        // Both bindings reference the SAME A2AClient instance.
        Map<java.lang.reflect.Method, A2AConsumerBeanPostProcessor.MethodBinding> bindings = proc.bindings();
        A2AClient[] clients = bindings.values().stream()
            .map(A2AConsumerBeanPostProcessor.MethodBinding::client)
            .toArray(A2AClient[]::new);
        assertSame(clients[0], clients[1], "shared config must yield shared A2AClient instance");
    }

    @Test
    void cache_separatesA2AClientsByDifferentConfig() {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new TwoMethodsDifferentConfigBean(), "diff");

        assertEquals(2, proc.cacheSize(),
            "two methods with different urls must construct two A2AClient instances");
    }

    @Test
    void cache_separatesA2AClientsByAuthSpec_evenWithIdenticalUrlAndSkill() throws Exception {
        // Fix 5: two methods with identical (url, skillId, timeout) but
        // DIFFERENT auth specs (none vs env vs literal) must produce
        // distinct cached A2AClient instances. Closes the cache-key
        // correctness gap where credentials with different rotation
        // surfaces would otherwise collide.
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new AuthlessBean(), "none");
        proc.postProcessAfterInitialization(new AuthEnvBean(), "env");
        proc.postProcessAfterInitialization(new AuthLiteralBean(), "literal");

        assertEquals(3, proc.cacheSize(),
            "auth=none, auth=env, auth=literal must each get their own cached A2AClient — "
                + "AuthSpec is part of the cache key");
        assertEquals(3, proc.bindings().size(),
            "each method must record its own binding");

        // Pull the three clients and verify pairwise distinctness.
        Method noneM = AuthlessBean.class.getMethod("none", A2AClient.class);
        Method envM = AuthEnvBean.class.getMethod("env", A2AClient.class);
        Method literalM = AuthLiteralBean.class.getMethod("literal", A2AClient.class);
        A2AClient noneClient = proc.bindingFor(noneM).client();
        A2AClient envClient = proc.bindingFor(envM).client();
        A2AClient literalClient = proc.bindingFor(literalM).client();
        assertNotSame(noneClient, envClient,
            "auth=none and auth=env must NOT share a cached client");
        assertNotSame(noneClient, literalClient,
            "auth=none and auth=literal must NOT share a cached client");
        assertNotSame(envClient, literalClient,
            "auth=env and auth=literal must NOT share a cached client");
    }

    // -------- Lifecycle --------

    @Test
    void shutdown_clearsCacheAndBindings() throws Exception {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new GoodBean(), "good");
        assertEquals(1, proc.cacheSize());
        assertEquals(1, proc.bindings().size());

        proc.shutdown();
        assertEquals(0, proc.cacheSize(),
            "shutdown must drop cached A2AClient instances so the context can be GC'd");
        assertEquals(0, proc.bindings().size());
    }

    @Test
    void shutdown_closesEachCachedA2AClient() throws Exception {
        // CodeRabbit Fix 5: clearing the cache map is necessary but not
        // sufficient — each cached A2AClient holds an HttpClient with
        // its own selector + worker pool, and AutoCloseable.close() is
        // the public lifecycle signal. Verify shutdown() actually flips
        // the `closed` flag on every cached instance, not just drops
        // them on the floor for the GC to (eventually) reach.
        //
        // A2AClient is `final`, so subclassing is impossible; we read
        // the production `closed` field via reflection — which has the
        // upside that this test covers the real production close path,
        // not a test-double surrogate.
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new TwoMethodsDifferentConfigBean(), "diff");
        assertEquals(2, proc.cacheSize(),
            "two distinct configs should populate two cache entries before shutdown");

        // Snapshot the cached clients before shutdown drops the map.
        Method m1 = TwoMethodsDifferentConfigBean.class.getMethod("first", A2AClient.class);
        Method m2 = TwoMethodsDifferentConfigBean.class.getMethod("second", A2AClient.class);
        A2AClient client1 = proc.bindingFor(m1).client();
        A2AClient client2 = proc.bindingFor(m2).client();
        assertNotSame(client1, client2,
            "two different urls must yield two distinct cached clients");
        assertFalse(readClosedFlag(client1), "client1 must start un-closed");
        assertFalse(readClosedFlag(client2), "client2 must start un-closed");

        proc.shutdown();

        assertTrue(readClosedFlag(client1),
            "shutdown() must call close() on every cached A2AClient — client1 leaked");
        assertTrue(readClosedFlag(client2),
            "shutdown() must call close() on every cached A2AClient — client2 leaked");
    }

    /**
     * Read the package-private {@code closed} flag on an {@link A2AClient}
     * via reflection. The field is set by {@link A2AClient#close()}; reading
     * it lets us verify the close path ran without subclassing the final
     * class. Used by {@link #shutdown_closesEachCachedA2AClient()}.
     */
    private static boolean readClosedFlag(A2AClient client) throws Exception {
        Field f = A2AClient.class.getDeclaredField("closed");
        f.setAccessible(true);
        return f.getBoolean(client);
    }

    // -------- Task=true wiring (uc27 tc04 regression cover) --------

    /**
     * Mirror of the {@code consumer-report-agent-java} fixture's signature:
     * {@code (@Param, @Param, A2AClient, MeshJob)} with {@code task=true}.
     * Catches the regression seen in uc27 tc04 where the wrapper-side
     * dispatch could not find the cached A2AClient on the task path.
     */
    public static class TaskBean {
        @MeshTool(capability = "report", task = true, tags = {"a2a-bridge"})
        @A2AConsumer(url = "http://localhost:9091/agents/report", skillId = "generate-report")
        public Object generateReport(
                @io.mcpmesh.Param("user_id") String userId,
                @io.mcpmesh.Param(value = "sections", required = false) java.util.List<String> sections,
                A2AClient a2a,
                io.mcpmesh.MeshJob job) {
            return java.util.Map.of();
        }
    }

    @Test
    void taskBean_bindingResolvesAtCorrectSlotIndex() throws Exception {
        A2AConsumerBeanPostProcessor proc = newProcessor();
        proc.postProcessAfterInitialization(new TaskBean(), "task");

        Method m = TaskBean.class.getMethod("generateReport",
            String.class, java.util.List.class, A2AClient.class, io.mcpmesh.MeshJob.class);
        A2AConsumerBeanPostProcessor.MethodBinding binding = proc.bindingFor(m);
        assertNotNull(binding,
            "task=true @A2AConsumer methods must be wired exactly like non-task ones");
        assertEquals(2, binding.a2aParamIndex(),
            "A2AClient sits at signature position 2 (after the two @Param slots)");
    }

    @Test
    void taskBean_methodLookupRoundTripsThroughReflectionUtils() throws Exception {
        // Defensive cover for the failure mode where two BPPs see two
        // different Method instances for "the same" method (would be a
        // bug in a custom Map<Method,?> impl). With ReflectionUtils +
        // ConcurrentHashMap (the production wiring) Method.equals is
        // class+name+params, so .get returns the recorded binding.
        A2AConsumerBeanPostProcessor proc = newProcessor();
        TaskBean bean = new TaskBean();
        proc.postProcessAfterInitialization(bean, "task");

        // Walk methods the same way MeshToolBeanPostProcessor does and
        // confirm the binding is found.
        Class<?> targetClass = bean.getClass();
        java.util.concurrent.atomic.AtomicReference<A2AConsumerBeanPostProcessor.MethodBinding> seen =
            new java.util.concurrent.atomic.AtomicReference<>();
        org.springframework.util.ReflectionUtils.doWithMethods(targetClass, method -> {
            if ("generateReport".equals(method.getName())) {
                seen.set(proc.bindingFor(method));
            }
        });
        assertNotNull(seen.get(),
            "binding lookup via ReflectionUtils.doWithMethods (the path the tool BPP uses) must "
                + "return a non-null binding for the same method that A2A BPP recorded");
    }
}
