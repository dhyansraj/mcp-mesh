package io.mcpmesh.spring.tracing;

import io.mcpmesh.core.TracingBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Manages span creation, execution tracking, and publishing.
 *
 * <p>ExecutionTracer handles the lifecycle of trace spans:
 * <ol>
 *   <li>Start span: Generate span_id, record start time, set parent context</li>
 *   <li>Execute: The actual function runs</li>
 *   <li>End span: Record duration, success/error, publish to Redis, restore parent</li>
 * </ol>
 *
 * <p>Usage:
 * <pre>
 * try (SpanScope span = tracer.startSpan("myFunction", metadata)) {
 *     Object result = doWork();
 *     span.withResult(result);
 *     return result;
 * }
 * </pre>
 */
public class ExecutionTracer {

    private static final Logger log = LoggerFactory.getLogger(ExecutionTracer.class);

    private final TracePublisher publisher;
    private final AgentContextProvider agentContext;
    private final boolean enabled;

    /**
     * Create an ExecutionTracer.
     *
     * @param publisher Publisher for sending spans to Redis
     * @param agentContext Provider for agent metadata
     */
    public ExecutionTracer(TracePublisher publisher, AgentContextProvider agentContext) {
        this.publisher = publisher;
        this.agentContext = agentContext;
        this.enabled = isTracingEnabled();

        if (enabled) {
            log.info("ExecutionTracer initialized with tracing ENABLED");
        } else {
            log.debug("ExecutionTracer initialized with tracing DISABLED");
        }
    }

    /**
     * Start a new span for function execution.
     *
     * <p>If tracing is disabled, returns a NOOP span that does nothing.
     *
     * @param functionName Name of the function being traced
     * @param metadata Additional metadata to include in the span
     * @return SpanScope for managing the span lifecycle
     */
    public SpanScope startSpan(String functionName, Map<String, Object> metadata) {
        if (!enabled) {
            return SpanScope.NOOP;
        }

        TraceInfo current = TraceContext.get();
        TraceInfo span;

        if (current != null) {
            // Create child span from current context
            span = current.createChild();
            log.trace("Created child span for {}: trace={}, span={}, parent={}",
                functionName,
                span.getTraceId().substring(0, 8),
                span.getSpanId().substring(0, 8),
                span.getParentSpan() != null ? span.getParentSpan().substring(0, 8) : "null");
        } else {
            // Create root span (fallback if context not propagated)
            span = TraceInfo.createRoot();
            log.debug("Created root trace for {} (no incoming context): trace={}",
                functionName, span.getTraceId().substring(0, 8));
        }

        // Set new span as current context for nested calls
        TraceContext.set(span);

        return new SpanScope(span, current, functionName, metadata, this);
    }

    /**
     * End a span and publish to Redis.
     *
     * <p>This is called by SpanScope.close() and should not be called directly.
     *
     * @param scope The span scope to end
     * @param result The result of the operation (may be null)
     * @param error Any error that occurred (may be null)
     */
    void endSpan(SpanScope scope, Object result, Throwable error) {
        if (!enabled || scope.isNoop()) {
            return;
        }

        TraceInfo span = scope.getSpan();
        if (span == null) {
            return;
        }

        long endTime = System.currentTimeMillis();
        long duration = endTime - span.getStartTime();

        // Build trace data
        Map<String, Object> traceData = new LinkedHashMap<>();
        traceData.put("trace_id", span.getTraceId());
        traceData.put("span_id", span.getSpanId());
        traceData.put("parent_span", span.getParentSpan());
        traceData.put("function_name", scope.getFunctionName());
        traceData.put("duration_ms", duration);
        traceData.put("success", error == null);
        traceData.put("start_time", span.getStartTime() / 1000.0);  // Convert to seconds
        traceData.put("end_time", endTime / 1000.0);
        traceData.put("published_at", System.currentTimeMillis() / 1000.0);

        // Add error info if present
        if (error != null) {
            traceData.put("error", error.getMessage());
            traceData.put("error_type", error.getClass().getName());
        }

        // Add result type
        if (result != null) {
            traceData.put("result_type", result.getClass().getSimpleName());
        } else {
            traceData.put("result_type", "null");
        }

        // Add agent context
        if (agentContext != null) {
            traceData.putAll(agentContext.getContext());
        }

        // Add custom metadata
        if (scope.getMetadata() != null) {
            traceData.putAll(scope.getMetadata());
        }

        // Publish asynchronously (non-blocking)
        if (publisher != null) {
            publisher.publish(traceData);
        }

        // CRITICAL: Restore parent context to prevent sibling nesting
        // Without this, subsequent calls become children of this span instead of siblings
        if (scope.getParentInfo() != null) {
            TraceContext.set(scope.getParentInfo());
        } else {
            TraceContext.clear();
        }

        log.trace("Ended span for {}: duration={}ms, success={}",
            scope.getFunctionName(), duration, error == null);
    }

    /**
     * Check if tracing is enabled.
     *
     * <p>Checks via Rust core first, then falls back to environment variable.
     *
     * @return true if tracing is enabled
     */
    public static boolean isTracingEnabled() {
        // Try Rust core first (handles config resolution properly)
        try {
            if (TracingBridge.isTracingEnabled()) {
                return true;
            }
        } catch (Exception e) {
            // Fall through to env var check
        }

        // Fallback to direct env var check
        String enabled = System.getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        if (enabled == null) {
            enabled = System.getProperty("mcp.mesh.distributed-tracing-enabled", "false");
        }
        return "true".equalsIgnoreCase(enabled) || "1".equals(enabled);
    }

    /**
     * Check if this tracer has tracing enabled.
     */
    public boolean isEnabled() {
        return enabled;
    }
}
