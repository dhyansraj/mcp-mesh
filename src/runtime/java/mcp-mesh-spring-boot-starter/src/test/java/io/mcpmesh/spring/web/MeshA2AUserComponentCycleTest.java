package io.mcpmesh.spring.web;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshAutoConfiguration;
import io.mcpmesh.spring.MeshRuntime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Regression test for issue #937 — broader user-{@code @Component} →
 * {@link MeshRuntime} bean-creation cycle.
 *
 * <p>PR #934 mitigated ONE specific cycle path
 * ({@code meshHealthController} → {@code meshRuntime}) by injecting the
 * runtime via {@link org.springframework.context.annotation.Lazy @Lazy}.
 * The cycle pattern, however, is generic: ANY user {@code @Component} or
 * {@code @Service} bean that autowires {@link MeshRuntime} would hit the
 * same {@code BeanCurrentlyInCreationException} because the
 * {@code meshA2ARouterFunction} and {@code meshRuntime} factories walked
 * {@code @Component}/{@code @Service} beans eagerly during construction —
 * re-entering the very user beans that needed the runtime.
 *
 * <h2>What this test asserts</h2>
 *
 * <p>A plain user {@code @Component} (and a sibling {@code @Service})
 * autowire {@link MeshRuntime} <strong>without {@code @Lazy}</strong>.
 * Loading the context proves the structural fix — if the eager bean walk
 * remained anywhere on the construction path, refresh would fail with
 * {@code BeanCurrentlyInCreationException} and the assertions below
 * would never execute.
 *
 * <h2>Pre-fix vs. post-fix</h2>
 *
 * <ul>
 *   <li><strong>Pre-fix</strong> ({@code MeshAutoConfiguration} walking
 *       {@code getBeansWithAnnotation(@Component.class)} inside the
 *       {@code meshRuntime} factory): refresh fails with
 *       {@code BeanCurrentlyInCreationException}.</li>
 *   <li><strong>Post-fix</strong> (eager walks replaced by a
 *       {@code SmartInitializingSingleton} that runs AFTER all singletons
 *       and BEFORE {@code SmartLifecycle.start()}): refresh completes,
 *       the runtime is injected into the user beans, and the spec is
 *       fully populated by the time the heartbeat loop starts.</li>
 * </ul>
 *
 * <h2>Test-mode caveats</h2>
 *
 * <p>The native Rust core is not exercised here; the test config
 * provides a no-op {@link MeshRuntime} subclass identical in shape to
 * the one used by {@link MeshA2AContextLoadTest}, so the
 * {@code SmartLifecycle} processor does not attempt to bind to a
 * registry during the unit test.
 */
@DisplayName("MeshRuntime — broader user-@Component cycle regression (#937)")
class MeshA2AUserComponentCycleTest {

    /**
     * Plain {@code @Component} autowiring {@link MeshRuntime} <strong>without
     * {@code @Lazy}</strong>. This is the exact failure shape reported in
     * issue #937 — the user-facing reproduction case.
     */
    @Component
    public static class UserComponentWithRuntime {
        private final MeshRuntime runtime;

        @Autowired
        public UserComponentWithRuntime(MeshRuntime runtime) {
            this.runtime = runtime;
        }

        public String agentName() {
            return runtime.getAgentSpec().getName();
        }
    }

    /**
     * {@code @Service} variant — different stereotype, same cycle pattern.
     * Ensures the fix isn't accidentally specific to one stereotype.
     */
    @Service
    public static class UserServiceWithRuntime {
        @Autowired
        private MeshRuntime runtime;

        public String agentId() {
            return runtime.getAgentSpec().getAgentId();
        }
    }

    /**
     * Component that ALSO carries a {@code @MeshA2A} surface AND autowires
     * {@code MeshRuntime}. Covers the precise shape that bit
     * {@code producer-report-agent} during local smoke testing: a real
     * A2A handler bean that needs the runtime for downstream work.
     */
    @Component
    public static class UserA2ABeanWithRuntime {
        private final MeshRuntime runtime;

        @Autowired
        public UserA2ABeanWithRuntime(MeshRuntime runtime) {
            this.runtime = runtime;
        }

