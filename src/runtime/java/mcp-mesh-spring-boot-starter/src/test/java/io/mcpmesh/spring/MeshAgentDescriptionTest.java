package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.core.AgentSpec;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Issue #969: {@code @MeshAgent(description=...)} must reach the
 * {@link AgentSpec} that the runtime publishes to the registry.
 *
 * <p>Before this change the annotation declared {@code description()} but
 * {@link MeshAutoConfiguration#buildBaseAgentSpec} never read it; the field
 * arrived at the registry as the {@link AgentSpec} default ({@code ""})
 * regardless of what the agent annotation said. This test boots the real
 * {@link MeshAutoConfiguration}, neutralises {@link MeshRuntime#start()} so
 * the native Rust core never loads, and inspects the constructed
 * {@code MeshRuntime}'s {@code AgentSpec} to confirm:
 *
 * <ul>
 *   <li>Annotation {@code description="..."} lands on
 *       {@code spec.getDescription()}.</li>
 *   <li>An unset annotation falls back to the {@code mesh.agent.description}
 *       property — and only when the annotation default ({@code ""}) is in
 *       effect (annotation wins over properties when both are set).</li>
 *   <li>An entirely unset description leaves {@code spec.getDescription()}
 *       as the empty string (never null — Jackson's {@code NON_NULL} filter
 *       would otherwise drop the field from the wire envelope and the
 *       registry would interpret the absence as "leave the prior value
 *       alone" rather than "clear it").</li>
 * </ul>
 *
 * <p>The neutraliser pattern (replacing the started {@link MeshRuntime}
 * post-factory with a no-op) mirrors {@code MeshHelperToolsEagerRegistrationTest}:
 * production wiring runs unmodified, only the Rust-FFI boot is suppressed.
 */
@DisplayName("Issue #969 — @MeshAgent description propagates to AgentSpec")
class MeshAgentDescriptionTest {

    static class MeshRuntimeNeutralizer implements BeanPostProcessor {
        @Override
        public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
            if (bean instanceof MeshRuntime real && !(bean instanceof NoOpRuntime)) {
                return new NoOpRuntime(real.getAgentSpec());
            }
            return bean;
        }
    }

    static class NoOpRuntime extends MeshRuntime {
        NoOpRuntime(AgentSpec spec) {
            super(spec);
        }
        @Override public void start() { /* skip native FFI */ }
        @Override public void stop() { /* no-op */ }
        @Override public boolean isRunning() { return false; }
    }

    @Configuration
    static class CommonTestConfig {
        @Bean
        public MeshRuntimeNeutralizer meshRuntimeNeutralizer() {
            return new MeshRuntimeNeutralizer();
        }
    }

    /**
     * A @MeshAgent-annotated bean is required for {@code findMeshAgentAnnotation}
     * to discover the annotation. The annotation lives on the class itself
     * (not on the bean instance), so a bare @Configuration with the annotation
     * is enough — no @SpringBootApplication needed.
     */
    @Configuration
    @MeshAgent(name = "described-agent", description = "Hello from the mesh")
    static class AnnotatedAgentConfig {
    }

    @Configuration
    @MeshAgent(name = "no-desc-agent")
    static class UnannotatedAgentConfig {
    }

    @Configuration
    @MeshAgent(name = "annotation-wins-agent", description = "annotation-wins")
    static class AnnotationAndPropertyConfig {
    }

    private final WebApplicationContextRunner baseRunner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
        .withUserConfiguration(CommonTestConfig.class);

    @Test
    @DisplayName("Annotation description is copied onto the AgentSpec")
    void annotationDescriptionFlowsToSpec() {
        baseRunner
            .withUserConfiguration(AnnotatedAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                MeshRuntime runtime = context.getBean(MeshRuntime.class);
                assertThat(runtime.getAgentSpec().getDescription())
                    .as("@MeshAgent(description=...) must land on the AgentSpec "
                        + "so the Rust core can forward it to the registry "
                        + "(issue #969)")
                    .isEqualTo("Hello from the mesh");
            });
    }

    @Test
    @DisplayName("Properties description is used when annotation default in effect")
    void propertyDescriptionUsedWhenAnnotationBlank() {
        baseRunner
            .withUserConfiguration(UnannotatedAgentConfig.class)
            .withPropertyValues("mesh.agent.description=from-properties")
            .run(context -> {
                assertThat(context).hasNotFailed();
                MeshRuntime runtime = context.getBean(MeshRuntime.class);
                assertThat(runtime.getAgentSpec().getDescription())
                    .as("When @MeshAgent(description) is the default \"\", "
                        + "fall back to mesh.agent.description")
                    .isEqualTo("from-properties");
            });
    }

    @Test
    @DisplayName("Annotation description wins over properties")
    void annotationDescriptionWinsOverProperty() {
        baseRunner
            .withUserConfiguration(AnnotationAndPropertyConfig.class)
            .withPropertyValues("mesh.agent.description=from-properties")
            .run(context -> {
                assertThat(context).hasNotFailed();
                MeshRuntime runtime = context.getBean(MeshRuntime.class);
                assertThat(runtime.getAgentSpec().getDescription())
                    .as("Annotation should win — properties is only the fallback")
                    .isEqualTo("annotation-wins");
            });
    }

    @Test
    @DisplayName("Description is empty string (not null) when nothing configured")
    void noDescriptionDefaultsToEmptyString() {
        baseRunner
            .withUserConfiguration(UnannotatedAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                MeshRuntime runtime = context.getBean(MeshRuntime.class);
                // Must be non-null so the field reaches the wire (Jackson's
                // NON_NULL filter would otherwise drop it, and the registry
                // would interpret the absence as "keep prior value").
                assertThat(runtime.getAgentSpec().getDescription())
                    .as("Description must default to \"\" — never null")
                    .isEqualTo("");
            });
    }
}
