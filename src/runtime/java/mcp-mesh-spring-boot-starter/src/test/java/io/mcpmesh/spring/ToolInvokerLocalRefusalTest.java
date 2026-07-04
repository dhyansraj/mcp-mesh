package io.mcpmesh.spring;

import io.mcpmesh.types.MeshToolCallException;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1273 (review item 5): {@link ToolInvoker#invokeLocal} must not leak a
 * handler's {@code isError} {@link CallToolResult} back to local /
 * self-dependency / LLM callers as a SUCCESS value. It mirrors the remote path
 * ({@link McpHttpClient}), which throws {@link MeshToolCallException} on
 * {@code isError} — so the direct-invoke {@code dependency_unavailable} refusal
 * surfaces to local callers as the exception they already expect.
 */
class ToolInvokerLocalRefusalTest {

    private static CallToolResult refusal(String capability) {
        String json = "{\"error\":\"dependency_unavailable\",\"capability\":\""
            + capability + "\"}";
        return new CallToolResult(List.of(new TextContent(json)), true, null, null);
    }

    @Test
    void invokeLocal_isErrorResult_throwsMeshToolCallException() throws Exception {
        MeshToolWrapperRegistry registry = mock(MeshToolWrapperRegistry.class);
        McpToolHandler handler = mock(McpToolHandler.class);
        when(handler.getFuncId()).thenReturn("Bean.enrich");
        when(handler.getMethodName()).thenReturn("enrich");
        when(handler.invoke(Map.of())).thenReturn(refusal("lookup"));
        when(registry.getHandlerByCapability("enrich")).thenReturn(handler);

        ToolInvoker invoker = new ToolInvoker(null, registry, "agent-1");

        MeshToolCallException ex = assertThrows(MeshToolCallException.class,
            () -> invoker.invokeLocal("enrich", Map.of()));
        assertTrue(ex.getMessage().contains("dependency_unavailable"),
            "the exception must carry the refusal envelope; got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("lookup"),
            "the exception must name the missing capability; got: " + ex.getMessage());
    }

    @Test
    void invokeLocal_successResult_returnedAsIs() throws Exception {
        MeshToolWrapperRegistry registry = mock(MeshToolWrapperRegistry.class);
        McpToolHandler handler = mock(McpToolHandler.class);
        when(handler.getFuncId()).thenReturn("Bean.enrich");
        when(handler.getMethodName()).thenReturn("enrich");
        when(handler.invoke(Map.of())).thenReturn("ok");
        when(registry.getHandlerByCapability("enrich")).thenReturn(handler);

        ToolInvoker invoker = new ToolInvoker(null, registry, "agent-1");

        assertEquals("ok", invoker.invokeLocal("enrich", Map.of()),
            "a non-error result must pass through unchanged");
    }
}
