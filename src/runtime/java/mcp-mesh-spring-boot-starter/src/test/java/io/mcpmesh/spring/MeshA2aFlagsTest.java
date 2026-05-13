package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.web.MeshA2A;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Issue #972: {@code a2a_producer} and {@code a2a_consumer} flags must reach
 * the {@link AgentSpec} that the runtime publishes to the registry.
 *
 * <p>Producer is detected by {@code MeshAutoConfiguration.applyA2ASurfaces}
 * when {@code MeshA2ARegistry.hasSurfaces()} is true (at least one
 * {@code @MeshA2A} surface registered). Consumer is detected by
 * {@code MeshAutoConfiguration.finalizeAgentSpec} from
 * {@code A2AConsumerBeanPostProcessor.bindings()} being non-empty (at least
 * one {@code @A2AConsumer} method).
 *
 * <p>This test mirrors the {@link MeshAgentDescriptionTest} neutraliser
 * pattern — production wiring runs unmodified except the Rust-FFI boot is
 * suppressed by replacing the started {@link MeshRuntime} bean.
 */
@DisplayName("Issue #972 — a2a_producer/a2a_consumer flags propagate to AgentSpec")
class MeshA2aFlagsTest {

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

    // ---- Fixture beans ----

    /**
     * Pure MCP agent — neither producer nor consumer. Used for the
     * "neither" case to confirm both flags stay false by default.
     */
    @Configuration
    @MeshAgent(name = "plain-mcp-agent")
    static class PlainAgentConfig {
    }

    @Component
    static class ProducerSurface {
        @MeshA2A(path = "/agents/x", skillId = "x", skillName = "X")
        public Map<String, Object> handle(Map<String, Object> message) {
            return Map.of("ok", true);
        }
    }

    @Configuration
    @MeshAgent(name = "producer-agent")
    static class ProducerAgentConfig {
        @Bean
        public ProducerSurface producerSurface() {
            return new ProducerSurface();
        }
    }

    @Component
    static class ConsumerBinding {
        @MeshTool(capability = "weather", tags = {"a2a-bridge"})
        @A2AConsumer(url = "http://localhost:9090/agents/weather", skillId = "weather")
        public String weather(A2AClient a2a) {
            return "ok";
        }
    }

    @Configuration
    @MeshAgent(name = "consumer-agent")
    static class ConsumerAgentConfig {
        @Bean
        public ConsumerBinding consumerBinding() {
            return new ConsumerBinding();
        }
    }

    @Configuration
    @MeshAgent(name = "bridge-agent")
    static class BridgeAgentConfig {
        @Bean
        public ProducerSurface producerSurface() {
            return new ProducerSurface();
        }
        @Bean
        public ConsumerBinding consumerBinding() {
            return new ConsumerBinding();
        }
    }

    private final WebApplicationContextRunner baseRunner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
        .withUserConfiguration(CommonTestConfig.class);

    @Test
    @DisplayName("Plain agent: both flags false")
    void plainAgentBothFalse() {
        baseRunner
            .withUserConfiguration(PlainAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                assertThat(spec.isA2aProducer())
                    .as("plain agent — no @MeshA2A surface — producer flag must be false")
                    .isFalse();
                assertThat(spec.isA2aConsumer())
                    .as("plain agent — no @A2AConsumer binding — consumer flag must be false")
                    .isFalse();
            });
    }

    @Test
    @DisplayName("Producer-only agent: a2a_producer=true, a2a_consumer=false")
    void producerOnly() {
        baseRunner
            .withUserConfiguration(ProducerAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                assertThat(spec.isA2aProducer())
                    .as("@MeshA2A surface present — producer flag must be true")
                    .isTrue();
                assertThat(spec.isA2aConsumer())
                    .as("no @A2AConsumer — consumer flag must be false")
                    .isFalse();
            });
    }

    @Test
    @DisplayName("Consumer-only agent: a2a_producer=false, a2a_consumer=true")
    void consumerOnly() {
        baseRunner
            .withUserConfiguration(ConsumerAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                assertThat(spec.isA2aProducer())
                    .as("no @MeshA2A surface — producer flag must be false")
                    .isFalse();
                assertThat(spec.isA2aConsumer())
                    .as("@A2AConsumer binding present — consumer flag must be true")
                    .isTrue();
            });
    }

    @Test
    @DisplayName("Bridge agent: both flags true")
    void bridgeBothTrue() {
        baseRunner
            .withUserConfiguration(BridgeAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                assertThat(spec.isA2aProducer())
                    .as("@MeshA2A present — producer flag must be true")
                    .isTrue();
                assertThat(spec.isA2aConsumer())
                    .as("@A2AConsumer present — consumer flag must be true")
                    .isTrue();
            });
    }
}