        @MeshA2A(path = "/agents/cycle-test", skillId = "cycle-test",
                 skillName = "Cycle Test Skill")
        public Map<String, Object> handle(Map<String, Object> message) {
            return Map.of("agent", runtime.getAgentSpec().getName());
        }
    }

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
     * Carries a {@link MeshAgent} class-level annotation so the
     * production {@link MeshAutoConfiguration#meshRuntime} factory
     * resolves a valid agent name. WITHOUT this, the production
     * factory would fall through to the consumer-only branch and the
     * post-singleton finalizer would reject the spec (no
     * {@code @MeshRoute} dependencies present). Crucially, this
     * approach lets the test exercise the REAL production
     * {@code meshRuntime} factory — which is the only call site that
     * surfaced issue #937's cycle pre-fix. A {@code @Bean}-based stub
     * (the approach used by {@link MeshA2AContextLoadTest}) would
     * bypass the production factory via {@code @ConditionalOnMissingBean}
     * and the regression coverage would be lost.
     */
    @MeshAgent(name = "cycle-test-agent")
    @Configuration
    static class TestConfig {

        /**
         * Intercepts the production {@link MeshRuntime} bean right
         * after construction (BEFORE Spring fires its
         * {@code SmartLifecycle.start()}) and swaps in a
         * {@link NoOpMeshRuntime} carrying the same spec. This
         * preserves the bean-creation cycle path under test (the
         * production factory still ran, with whatever bean walks
         * {@code MeshAutoConfiguration} performed) while preventing
         * the native Rust core from being loaded during the unit
         * test's lifecycle phase.
         *
         * <p>Replacing the bean instance via
         * {@code postProcessAfterInitialization} is safe here because
         * no other bean has captured a reference to the production
         * {@code MeshRuntime} yet — Spring's
         * {@code AbstractAutowireCapableBeanFactory} calls
         * post-processors before exposing the bean to dependents.
         * Beans that later autowire {@code MeshRuntime} (user
         * {@code @Component}s, {@code ToolInvoker}, the post-singleton
         * finalizer) will all receive the {@code NoOpMeshRuntime}.
         */
        @Bean
        static BeanPostProcessor meshRuntimeNoOpAdapter() {
            return new BeanPostProcessor() {
                @Override
                public Object postProcessAfterInitialization(Object bean, String beanName)
                        throws BeansException {
                    if (bean instanceof MeshRuntime runtime
                            && !(bean instanceof NoOpMeshRuntime)) {
                        return new NoOpMeshRuntime(runtime.getAgentSpec());
                    }
                    return bean;
                }
            };
        }
    }

    private final WebApplicationContextRunner runner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
        .withUserConfiguration(TestConfig.class,
            UserComponentWithRuntime.class,
            UserServiceWithRuntime.class,
            UserA2ABeanWithRuntime.class);

    @Test
    @DisplayName("User @Component autowires MeshRuntime without @Lazy — context loads")
    void userComponentAutowiresMeshRuntimeWithoutLazy_boots() {
        runner.run(context -> {
            // Refresh completing is the primary assertion — pre-fix this
            // would have failed with BeanCurrentlyInCreationException
            // from the production buildAgentSpec()'s eager @Component
            // walk re-entering UserComponentWithRuntime mid-creation.
            assertThat(context).hasNotFailed();

            // Defence-in-depth: confirm the user component actually got
            // its runtime injection and can read the spec.
            UserComponentWithRuntime userComponent =
                context.getBean(UserComponentWithRuntime.class);
            assertThat(userComponent.agentName()).isEqualTo("cycle-test-agent");

            // The agent ID is name + 8-char UUID suffix (production
            // buildBaseAgentSpec ran end-to-end). Just sanity-check the
            // prefix — full equality would be flaky across runs.
            UserServiceWithRuntime userService =
                context.getBean(UserServiceWithRuntime.class);
            assertThat(userService.agentId()).startsWith("cycle-test-agent-");
        });
    }

    @Test
    @DisplayName("User @Component with @MeshA2A surface also autowires MeshRuntime without @Lazy")
    void userA2ABeanWithRuntimeAutowireSurface_boots() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            // The producer-report-agent shape: an A2A handler that
            // needs MeshRuntime for downstream work.
            UserA2ABeanWithRuntime a2aBean = context.getBean(UserA2ABeanWithRuntime.class);
            assertThat(a2aBean).isNotNull();

            // The surface must have made it into the registry — proves
            // MeshA2ABeanPostProcessor ran on the user bean even though
            // the eager-walk was removed from the factories.
            MeshA2ARegistry registry = context.getBean(MeshA2ARegistry.class);
            assertThat(registry.hasSurfaces())
                .as("MeshA2ABeanPostProcessor must register the surface "
                    + "from UserA2ABeanWithRuntime")
                .isTrue();
            assertThat(registry.getByPath("/agents/cycle-test"))
                .as("The surface registered by UserA2ABeanWithRuntime "
                    + "must be queryable by path")
                .isNotNull();
        });
    }

    @Test
    @DisplayName("Router function is materialised by the SmartInitializingSingleton after refresh")
    void routerFunctionMaterialisedPostInit() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            // The lazy router function bean is present and resolvable —
            // the post-singleton initializer drove buildRouterFunction()
            // exactly once, populating it with the (then fully-populated)
            // registry.
            assertThat(context).hasBean("meshA2ARouterFunction");
            assertThat(context).hasBean("meshA2ARouterFunctionInitializer");
        });
    }
}
