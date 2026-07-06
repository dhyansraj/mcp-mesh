package io.mcpmesh.spring;

import io.mcpmesh.types.MeshSupersededException;
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
 * Issue #1278 — consumer recognize + swallow point for the LOCAL /
 * self-dependency / LLM path ({@link ToolInvoker#invokeLocal}). Mirrors
 * {@link ToolInvokerLocalRefusalTest}: a handler that RETURNS the reserved
 * {@code claim_superseded} isError envelope must surface to the local caller as
 * the typed {@link MeshSupersededException} (not re-wrapped by the outer
 * {@code catch}), while a generic isError — or {@code dependency_unavailable} —
 * still surfaces as {@link MeshToolCallException}.
 */
class ToolInvokerSupersededTest {

    private static CallToolResult errorResult(String envelope) {
        return new CallToolResult(List.of(new TextContent(envelope)), true, null, null);
    }

    private static ToolInvoker invokerReturning(CallToolResult result) throws Exception {
        MeshToolWrapperRegistry registry = mock(MeshToolWrapperRegistry.class);
        McpToolHandler handler = mock(McpToolHandler.class);
        when(handler.getFuncId()).thenReturn("Bean.mutate");
        when(handler.getMethodName()).thenReturn("mutate");
        when(handler.invoke(Map.of())).thenReturn(result);
        when(registry.getHandlerByCapability("mutate")).thenReturn(handler);
        return new ToolInvoker(null, registry, "agent-1");
    }

    @Test
    void reservedEnvelopeWithDetail_throwsTypedSignal_untouched() throws Exception {
        ToolInvoker invoker = invokerReturning(
            errorResult("{\"error\":\"claim_superseded\",\"detail\":\"stale\"}"));

        // Swallow-point: the caught exception is the typed signal, NOT a
        // MeshToolCallException wrapping it.
        MeshSupersededException e = assertThrows(MeshSupersededException.class,
            () -> invoker.invokeLocal("mutate", Map.of()));
        assertEquals("stale", e.getDetail());
    }

    @Test
    void reservedEnvelopeNoDetail_throwsTypedSignal_detailNull() throws Exception {
        ToolInvoker invoker = invokerReturning(
            errorResult("{\"error\":\"claim_superseded\"}"));

        MeshSupersededException e = assertThrows(MeshSupersededException.class,
            () -> invoker.invokeLocal("mutate", Map.of()));
        assertNull(e.getDetail());
    }

    @Test
    void dependencyUnavailableEnvelope_stillThrowsMeshToolCallException() throws Exception {
        ToolInvoker invoker = invokerReturning(
            errorResult("{\"error\":\"dependency_unavailable\",\"capability\":\"lookup\"}"));

        assertThrows(MeshToolCallException.class,
            () -> invoker.invokeLocal("mutate", Map.of()),
            "dependency_unavailable must not be misclassified as supersession");
    }

    @Test
    void genericErrorText_stillThrowsMeshToolCallException() throws Exception {
        ToolInvoker invoker = invokerReturning(errorResult("boom"));

        assertThrows(MeshToolCallException.class,
            () -> invoker.invokeLocal("mutate", Map.of()));
    }
}
