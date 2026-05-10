package io.mcpmesh.spring.a2a;

import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.spring.A2AConsumerBeanPostProcessor;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.BeanInitializationException;
import org.springframework.core.env.Environment;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.mock.env.MockEnvironment;

import java.lang.reflect.Method;
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

    private static A2AConsumerBeanPostProcessor newProcessor(Environment env) {
        return new A2AConsumerBeanPostProcessor(env);
    }

    private static A2AConsumerBeanPostProcessor newProcessor() {
        return newProcessor(new StandardEnvironment());
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
        BeanInitializationException ex = assertThrows(BeanInitializationException.class,
            () -> proc.postProcessAfterInitialization(new ZeroTimeoutBean(), "zero"));
        assertTrue(ex.getMessage().contains("timeoutSeconds"),
            "must call out invalid timeout, got: " + ex.getMessage());
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
