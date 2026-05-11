package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshAutoConfiguration;
import io.mcpmesh.spring.MeshRuntime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.function.RouterFunction;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Regression test for the {@code meshA2ARouterFunction} bean-creation cycle
 * (issue #932 Phase 1A/1B follow-up).
 *
 * <p>The original auto-configuration wired
 * {@link io.mcpmesh.spring.MeshHealthController} via
 * {@code ObjectProvider<MeshRuntime>}; the factory called
 * {@code getIfAvailable()} at construction, which triggered
 * {@link MeshRuntime} creation. Combined with the eager-touch
 * ({@code applicationContext.getBeansWithAnnotation(Component.class)})
 * performed by both {@code meshA2ARouterFunction} AND by
 * {@code MeshRuntime#buildAgentSpec}, this produced a bean-creation cycle:
 *
 * <pre>
 *   routerFunctionMapping
 *     -> meshA2ARouterFunction
 *       -> meshHealthController        (touched by eager getBeansWithAnnotation(@Component))
 *         -> meshRuntime               (resolved via ObjectProvider.getIfAvailable)
 *           -> meshHealthController    (re-touched by buildAgentSpec's eager scan; CYCLE)
 * </pre>
 *
 * <p>Spring Boot 2.6+ rejects circular references by default; the application
 * fails at context-refresh with a {@code BeanCurrentlyInCreationException}.
 *
 * <h2>The fix</h2>
 *
 * <p>The fix annotates the {@code MeshRuntime} parameter of
 * {@code meshHealthController} with
 * {@link org.springframework.context.annotation.Lazy @Lazy}. Spring then
 * injects a CGLIB proxy that defers actual runtime resolution to the first
 * method call (which happens at request time, not at construction time).
 * The {@code meshHealthController -> meshRuntime} edge of the dependency
 * graph is removed AT CONSTRUCTION, breaking the cycle structurally —
 * regardless of which eager-touch runs first.
 *
 * <h2>How this test reproduces the cycle</h2>
 *
 * <p>The test wires the real {@link MeshAutoConfiguration} via
 * {@link WebApplicationContextRunner}. To avoid hitting the native Rust
 * core (which would otherwise try to register with a real registry during
 * {@code MeshRuntime.start()}), the test config provides a no-op
 * {@code MeshRuntime} subclass. Critically, the test factory <strong>also
 * walks {@code @Component} beans during construction</strong>, mirroring
 * the eager-touch that {@code buildAgentSpec()} performs in production.
 * Without that mirror, the test factory would be too lightweight to
 * surface the cycle.
 *
 * <p><strong>Pre-fix expectation:</strong> {@code meshHealthController}
 * factory eagerly resolves {@code MeshRuntime} via
 * {@code ObjectProvider.getIfAvailable()} — meanwhile the test's eager
 * {@code @Component} scan re-enters {@code meshHealthController} → cycle.
 *
 * <p><strong>Post-fix expectation:</strong> {@code meshHealthController}
 * receives a {@code @Lazy} runtime proxy — no eager resolution, no cycle.
 * Context refreshes cleanly.
 */
@DisplayName("MeshA2A producer — context-load regression (no bean cycle)")
class MeshA2AContextLoadTest {

    /**
     * Test fixture bean carrying a {@code @MeshA2A} surface so the producer
     * autoconfig has at least one registered handler. Mirrors the shape of
     * the producer-date-agent that originally surfaced the cycle.
     */
    @Component
    public static class TestA2ABean {
        @MeshA2A(path = "/agents/test", skillId = "test-skill", skillName = "Test Skill")
        public Map<String, Object> handle(Map<String, Object> message) {
            return Map.of("ok", true);
        }
    }

    /**
     * Test-only {@link MeshRuntime} subclass — overrides {@link #start()},
     * {@link #stop()}, and {@link #isRunning()} so the Spring
     * {@code SmartLifecycle} processor does not try to spin up the native
     * Rust core during a unit test. All other methods inherit production
     * behaviour.
     */
    static class NoOpMeshRuntime extends MeshRuntime {
        private volatile boolean running;

        NoOpMeshRuntime(AgentSpec spec) {
            super(spec);
        }

        @Override
        public void start() {
            running = true;
        }

        @Override
        public void stop() {
            running = false;
        }

        @Override
        public boolean isRunning() {
            return running;
        }
    }

    /**
     * Test config that provides a {@code MeshRuntime} stub satisfying the
     * starter's {@code @ConditionalOnMissingBean} so the real factory (which
     * loads the native lib) is skipped. The factory body intentionally walks
     * {@code @Component} beans — the same eager-touch the production
     * {@code buildAgentSpec()} performs — so the cycle structure being
     * tested is preserved end-to-end.
     */
    @Configuration
    static class TestConfig {

        @Bean
        public MeshRuntime meshRuntime(ApplicationContext applicationContext) {
            // Mirror the eager-touch from MeshAutoConfiguration.buildAgentSpec().
            // This is what re-enters MeshHealthController in the production
            // cycle; keeping it here lets the regression test fail with the
            // same BeanCurrentlyInCreationException pre-fix.
            applicationContext.getBeansWithAnnotation(Component.class);
            applicationContext.getBeansWithAnnotation(
                org.springframework.stereotype.Service.class);

            AgentSpec spec = new AgentSpec();
            spec.setName("test-agent");
            spec.setAgentId("test-agent-00000000");
            return new NoOpMeshRuntime(spec);
        }
    }

    private final WebApplicationContextRunner runner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
        .withUserConfiguration(TestConfig.class, TestA2ABean.class);

    @Test
    @DisplayName("Context refreshes cleanly with @MeshA2A producer wiring (no bean cycle)")
    void contextLoadsWithoutCircularReference() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).isNotNull();
        });
    }

    @Test
    @DisplayName("All A2A producer beans are wired and resolvable")
    void allA2ABeansArePresent() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            // Core A2A producer beans.
            assertThat(context).hasBean("meshA2ARegistry");
            assertThat(context).hasBean("meshA2ADispatcher");
            assertThat(context).hasBean("meshA2ASseDispatcher");
            assertThat(context).hasBean("meshA2ADispatcherController");
            assertThat(context).hasBean("meshA2ARouterFunction");
            assertThat(context).hasBean("meshA2AAuthFilter");
            // Health controller is part of the cycle path — assert it's
            // present and resolvable post-fix.
            assertThat(context).hasBean("meshHealthController");
            // MeshA2A surface from TestA2ABean must have been registered by
            // the bean post-processor, proving the eager-touch path still
            // runs end-to-end post-fix.
            MeshA2ARegistry registry = context.getBean(MeshA2ARegistry.class);
            assertThat(registry.hasSurfaces())
                .as("MeshA2ABeanPostProcessor must have populated the registry "
                    + "with TestA2ABean.handle()")
                .isTrue();
        });
    }

    @Test
    @DisplayName("Router function bean is the typed RouterFunction<ServerResponse>")
    void routerFunctionIsTypedCorrectly() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            RouterFunction<?> router = context.getBean(
                "meshA2ARouterFunction", RouterFunction.class);
            assertThat(router).isNotNull();
            // Sanity: the router was produced by buildRouterFunction(), so it
            // composes (per surface) three sub-routes. We can't introspect
            // the route table without spinning up MockMvc, but checking the
            // bean is reachable confirms the factory ran without cycling.
            assertThat(context.getBeansOfType(RouterFunction.class))
                .as("Expected at least the meshA2ARouterFunction to be in the context")
                .isNotEmpty();
        });
    }

    @Test
    @DisplayName("Context is autowireable post-refresh (no cycle, no startup failure)")
    void contextIsAutowireable() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            // AssertableApplicationContext is itself an ApplicationContext —
            // mirrors the spec's "Autowire ApplicationContext, assert non-null".
            ApplicationContext ctx = context.getSourceApplicationContext();
            assertThat(ctx).isNotNull();
        });
    }
}
