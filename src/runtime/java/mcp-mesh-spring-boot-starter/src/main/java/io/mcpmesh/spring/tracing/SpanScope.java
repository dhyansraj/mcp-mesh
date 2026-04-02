package io.mcpmesh.spring.tracing;

import java.util.LinkedHashMap;
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
    private Map<String, Object> metadata;
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
     * Record request and response payload sizes.
     *
     * @param requestBytes  Size of the outgoing request in bytes
     * @param responseBytes Size of the incoming response in bytes
     * @return this for chaining
     */
    public SpanScope withPayloadSizes(int requestBytes, int responseBytes) {
        if (this == NOOP) return this;
        ensureMutableMetadata();
        this.metadata.put("request_bytes", requestBytes);
        this.metadata.put("response_bytes", responseBytes);
        return this;
    }

    /**
     * Record LLM token usage metadata.
     *
     * @param provider     LLM provider name (e.g., "anthropic", "openai")
     * @param model        Model identifier (e.g., "claude-sonnet-4-20250514")
     * @param inputTokens  Number of input/prompt tokens
     * @param outputTokens Number of output/completion tokens
     * @return this for chaining
     */
    public SpanScope withLlmMeta(String provider, String model, int inputTokens, int outputTokens) {
        if (this == NOOP) return this;
        ensureMutableMetadata();
        this.metadata.put("llm_input_tokens", inputTokens);
        this.metadata.put("llm_output_tokens", outputTokens);
        this.metadata.put("llm_total_tokens", inputTokens + outputTokens);
        this.metadata.put("llm_model", model);
        this.metadata.put("llm_provider", provider);
        return this;
    }

    /**
     * Ensure the metadata map is mutable.
     *
     * <p>The metadata map may be an unmodifiable map (e.g., from {@code Map.of()}).
     * This method replaces it with a mutable {@link LinkedHashMap} if needed.
     */
    private void ensureMutableMetadata() {
        if (this.metadata == null) {
            this.metadata = new LinkedHashMap<>();
        } else {
            try {
                this.metadata.put("_probe", null);
                this.metadata.remove("_probe");
            } catch (UnsupportedOperationException e) {
                this.metadata = new LinkedHashMap<>(this.metadata);
            }
        }
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
