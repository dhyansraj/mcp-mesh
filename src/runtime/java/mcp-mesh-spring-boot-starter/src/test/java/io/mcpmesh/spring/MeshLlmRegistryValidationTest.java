package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.Selector;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Validates that {@link MeshLlmRegistry#register} rejects {@code @MeshLlm}
 * annotations with an empty {@code providerSelector} after the v2 direct-mode
 * removal (#859).
 *
 * <p>Before v2, an unset {@code providerSelector} silently registered fine and
 * the consumer would only fail on the first {@code generate()} call. After v2,
 * registration must fail loudly so the misconfig surfaces at startup.
 */
@DisplayName("MeshLlmRegistry — providerSelector required (v2)")
class MeshLlmRegistryValidationTest {

    static class GoodConsumer {
        @MeshLlm(providerSelector = @Selector(capability = "llm", tags = {"+claude"}))
        public String good() {
            return "ok";
        }
    }

    static class MissingSelectorConsumer {
        // Empty default @Selector — no capability set
        @MeshLlm
        public String bad() {
            return "ok";
        }
    }

    static class EmptyCapabilityConsumer {
        @MeshLlm(providerSelector = @Selector(tags = {"+claude"}))
        public String bad() {
            return "ok";
        }
    }

    @Test
    @DisplayName("registers @MeshLlm with non-empty providerSelector capability")
    void registersValidConsumer() throws Exception {
        MeshLlmRegistry registry = new MeshLlmRegistry();
        Method m = GoodConsumer.class.getMethod("good");
        MeshLlm ann = m.getAnnotation(MeshLlm.class);

        // Should not throw
        registry.register(GoodConsumer.class, m, ann);

        MeshLlmRegistry.LlmConfig cfg = registry.getByMethod(m);
        assertNotNull(cfg);
        assertEquals("llm", cfg.providerSelector().capability());
    }

    @Test
    @DisplayName("rejects @MeshLlm with default empty providerSelector")
    void rejectsMissingSelector() throws Exception {
        MeshLlmRegistry registry = new MeshLlmRegistry();
        Method m = MissingSelectorConsumer.class.getMethod("bad");
        MeshLlm ann = m.getAnnotation(MeshLlm.class);

        IllegalStateException ex = assertThrows(
            IllegalStateException.class,
            () -> registry.register(MissingSelectorConsumer.class, m, ann)
        );
        assertTrue(ex.getMessage().contains("providerSelector"),
            "error should mention providerSelector, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("Direct LLM mode was removed in v2"),
            "error should reference v2 migration, got: " + ex.getMessage());
    }

    @Test
    @DisplayName("rejects @MeshLlm with empty capability() in providerSelector")
    void rejectsEmptyCapability() throws Exception {
        MeshLlmRegistry registry = new MeshLlmRegistry();
        Method m = EmptyCapabilityConsumer.class.getMethod("bad");
        MeshLlm ann = m.getAnnotation(MeshLlm.class);

        IllegalStateException ex = assertThrows(
            IllegalStateException.class,
            () -> registry.register(EmptyCapabilityConsumer.class, m, ann)
        );
        assertTrue(ex.getMessage().contains("non-empty capability"),
            "error should mention non-empty capability, got: " + ex.getMessage());
    }
}
