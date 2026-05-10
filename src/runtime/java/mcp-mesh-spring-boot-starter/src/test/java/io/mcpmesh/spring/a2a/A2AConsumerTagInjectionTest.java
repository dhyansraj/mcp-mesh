package io.mcpmesh.spring.a2a;

import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshToolRegistry;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #916 Phase 1: verify that
 * {@link MeshToolRegistry#injectConsumerNameTags} appends the
 * surrounding {@code @MeshAgent} name to every {@code @A2AConsumer}
 * tool's tag list (and to those tools only), is idempotent across
 * repeated invocations, and skips cleanly when the agent name is
 * blank or the tool is missing the marker annotation.
 */
class A2AConsumerTagInjectionTest {

    /** Stub bean exposing one consumer-marked + one plain mesh tool. */
    public static class ConsumerBean {

        @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
        @A2AConsumer(url = "http://localhost:9090/agents/date", skillId = "get-date")
        public String currentDate() {
            return "today";
        }

        @MeshTool(capability = "plain-tool", tags = {"plain"})
        public String plainTool() {
            return "ok";
        }
    }

    @Test
    void injectConsumerNameTags_appendsAgentNameToConsumerToolOnly() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        ConsumerBean bean = new ConsumerBean();
        registry.registerTool(
            bean,
            ConsumerBean.class.getMethod("currentDate"),
            ConsumerBean.class.getMethod("currentDate").getAnnotation(MeshTool.class));
        registry.registerTool(
            bean,
            ConsumerBean.class.getMethod("plainTool"),
            ConsumerBean.class.getMethod("plainTool").getAnnotation(MeshTool.class));

        registry.injectConsumerNameTags("date-consumer");

        MeshToolRegistry.ToolMetadata consumerMeta = registry.getTool("current-date");
        assertNotNull(consumerMeta);
        assertTrue(consumerMeta.tags().contains("a2a-bridge"),
            "user-supplied tag should still be present");
        assertTrue(consumerMeta.tags().contains("date-consumer"),
            "consumer-name auto-tag should be injected");

        MeshToolRegistry.ToolMetadata plainMeta = registry.getTool("plain-tool");
        assertNotNull(plainMeta);
        assertFalse(plainMeta.tags().contains("date-consumer"),
            "plain @MeshTool without @A2AConsumer must NOT receive the auto-tag");
    }

    @Test
    void injectConsumerNameTags_isIdempotent() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        ConsumerBean bean = new ConsumerBean();
        registry.registerTool(
            bean,
            ConsumerBean.class.getMethod("currentDate"),
            ConsumerBean.class.getMethod("currentDate").getAnnotation(MeshTool.class));

        registry.injectConsumerNameTags("date-consumer");
        registry.injectConsumerNameTags("date-consumer");
        registry.injectConsumerNameTags("date-consumer");

        List<String> tags = registry.getTool("current-date").tags();
        long agentTagCount = tags.stream().filter("date-consumer"::equals).count();
        assertEquals(1, agentTagCount,
            "auto-tag injection must be idempotent — repeated calls should not duplicate the tag");
    }

    @Test
    void injectConsumerNameTags_skipsBlankAgentName() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        ConsumerBean bean = new ConsumerBean();
        registry.registerTool(
            bean,
            ConsumerBean.class.getMethod("currentDate"),
            ConsumerBean.class.getMethod("currentDate").getAnnotation(MeshTool.class));

        registry.injectConsumerNameTags("");
        registry.injectConsumerNameTags(null);
        registry.injectConsumerNameTags("   ");

        List<String> tags = registry.getTool("current-date").tags();
        assertEquals(List.of("a2a-bridge"), tags,
            "blank/null agent name should leave tags untouched (consumer-only mode)");
    }

    @Test
    void injectConsumerNameTags_propagatesToHeartbeatToolSpecs() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        ConsumerBean bean = new ConsumerBean();
        registry.registerTool(
            bean,
            ConsumerBean.class.getMethod("currentDate"),
            ConsumerBean.class.getMethod("currentDate").getAnnotation(MeshTool.class));

        registry.injectConsumerNameTags("date-consumer");

        // Confirm the auto-tag flows through to the AgentSpec.ToolSpec
        // emitted in the heartbeat — this is what the registry actually
        // sees, and what the resolver uses for capability+tag matching.
        AgentSpec.ToolSpec spec = registry.getToolSpecs().stream()
            .filter(s -> "current-date".equals(s.getCapability()))
            .findFirst()
            .orElseThrow();
        assertTrue(spec.getTags().contains("a2a-bridge"),
            "heartbeat ToolSpec must keep the user-supplied tag");
        assertTrue(spec.getTags().contains("date-consumer"),
            "heartbeat ToolSpec must include the auto-injected consumer-name tag");
    }
}
