package io.mcpmesh.spring.tracing;

import java.util.UUID;

/**
 * Holds trace context information for a single span.
 *
 * <p>Uses OpenTelemetry-compliant ID formats:
 * <ul>
 *   <li>trace_id: 32-character hex string (128-bit)</li>
 *   <li>span_id: 16-character hex string (64-bit)</li>
 * </ul>
 */
public class TraceInfo {

    private final String traceId;
    private final String spanId;
    private final String parentSpan;
    private final long startTime;

    /**
     * Create a new TraceInfo with all fields.
     */
    public TraceInfo(String traceId, String spanId, String parentSpan, long startTime) {
        this.traceId = traceId;
        this.spanId = spanId;
        this.parentSpan = parentSpan;
        this.startTime = startTime;
    }

    /**
     * Create a new TraceInfo with current time as start time.
     */
    public TraceInfo(String traceId, String spanId, String parentSpan) {
        this(traceId, spanId, parentSpan, System.currentTimeMillis());
    }

    /**
     * Create a new root trace (no parent).
     *
     * @return New TraceInfo with generated trace_id and span_id
     */
    public static TraceInfo createRoot() {
        return new TraceInfo(
            generateTraceId(),
            generateSpanId(),
            null,
            System.currentTimeMillis()
        );
    }

    /**
     * Create a child span from this trace context.
     *
     * <p>The child span:
     * <ul>
     *   <li>Inherits the same trace_id</li>
     *   <li>Gets a new span_id</li>
     *   <li>Uses this span's span_id as parent_span</li>
     * </ul>
     *
     * @return New TraceInfo representing a child span
     */
    public TraceInfo createChild() {
        return new TraceInfo(
            this.traceId,
            generateSpanId(),
            this.spanId,
            System.currentTimeMillis()
        );
    }

    /**
     * Create TraceInfo from incoming request headers.
     *
     * @param traceId Trace ID from X-Trace-ID header
     * @param parentSpan Parent span from X-Parent-Span header (may be null)
     * @return New TraceInfo with given trace context and new span_id
     * @deprecated Use {@link #forPropagation(String, String)} instead to avoid phantom span creation.
     *             Kept for backward compatibility with external callers.
     */
    @Deprecated
    public static TraceInfo fromHeaders(String traceId, String parentSpan) {
        return new TraceInfo(
            traceId,
            generateSpanId(),
            parentSpan,
            System.currentTimeMillis()
        );
    }

    /**
     * Create TraceInfo for trace propagation from incoming headers.
     *
     * <p>Unlike {@link #fromHeaders}, this method does NOT generate a new span_id.
     * Instead, the incoming parent span becomes the current span_id so that
     * {@link #createChild()} correctly parents to the actual caller.
     * If {@code incomingParentSpan} is null (root calls with no parent),
     * the span ID will be null, causing {@link #createChild()} to produce a root span with no parent.
     *
     * @param traceId Trace ID from X-Trace-ID header
     * @param incomingParentSpan Parent span from X-Parent-Span header (may be null for root calls)
     * @return TraceInfo suitable for use in TraceContext propagation
     */
    public static TraceInfo forPropagation(String traceId, String incomingParentSpan) {
        return new TraceInfo(traceId, incomingParentSpan, null, System.currentTimeMillis());
    }

    /**
     * Generate a new trace ID (OpenTelemetry compliant).
     *
     * @return 32-character hex string (128-bit trace ID)
     */
    public static String generateTraceId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * Generate a new span ID (OpenTelemetry compliant).
     *
     * @return 16-character hex string (64-bit span ID)
     */
    public static String generateSpanId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }

    // Getters

    public String getTraceId() {
        return traceId;
    }

    public String getSpanId() {
        return spanId;
    }

    public String getParentSpan() {
        return parentSpan;
    }

    public long getStartTime() {
        return startTime;
    }

    @Override
    public String toString() {
        return "TraceInfo{" +
            "traceId='" + (traceId != null ? traceId.substring(0, 8) + "..." : "null") + '\'' +
            ", spanId='" + (spanId != null ? spanId.substring(0, 8) + "..." : "null") + '\'' +
            ", parentSpan='" + (parentSpan != null ? parentSpan.substring(0, 8) + "..." : "null") + '\'' +
            '}';
    }
}
