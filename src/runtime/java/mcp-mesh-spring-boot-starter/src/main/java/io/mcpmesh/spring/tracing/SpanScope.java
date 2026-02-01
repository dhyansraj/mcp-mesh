package io.mcpmesh.spring.tracing;

import java.util.Map;

/**
 * RAII-style span management for try-with-resources.
 *
 * <p>Usage:
 * <pre>
 * try (SpanScope span = tracer.startSpan("myFunction", metadata)) {
 *     Object result = doWork();
 *     span.withResult(result);
 *     return result;
 * } catch (Exception e) {
 *     // SpanScope.close() automatically records the error
 *     throw e;
 * }
 * </pre>
 *
 * <p>The span is automatically ended and published when the try block completes.
 */
public class SpanScope implements AutoCloseable {

    /**
     * No-op span scope for when tracing is disabled.
     */
    public static final SpanScope NOOP = new SpanScope();

    private final TraceInfo span;
    private final TraceInfo parentInfo;
    private final String functionName;
    private final Map<String, Object> metadata;
    private final ExecutionTracer tracer;

    private Object result;
    private Throwable error;

    /**
     * Private constructor for NOOP instance.
     */
    private SpanScope() {
        this.span = null;
        this.parentInfo = null;
        this.functionName = null;
        this.metadata = null;
        this.tracer = null;
    }

    /**
     * Create a new SpanScope.
     *
     * @param span Current span's TraceInfo
     * @param parentInfo Parent span's TraceInfo (for context restoration)
     * @param functionName Name of the function being traced
     * @param metadata Additional metadata to include in the span
     * @param tracer ExecutionTracer for publishing the span
     */
    SpanScope(TraceInfo span, TraceInfo parentInfo, String functionName,
              Map<String, Object> metadata, ExecutionTracer tracer) {
        this.span = span;
        this.parentInfo = parentInfo;
        this.functionName = functionName;
        this.metadata = metadata;
        this.tracer = tracer;
    }

    /**
     * Record the result of the operation.
     *
     * @param result The result value
     * @return this for chaining
     */
    public SpanScope withResult(Object result) {
        this.result = result;
        return this;
    }

    /**
     * Record an error that occurred during the operation.
     *
     * @param error The error/exception
     * @return this for chaining
     */
    public SpanScope withError(Throwable error) {
        this.error = error;
        return this;
    }

    /**
     * End the span and publish to Redis.
     *
     * <p>This is called automatically when used in try-with-resources.
     * After closing, the parent context is restored.
     */
    @Override
    public void close() {
        if (tracer != null && this != NOOP) {
            tracer.endSpan(this, result, error);
        }
    }

    /**
     * Check if this is the NOOP span (tracing disabled).
     */
    public boolean isNoop() {
        return this == NOOP;
    }

    // Getters (package-private for ExecutionTracer access)

    TraceInfo getSpan() {
        return span;
    }

    TraceInfo getParentInfo() {
        return parentInfo;
    }

    String getFunctionName() {
        return functionName;
    }

    Map<String, Object> getMetadata() {
        return metadata;
    }
}
