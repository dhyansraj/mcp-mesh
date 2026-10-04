package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationContext;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

/**
 * Settling-window grace for {@code @MeshLlm} provider injection (issue #1592,
 * the same fix as #1593's LLM bullet; Python #1456, TypeScript #1628).
 *
 * <p>A call landing before the provider resolves used to get an unavailable
 * agent, whose {@code generate()} threw "LLM provider not available". It now
 * waits — bounded by the remaining settle budget — on a per-consumer key
 * ({@code llm:<funcId>}, Python's {@code _llm_settle_key}) that resolves when
 * the provider lands.
 */
class MeshLlmSettleGraceTest {

    @SuppressWarnings("unused")
    static class Tool {
        @MeshLlm(providerSelector = @Selector(capability = "llm"))
        public String chat(@Param("q") String q, MeshLlmAgent llm) {
            return (llm != null && llm.isAvailable()) ? "resolved" : "degraded";
        }

        // A MeshLlmAgent parameter WITHOUT @MeshLlm: no provider will come.
        public String bare(@Param("q") String q, MeshLlmAgent llm) {
            return (llm != null && llm.isAvailable()) ? "resolved" : "degraded";
        }
    }

    private static final String FUNC_ID = "Tool.chat";

    @AfterEach
    void reset() {
        MeshSettleState.resetForTests();
    }

    private static Method chat() throws Exception {
        return Tool.class.getMethod("chat", String.class, MeshLlmAgent.class);
    }

    private static MeshToolWrapper newWrapper() throws Exception {
        return new MeshToolWrapper(FUNC_ID, "chat", "test", new Tool(), chat(), List.of(),
            JsonMapper.builder().build());
    }

    private static MeshToolWrapperRegistry newRegistry() {
        return new MeshToolWrapperRegistry(new McpMeshToolProxyFactory(new McpHttpClient()));
    }

    @Test
    void registeringAnLlmConsumerDeclaresItsPerConsumerKey() throws Exception {
        MeshToolWrapper wrapper = newWrapper();
        MeshSettleState.resetForTests(10.0);
        newRegistry().registerWrapper(wrapper);

        assertTrue(MeshSettleState.getInstance().isDeclared("llm:" + FUNC_ID));
        assertEquals("llm:" + FUNC_ID, MeshToolWrapperRegistry.buildLlmSettleKey(FUNC_ID));
    }

    @Test
    void callWaitsForTheProviderAndProceedsTheMomentItLands() throws Exception {
        MeshToolWrapper wrapper = newWrapper();
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        newRegistry().registerWrapper(wrapper);

        // The proxy is installed before its provider (handleLlmToolsUpdated).
        MeshLlmAgentProxy proxy = new MeshLlmAgentProxy(FUNC_ID);
        wrapper.updateLlmAgent(0, proxy);

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            proxy.updateProvider("http://localhost:1", "llm_generate", "anthropic");
            wrapper.markLlmProviderResolved();
        });
        resolver.start();

        long start = System.nanoTime();
        Object result = wrapper.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        assertEquals("resolved", result, "the woken call must see the available agent");
        assertTrue(elapsedMs < 5000, "unblocked by the provider event, not the budget; " + elapsedMs + "ms");
        assertTrue(state.getWaitCount() >= 1);
        assertTrue(state.isSettled(), "the provider key was the only declared key");
    }

    @Test
    void aMeshLlmAgentParameterWithoutMeshLlmDeclaresNothingAndNeverWaits() throws Exception {
        MeshToolWrapper wrapper = new MeshToolWrapper("Tool.bare", "bare", "test", new Tool(),
            Tool.class.getMethod("bare", String.class, MeshLlmAgent.class), List.of(),
            JsonMapper.builder().build());
        MeshSettleState.resetForTests(10.0);
        newRegistry().registerWrapper(wrapper);
        assertFalse(MeshSettleState.getInstance().isDeclared("llm:Tool.bare"),
            "no @MeshLlm, no provider, no key — Python declares it only in @mesh.llm");

        long start = System.nanoTime();
        assertEquals("degraded", wrapper.invoke(Map.of("q", "x")));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertTrue(elapsedMs < 2000, "must not sit out the settle budget; waited " + elapsedMs + "ms");
        assertEquals(0, MeshSettleState.getInstance().getWaitCount());
    }

    @Test
    void budgetExpiryProceedsAsBefore() throws Exception {
        MeshToolWrapper wrapper = newWrapper();
        wrapper.updateLlmAgent(0, new MeshLlmAgentProxy(FUNC_ID));
        MeshSettleState.resetForTests(0.3);
        MeshSettleState.getInstance().registerDeclared("llm:" + FUNC_ID);

        long start = System.nanoTime();
        Object result = wrapper.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertEquals("degraded", result, "an unresolved provider still reaches user code unavailable");
        assertTrue(elapsedMs >= 200, "expected a wait toward the budget, got " + elapsedMs + "ms");
    }

    @Test
    void settledAgentNeverWaits() throws Exception {
        MeshToolWrapper wrapper = newWrapper();
        wrapper.updateLlmAgent(0, new MeshLlmAgentProxy(FUNC_ID));
        MeshSettleState.resetForTests(0.0);

        assertEquals("degraded", wrapper.invoke(Map.of("q", "x")));
        assertEquals(0, MeshSettleState.getInstance().getWaitCount());
    }

    @Test
    void providerEventResolvesTheKey_bothWhenCreatingAndWhenUpdatingTheProxy() throws Exception {
        MeshToolWrapper wrapper = newWrapper();
        MeshSettleState.resetForTests(10.0);
        MeshToolWrapperRegistry registry = newRegistry();
        registry.registerWrapper(wrapper);
        McpHttpClient client = new McpHttpClient();
        MeshEventProcessor processor = new MeshEventProcessor(
            mock(MeshRuntime.class), mock(MeshDependencyInjector.class), registry,
            new MeshLlmRegistry(), client, null, null, mock(ApplicationContext.class), null);

        Method update = MeshEventProcessor.class.getDeclaredMethod(
            "updateWrapperLlmAgent", String.class, String.class, String.class, String.class);
        update.setAccessible(true);

        // First provider event: no proxy yet — the processor creates one.
        update.invoke(processor, FUNC_ID, "http://localhost:1", "llm_generate", "anthropic");
        assertTrue(MeshSettleState.getInstance().isResolved("llm:" + FUNC_ID));

        // A later event updates the existing proxy and resolves again (idempotent).
        MeshSettleState.resetForTests(10.0);
        MeshSettleState.getInstance().registerDeclared("llm:" + FUNC_ID);
        update.invoke(processor, FUNC_ID, "http://localhost:2", "llm_generate", "anthropic");
        assertTrue(MeshSettleState.getInstance().isResolved("llm:" + FUNC_ID));
    }
}
