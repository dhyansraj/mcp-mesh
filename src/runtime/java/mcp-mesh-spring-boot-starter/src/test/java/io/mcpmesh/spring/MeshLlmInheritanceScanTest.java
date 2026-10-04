package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * {@code @MeshLlm} scanning uses the same {@code MethodIntrospector} selection
 * as {@code @MeshTool} (#1164 / #1569 class): an overridden method registers
 * once, under the same {@link Method} the tool registers with.
 */
@DisplayName("@MeshLlm: inherited / overridden methods register once, under the tool's Method")
class MeshLlmInheritanceScanTest {

    public abstract static class BaseChat {
        @MeshLlm(providerSelector = @Selector(capability = "llm", tags = {"+claude"}))
        @MeshTool(capability = "chat")
        public String chat(@Param("message") String message, MeshLlmAgent llm) {
            return message;
        }
    }

    /** Bare override: no @Param, so the tool registers the BASE declaration. */
    public static class OverridingChat extends BaseChat {
        @Override
        public String chat(String message, MeshLlmAgent llm) {
            return "override";
        }
    }

    @Test
    @DisplayName("bare override: one config, keyed by the declaration MeshToolBeanPostProcessor registers")
    void overrideRegistersOnceUnderToolMethod() throws Exception {
        MeshLlmRegistry registry = new MeshLlmRegistry();
        new MeshLlmBeanPostProcessor(registry).postProcessAfterInitialization(new OverridingChat(), "chat");

        assertEquals(1, registry.getAllConfigs().size());
        Method specific = OverridingChat.class.getMethod("chat", String.class, MeshLlmAgent.class);
        Method toolTarget = MeshToolBeanPostProcessor.selectRegistrationTarget(specific);
        assertEquals(BaseChat.class, toolTarget.getDeclaringClass(), "fixture: tool registers the base");
        assertNotNull(registry.getByMethod(toolTarget));
        assertNotNull(registry.getByFunctionId(OverridingChat.class.getName() + ".chat"));
    }
}
