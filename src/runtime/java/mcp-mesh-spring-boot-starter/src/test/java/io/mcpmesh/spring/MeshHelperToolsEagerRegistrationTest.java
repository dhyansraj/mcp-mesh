package io.mcpmesh.spring;

import io.mcpmesh.core.AgentSpec;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Regression test for the MeshJob helper-tool registration timing bug.
 *
 * <p><b>Background.</b> PR #941 (issue #937 follow-up) moved the
 * {@link JobsHelperToolsRegistrar#register} call out of the synchronous
 * {@code meshRuntime} factory and into a {@link
 * org.springframework.beans.factory.SmartInitializingSingleton}
 * ({@code meshAgentSpecFinalizer}) so the {@code applicationContext.getBeansWithAnnotation(...)}
 * walks would not re-enter user {@code @Component} beans during
 * {@code MeshRuntime} creation.
 *
 * <p><b>Side-effect bug.</b> {@code MeshMcpServerConfiguration#mcpStatelessServer}
 * snapshots the {@link MeshToolWrapperRegistry}'s handlers at bean-construction
 * time (it iterates {@code wrapperRegistry.getAllHandlers()} once and
 * registers each into the MCP SDK's stateless server). Because the
 * {@code mcpStatelessServer} bean is constructed BEFORE any
 * {@code SmartInitializingSingleton} fires, the helper handlers
 * ({@code __mesh_job_status}, {@code __mesh_job_result},
 * {@code __mesh_job_cancel}) — registered from {@code finalizeAgentSpec} —
 * never made it into the snapshot. Every meshctl call to a helper tool
 * therefore failed with the upstream MCP SDK's hardcoded
 * {@code Unknown tool: invalid_tool_name} sentinel.
 *
 * <h2>What this test asserts</h2>
 *
 * <p>The test boots the real {@link MeshAutoConfiguration} (so the production
 * {@code meshRuntime} factory runs unmodified) and uses a
 * {@link BeanPostProcessor} to neutralise {@link MeshRuntime#start()} —
 * preventing the native Rust core from being loaded — without intercepting
 * the factory itself. A "snapshot bean" (constructed during the same
 * singleton phase as {@code mcpStatelessServer}) records the wrapperRegistry's
 * handler-capability set at its own construction time.
 *
 * <ul>
 *   <li><b>Pre-fix</b> (helpers registered from finalizeAgentSpec only):
 *       the snapshot does NOT contain the three helper capabilities — they
 *       are registered later, after every singleton has been instantiated.</li>
 *   <li><b>Post-fix</b> (helpers registered eagerly from the
 *       {@code meshRuntime} factory): the snapshot contains all three
 *       helper capabilities — they are visible to anything that snapshots
 *       wrapperRegistry during the construction phase, including the real
 *       {@code mcpStatelessServer}.</li>
 * </ul>
 *
 * <p>This is a structural test of the registration timing — not the MCP
 * SDK integration itself — so it stays independent of the SDK's snapshot
 * implementation while still surfacing the regression that broke 32 Java
 * integration tests.
 */
@DisplayName("MeshJob helper tools — eager wrapper-registry registration (regression for PR #941)")
class MeshHelperToolsEagerRegistrationTest {

    /**
     * Snapshot bean that records the wrapperRegistry's handler-capability
     * set at its own construction time.
     *
     * <p>To accurately mirror {@code mcpStatelessServer}'s production
     * lifecycle, this bean depends on BOTH {@link MeshToolWrapperRegistry}
     * (the snapshot source) AND {@link MeshRuntime} (a no-op declaring
     * dependency). The {@code MeshRuntime} edge guarantees that this
     * snapshot bean is constructed AFTER the {@code meshRuntime} factory
     * has run — which is the same window where {@code mcpStatelessServer}
     * snapshots in production (the {@code MeshAutoConfiguration} class
     * is processed before {@code MeshMcpServerConfiguration} per the
     * {@code AutoConfiguration.imports} ordering).
     *
     * <p>The bean is constructed BEFORE any
     * {@link org.springframework.beans.factory.SmartInitializingSingleton}
     * fires — that's the singleton-instantiation-phase invariant Spring
     * guarantees, and it's the same invariant the production
     * {@code mcpStatelessServer} relies on.
     */
    static class WrapperRegistrySnapshot {
        final Set<String> capabilitiesAtConstruction;

        WrapperRegistrySnapshot(MeshToolWrapperRegistry wrapperRegistry, MeshRuntime runtime) {
            // Snapshot at construction — the production mcpStatelessServer
            // takes its tool list at the same moment. The unused `runtime`
            // parameter declares an ordering edge so this bean is constructed
            // after the meshRuntime factory has run (whose body performs the
            // eager helper-tool registration this test validates).
            this.capabilitiesAtConstruction = Set.copyOf(
                wrapperRegistry.getHandlersByCapability().keySet());
        }
    }

    /**
     * Replaces the real {@link MeshRuntime} bean with a no-op subclass
     * AFTER the production {@code meshRuntime} factory has run — so all
     * the eager registration logic in the factory body executes against
     * the real {@link MeshToolRegistry} / {@link MeshToolWrapperRegistry}
     * beans, but {@link MeshRuntime#start} never loads the native FFI.
     *
     * <p>Using a {@link BeanPostProcessor} here (rather than a stub
     * {@code @Bean MeshRuntime} that satisfies {@code @ConditionalOnMissingBean})
     * is critical for the test's value: a stub would replace the
     * production factory and silently mask a regression where someone
     * removes the eager registration call.
     */
    static class MeshRuntimeNeutralizer implements BeanPostProcessor {
        @Override
        public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
            if (bean instanceof MeshRuntime real && !(bean instanceof NoOpRuntime)) {
                // Replace with a NoOp subclass that shares the same agent
                // spec — so spec mutations made by the SmartInitializingSingleton
                // (e.g. agent_type=a2a, tool list) still land on the same
                // object the rest of the context has a reference to.
                return new NoOpRuntime(real.getAgentSpec());
            }
            return bean;
        }
    }

    /**
     * No-op runtime stub so the {@code SmartLifecycle} container doesn't
     * try to spin up the native Rust core in a unit test.
     */
    static class NoOpRuntime extends MeshRuntime {
        private volatile boolean running;

        NoOpRuntime(AgentSpec spec) {
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

    @Configuration
    static class TestConfig {

        @Bean
        public WrapperRegistrySnapshot wrapperRegistrySnapshot(
                MeshToolWrapperRegistry wrapperRegistry,
                MeshRuntime runtime) {
            return new WrapperRegistrySnapshot(wrapperRegistry, runtime);
        }

        @Bean
        public MeshRuntimeNeutralizer meshRuntimeNeutralizer() {
            return new MeshRuntimeNeutralizer();
        }
    }

    private final WebApplicationContextRunner runner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
        .withUserConfiguration(TestConfig.class)
        // Required: finalizeAgentSpec rejects an empty agent name (consumer-only
        // mode without any @MeshRoute deps). We don't care about the value —
        // only that the spec is well-formed enough for the context to refresh.
        .withPropertyValues("mesh.agent.name=test-helper-eager-registration");

    @Test
    @DisplayName("Helper handlers are visible to wrapperRegistry consumers " +
        "constructed before SmartInitializingSingleton fires")
    void helperHandlersAreEagerlyRegistered() {
        AtomicReference<Set<String>> snapshotRef = new AtomicReference<>();

        runner.run(context -> {
            assertThat(context).hasNotFailed();
            WrapperRegistrySnapshot snapshot = context.getBean(WrapperRegistrySnapshot.class);
            snapshotRef.set(snapshot.capabilitiesAtConstruction);

            // The snapshot was taken at WrapperRegistrySnapshot construction —
            // i.e. during the singleton-instantiation phase, BEFORE any
            // SmartInitializingSingleton (including meshAgentSpecFinalizer)
            // fires. The three helper-tool handlers must already be registered
            // at that moment so mcpStatelessServer's identical snapshot
            // includes them.
            assertThat(snapshot.capabilitiesAtConstruction)
                .as("Helper handler __mesh_job_status must be registered "
                    + "BEFORE SmartInitializingSingleton fires (otherwise "
                    + "mcpStatelessServer's snapshot won't include it)")
                .contains(JobsHelperToolHandler.TOOL_NAME_STATUS);
            assertThat(snapshot.capabilitiesAtConstruction)
                .as("Helper handler __mesh_job_result must be registered "
                    + "BEFORE SmartInitializingSingleton fires")
                .contains(JobsHelperToolHandler.TOOL_NAME_RESULT);
            assertThat(snapshot.capabilitiesAtConstruction)
                .as("Helper handler __mesh_job_cancel must be registered "
                    + "BEFORE SmartInitializingSingleton fires")
                .contains(JobsHelperToolHandler.TOOL_NAME_CANCEL);
        });
    }

    @Test
    @DisplayName("Helper synthetic tool specs are present in toolRegistry post-context-init")
    void helperToolSpecsAreInToolRegistry() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            MeshToolRegistry toolRegistry = context.getBean(MeshToolRegistry.class);

            // The three synthetic ToolSpecs must be present in the heartbeat
            // catalog so the registry knows the agent advertises them.
            assertThat(toolRegistry.getToolSpecs())
                .as("toolRegistry must contain three synthetic helper specs")
                .extracting(AgentSpec.ToolSpec::getCapability)
                .contains(
                    JobsHelperToolHandler.TOOL_NAME_STATUS,
                    JobsHelperToolHandler.TOOL_NAME_RESULT,
                    JobsHelperToolHandler.TOOL_NAME_CANCEL);
        });
    }
}
