package io.mcpmesh.spring.tracing;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;

import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Spring Filter for extracting and propagating trace context.
 *
 * <p>This filter runs at the highest precedence to ensure trace context
 * is available to all downstream components.
 *
 * <p>Extracts trace context from HTTP headers:
 * <ul>
 *   <li>X-Trace-ID: The distributed trace ID</li>
 *   <li>X-Parent-Span: The parent span ID from the calling service</li>
 * </ul>
 *
 * <p>If no trace headers are present, the filter does NOT create a root trace.
 * Root trace creation is delegated to MeshToolWrapper when the tool executes,
 * which also handles extracting trace context from arguments (for TypeScript agents).
 */
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TracingFilter implements Filter {

    private static final Logger log = LoggerFactory.getLogger(TracingFilter.class);

    public static final String TRACE_ID_HEADER = "X-Trace-ID";
    public static final String PARENT_SPAN_HEADER = "X-Parent-Span";

    private final boolean enabled;

    /**
     * Create a TracingFilter.
     */
    public TracingFilter() {
        this.enabled = ExecutionTracer.isTracingEnabled();
        if (enabled) {
            log.info("TracingFilter initialized with tracing ENABLED");
        } else {
            log.debug("TracingFilter initialized with tracing DISABLED");
        }
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response,
                         FilterChain chain) throws IOException, ServletException {
        HttpServletRequest httpRequest = (HttpServletRequest) request;
        HttpServletResponse httpResponse = (HttpServletResponse) response;

        try {
            // CRITICAL: Clear any inherited context from previous requests
            // InheritableThreadLocal can leak context when thread pools reuse threads
            TraceContext.clear();
            TraceContext.clearPropagatedHeaders();

            // Extract trace context from headers
            String traceId = httpRequest.getHeader(TRACE_ID_HEADER);
            String parentSpan = httpRequest.getHeader(PARENT_SPAN_HEADER);

            if (traceId != null && !traceId.isEmpty()) {
                // Continue existing trace from upstream service
                // Create a new span for this request, with parent from headers
                TraceInfo traceInfo = TraceInfo.fromHeaders(traceId, parentSpan);
                TraceContext.set(traceInfo);

                log.trace("Extracted trace context from headers: trace={}, parent={}",
                    traceId.substring(0, Math.min(8, traceId.length())),
                    parentSpan != null ? parentSpan.substring(0, Math.min(8, parentSpan.length())) : "null");

                // Add trace headers to response for debugging (only when tracing enabled)
                if (enabled) {
                    httpResponse.setHeader(TRACE_ID_HEADER, traceInfo.getTraceId());
                    httpResponse.setHeader(PARENT_SPAN_HEADER, traceInfo.getSpanId());
                }
            } else {
                // No trace headers - don't create root trace here
                // MeshToolWrapper will handle creating root trace or extracting from arguments
                log.trace("No trace headers found, deferring context creation to MeshToolWrapper");
            }

            // Capture configured propagation headers from incoming request
            List<String> propagateNames = TraceContext.getPropagateHeaderNames();
            if (!propagateNames.isEmpty()) {
                Map<String, String> captured = new HashMap<>();
                for (String headerName : propagateNames) {
                    String value = httpRequest.getHeader(headerName);
                    if (value != null && !value.isEmpty()) {
                        captured.put(headerName.toLowerCase(), value);
                    }
                }
                if (!captured.isEmpty()) {
                    TraceContext.setPropagatedHeaders(captured);
                    log.trace("Captured {} propagation headers", captured.size());
                }
            }

            chain.doFilter(request, response);

        } finally {
            // Always clear context after request completes
            TraceContext.clear();
            TraceContext.clearPropagatedHeaders();
        }
    }
}
