package io.mcpmesh.spring.a2a;

import io.mcpmesh.Param;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.spring.MeshToolWrapper;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #923: verify that {@link MeshToolWrapper} recognises the
 * {@link A2AClient} parameter slot, exempts it from the MCP input
 * schema, and injects the bound client at dispatch time.
 */
class MeshToolWrapperA2AInjectionTest {

    /** Sink bean — captures the injected A2AClient so the test can assert identity. */
    @SuppressWarnings("unused")
    static class Bridge {
        final AtomicReference<A2AClient> received = new AtomicReference<>();

        // Annotation must be present at wrapper-construction time —
        // CodeRabbit Fix 3 added a boot-time guard rejecting A2AClient
        // params on methods without @A2AConsumer. The url here is
        // unused by the wrapper (the post-processor owns config); we
        // just need the marker so analyzeParameters lets the slot through.
        @A2AConsumer(url = "http://localhost:9090/agents/date", skillId = "get-date")
        public Map<String, Object> currentDate(@Param("hint") String hint, A2AClient a2a) {
            received.set(a2a);
            return Map.of("hint", hint == null ? "" : hint);
        }
    }

    private static Method find(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError("not found: " + name);
    }

    @Test
    void wrapper_capturesA2AClientSlot_andExemptsItFromInputSchema() {
        Bridge bridge = new Bridge();
        MeshToolWrapper w = new MeshToolWrapper(
            "Bridge.currentDate",
            "current-date",
            "test",
            bridge,
            find(Bridge.class, "currentDate"),
            List.of(),
            JsonMapper.builder().build()
        );
        // The A2AClient slot sits at signature position 1 (after @Param("hint")).
        assertEquals(1, w.getA2AClientParamIndex(),
            "wrapper must record the A2AClient slot index");

        Map<String, Object> schema = w.getInputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        assertEquals(1, properties.size(),
            "A2AClient param must be excluded from the MCP input schema");
        assertTrue(properties.containsKey("hint"));
        assertFalse(properties.containsKey("a2a"),
            "injected A2AClient slot must not bleed into the MCP schema");
    }

    @Test
    void wrapper_injectsBoundA2AClientAtDispatch() throws Exception {
        Bridge bridge = new Bridge();
        MeshToolWrapper w = new MeshToolWrapper(
            "Bridge.currentDate",
            "current-date",
            "test",
            bridge,
            find(Bridge.class, "currentDate"),
            List.of(),
            JsonMapper.builder().build()
        );
        // The cached A2AClient that the bean post-processor would normally
        // hand us. Real wiring goes through MeshToolBeanPostProcessor.
        A2AClient expected = new A2AClient("http://localhost:9090/agents/date", "get-date");
        try {
            w.setA2AClientBinding(1, expected);

            Object result = w.invoke(Map.of("hint", "now"));
            assertNotNull(result);
            assertSame(expected, bridge.received.get(),
                "dispatch must pass the bound A2AClient through to the user method");
        } finally {
            expected.close();
        }
    }

    @Test
    void wrapper_setA2AClientBinding_rejectsSlotMismatch() {
        Bridge bridge = new Bridge();
        MeshToolWrapper w = new MeshToolWrapper(
            "Bridge.currentDate",
            "current-date",
            "test",
            bridge,
            find(Bridge.class, "currentDate"),
            List.of(),
            JsonMapper.builder().build()
        );
        A2AClient client = new A2AClient("http://localhost:9090/agents/date", "get-date");
        try {
            // The wrapper analysed the slot at index 1; a post-processor
            // claiming index 0 means the wiring drifted and we should fail
            // loudly rather than silently inject into the wrong slot.
            assertThrows(IllegalStateException.class,
                () -> w.setA2AClientBinding(0, client));
        } finally {
            client.close();
        }
    }

    @Test
    void wrapper_setA2AClientBinding_rejectsMethodWithoutSlot() {
        // Method with no A2AClient param — wrapper must refuse to bind.
        @SuppressWarnings("unused")
        class PlainBean {
            public String plain(@Param("x") String x) {
                return x;
            }
        }
        PlainBean bean = new PlainBean();
        MeshToolWrapper w = new MeshToolWrapper(
            "PlainBean.plain",
            "plain",
            "test",
            bean,
            find(PlainBean.class, "plain"),
            List.of(),
            JsonMapper.builder().build()
        );
        assertNull(w.getA2AClientParamIndex(),
            "method without A2AClient param must report null slot index");
        A2AClient client = new A2AClient("http://localhost:9090/agents/date", "get-date");
        try {
            assertThrows(IllegalStateException.class,
                () -> w.setA2AClientBinding(0, client),
                "binding must be rejected when the wrapper has no slot to inject into");
        } finally {
            client.close();
        }
    }

    /** A bean whose @MeshTool method has an A2AClient parameter but NO @A2AConsumer. */
    @SuppressWarnings("unused")
    static class A2AClientWithoutConsumerBean {
        public String orphan(@Param("hint") String hint, A2AClient a2a) {
            return hint;
        }
    }

    @Test
    void wrapper_rejectsA2AClientParamWithoutA2AConsumerAtBoot() {
        // CodeRabbit Fix 3: an A2AClient parameter on a @MeshTool method
        // that lacks @A2AConsumer has no upstream URL/auth/timeout to
        // bind to. The dispatch wrapper would silently inject null and
        // the user method would NPE on the first a2a.send(...) call.
        // Fail BOOT (wrapper construction == registration time) so the
        // misuse surfaces immediately.
        A2AClientWithoutConsumerBean bean = new A2AClientWithoutConsumerBean();
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> new MeshToolWrapper(
                "A2AClientWithoutConsumerBean.orphan",
                "orphan",
                "test",
                bean,
                find(A2AClientWithoutConsumerBean.class, "orphan"),
                List.of(),
                JsonMapper.builder().build()
            ));
        assertTrue(ex.getMessage().contains("@A2AConsumer"),
            "must reference the missing @A2AConsumer annotation, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("A2AClient"),
            "must mention the A2AClient parameter, got: " + ex.getMessage());
    }
}
