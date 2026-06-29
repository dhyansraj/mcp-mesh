package io.mcpmesh.spring.tracing;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Tracer-level coverage for the LLM token-telemetry emission path (issue #1227).
 *
 * <p>{@link MeshLlmAgentProxyTokenTelemetryTest} asserts that the agentic loop populates
 * {@link TraceContext#getLlmMetadata()}. This test drives the OTHER half of the contract:
 * that {@link ExecutionTracer#endSpan} actually DRAINS that per-thread sink into the
 * published span payload (via {@link SpanScope#withLlmMeta}) so the dashboard fields are
 * populated — and clears the sink after consumption. A regression that fails to stamp the
 * span (leaving dashboard fields empty) would be caught here but not by the proxy-level test.
 *
 * <p>The real publish path is exercised with a Mockito-mocked {@link TracePublisher} that
 * captures the trace-data map handed to {@code publish(...)}. Tracing is enabled for the
 * tracer via the {@code mcp.mesh.distributed-tracing-enabled} system property (the env-var
 * fallback in {@link ExecutionTracer#isTracingEnabled()} when the Rust core is not loaded).
 */
@DisplayName("ExecutionTracer — drains the LLM metadata sink into the published span (issue #1227)")
class ExecutionTracerLlmSpanTest {

    private String prevTracingProp;

    @BeforeEach
    void enableTracing() {
        prevTracingProp = System.getProperty("mcp.mesh.distributed-tracing-enabled");
        System.setProperty("mcp.mesh.distributed-tracing-enabled", "true");
        TraceContext.clear();
        TraceContext.clearLlmMetadata();
    }

    @AfterEach
    void restore() {
        if (prevTracingProp == null) {
            System.clearProperty("mcp.mesh.distributed-tracing-enabled");
        } else {
            System.setProperty("mcp.mesh.distributed-tracing-enabled", prevTracingProp);
        }
        TraceContext.clear();
        TraceContext.clearLlmMetadata();
    }

    @Test
    @DisplayName("endSpan stamps llm_* fields onto the published span and clears the sink")
    @SuppressWarnings("unchecked")
    void endSpanStampsLlmFieldsOntoPublishedSpan() {
        TracePublisher publisher = mock(TracePublisher.class);
        ExecutionTracer tracer = new ExecutionTracer(publisher, null);
        assertTrue(tracer.isEnabled(),
            "tracing must be ON for the emission path to run (system property fallback)");

        // The proxy publishes accumulated usage into the per-thread sink before the
        // consumer span closes; replicate that here.
        TraceContext.setLlmMetadata("anthropic", "claude-sonnet-4-20250514", 120, 45);

        try (SpanScope span = tracer.startSpan("test.consumer", null)) {
            span.withResult("done");
        }

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(publisher, times(1)).publish(captor.capture());
        Map<String, Object> published = captor.getValue();

        assertEquals(120L, ((Number) published.get("llm_input_tokens")).longValue(), "llm_input_tokens");
        assertEquals(45L, ((Number) published.get("llm_output_tokens")).longValue(), "llm_output_tokens");
        assertEquals(165L, ((Number) published.get("llm_total_tokens")).longValue(), "llm_total_tokens");
        assertEquals("claude-sonnet-4-20250514", published.get("llm_model"), "llm_model");
        assertEquals("anthropic", published.get("llm_provider"), "llm_provider");

        assertNull(TraceContext.getLlmMetadata(),
            "sink must be cleared after the tracer consumes it (no leak onto a later span)");
    }

    @Test
    @DisplayName("endSpan with no sink set publishes a span carrying no llm_* fields")
    @SuppressWarnings("unchecked")
    void endSpanWithoutSinkOmitsLlmFields() {
        TracePublisher publisher = mock(TracePublisher.class);
        ExecutionTracer tracer = new ExecutionTracer(publisher, null);

        // No TraceContext.setLlmMetadata(...) — e.g. a non-LLM tool span.
        try (SpanScope span = tracer.startSpan("test.tool", null)) {
            span.withResult("ok");
        }

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(publisher, times(1)).publish(captor.capture());
        Map<String, Object> published = captor.getValue();

        assertFalse(published.containsKey("llm_input_tokens"),
            "no sink → span must not carry zero/stale llm_* fields");
        assertFalse(published.containsKey("llm_total_tokens"));
        assertFalse(published.containsKey("llm_model"));
    }
}
