package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 LOW: duplicate {@code @MeshTool} capability names must fail fast
 * at boot instead of silently last-wins overwriting — one of the two tools
 * would otherwise never be served while still appearing registered.
 */
@DisplayName("MeshToolRegistry — duplicate capability fail-fast (issue #1164 LOW)")
class MeshToolRegistryDuplicateCapabilityTest {

    public static class AgentOne {
        @MeshTool(capability = "lookup", description = "first")
        public String lookupV1(@Param("q") String q) {
            return "v1";
        }
    }

    public static class AgentTwo {
        @MeshTool(capability = "lookup", description = "second")
        public String lookupV2(@Param("q") String q) {
            return "v2";
        }
    }

    private static Method method(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("no method " + name + " on " + cls);
    }

    @Test
    @DisplayName("two different methods claiming the same capability → descriptive boot error")
    void duplicateCapabilityThrowsDescriptiveError() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method m1 = method(AgentOne.class, "lookupV1");
        Method m2 = method(AgentTwo.class, "lookupV2");

        registry.registerTool(new AgentOne(), m1, m1.getAnnotation(MeshTool.class));

        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> registry.registerTool(new AgentTwo(), m2, m2.getAnnotation(MeshTool.class)));

        assertTrue(ex.getMessage().contains("lookup"),
            "error must name the colliding capability. Got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("lookupV1") && ex.getMessage().contains("lookupV2"),
            "error must name both declaration sites. Got: " + ex.getMessage());
    }

    @Test
    @DisplayName("re-registering the SAME method is an idempotent refresh (prototype beans, context refresh)")
    void sameMethodReRegistrationIsTolerated() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method m1 = method(AgentOne.class, "lookupV1");

        registry.registerTool(new AgentOne(), m1, m1.getAnnotation(MeshTool.class));
        AgentOne refreshed = new AgentOne();
        assertDoesNotThrow(() ->
            registry.registerTool(refreshed, m1, m1.getAnnotation(MeshTool.class)));

        assertSame(refreshed, registry.getTool("lookup").bean(),
            "re-registration must refresh the bean instance");
    }
}
