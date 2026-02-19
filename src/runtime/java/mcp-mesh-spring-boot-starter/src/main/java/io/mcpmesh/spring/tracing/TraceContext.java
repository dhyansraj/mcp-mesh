package io.mcpmesh.spring.tracing;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

/**
 * Thread-safe trace context storage using InheritableThreadLocal.
 *
 * <p>InheritableThreadLocal allows child threads to inherit the trace context,
 * which is important for async operations using CompletableFuture, @Async, etc.
 *
 * <p>Usage:
 * <pre>
 * // Set context at request entry
 * TraceContext.set(traceInfo);
 *
 * // Get context anywhere in the request thread
 * TraceInfo info = TraceContext.get();
 *
 * // Clear at request completion
 * TraceContext.clear();
 *
 * // For async operations, wrap the task
 * executor.submit(TraceContext.wrap(() -> {
 *     // Trace context is available here
 *     TraceInfo info = TraceContext.get();
 * }));
 * </pre>
 */
public class TraceContext {

    static final List<String> PROPAGATE_HEADERS;

    static {
        String envVal = System.getenv("MCP_MESH_PROPAGATE_HEADERS");
        if (envVal != null && !envVal.trim().isEmpty()) {
            List<String> names = new ArrayList<>();
            for (String name : envVal.split(",")) {
                String trimmed = name.trim();
                if (!trimmed.isEmpty()) {
                    names.add(trimmed.toLowerCase());
                }
            }
            PROPAGATE_HEADERS = Collections.unmodifiableList(names);
        } else {
            PROPAGATE_HEADERS = Collections.emptyList();
        }
    }

    static final InheritableThreadLocal<Map<String, String>> PROPAGATED_HEADERS =
        new InheritableThreadLocal<>() {
            @Override
            protected Map<String, String> initialValue() {
                return Collections.emptyMap();
            }
        };

    /**
     * Thread-local storage for trace context.
     * Uses InheritableThreadLocal so child threads inherit the context.
     */
    private static final InheritableThreadLocal<TraceInfo> CONTEXT =
        new InheritableThreadLocal<>();

    /**
     * Get the current trace context.
     *
     * @return Current TraceInfo, or null if not set
     */
    public static TraceInfo get() {
        return CONTEXT.get();
    }

    /**
     * Set the current trace context.
     *
     * @param info TraceInfo to set as current context
     */
    public static void set(TraceInfo info) {
        CONTEXT.set(info);
    }

    /**
     * Clear the current trace context.
     */
    public static void clear() {
        CONTEXT.remove();
    }

    /**
     * Get the current trace ID, or null if no context.
     */
    public static String getTraceId() {
        TraceInfo info = get();
        return info != null ? info.getTraceId() : null;
    }

    /**
     * Get the current span ID, or null if no context.
     */
    public static String getSpanId() {
        TraceInfo info = get();
        return info != null ? info.getSpanId() : null;
    }

    /**
     * Get the current parent span ID, or null if no context or root span.
     */
    public static String getParentSpan() {
        TraceInfo info = get();
        return info != null ? info.getParentSpan() : null;
    }

    /**
     * Check if trace context is currently set.
     */
    public static boolean isSet() {
        return CONTEXT.get() != null;
    }

    public static List<String> getPropagateHeaderNames() {
        return PROPAGATE_HEADERS;
    }

    public static Map<String, String> getPropagatedHeaders() {
        return PROPAGATED_HEADERS.get();
    }

    public static void setPropagatedHeaders(Map<String, String> headers) {
        PROPAGATED_HEADERS.set(headers);
    }

    public static void clearPropagatedHeaders() {
        PROPAGATED_HEADERS.set(Collections.emptyMap());
    }

    /**
     * Check if a header name matches any prefix in the propagate headers allowlist.
     * Uses prefix matching: if PROPAGATE_HEADERS contains "x-audit", it will match
     * "x-audit", "x-audit-id", "x-audit-source", etc.
     *
     * @param name Header name to check
     * @return true if the name matches any prefix in the allowlist
     */
    public static boolean matchesPropagateHeader(String name) {
        if (PROPAGATE_HEADERS.isEmpty()) return false;
        String lower = name.toLowerCase();
        for (String prefix : PROPAGATE_HEADERS) {
            if (lower.startsWith(prefix)) return true;
        }
        return false;
    }

    /**
     * Wrap a Runnable to propagate trace context to another thread.
     *
     * <p>Use this when submitting tasks to ExecutorService or other async mechanisms
     * that may not inherit the thread context.
     *
     * @param task The task to wrap
     * @return Wrapped task that restores trace context on execution
     */
    public static Runnable wrap(Runnable task) {
        TraceInfo current = get();
        Map<String, String> currentHeaders = getPropagatedHeaders();
        return () -> {
            TraceInfo previous = get();
            Map<String, String> previousHeaders = getPropagatedHeaders();
            try {
                if (current != null) {
                    set(current);
                }
                if (!currentHeaders.isEmpty()) {
                    setPropagatedHeaders(currentHeaders);
                }
                task.run();
            } finally {
                if (previous != null) {
                    set(previous);
                } else {
                    clear();
                }
                if (!previousHeaders.isEmpty()) {
                    setPropagatedHeaders(previousHeaders);
                } else {
                    clearPropagatedHeaders();
                }
            }
        };
    }

    /**
     * Wrap a Callable to propagate trace context to another thread.
     *
     * <p>Use this when submitting tasks to ExecutorService or other async mechanisms
     * that may not inherit the thread context.
     *
     * @param task The task to wrap
     * @param <T> Return type of the callable
     * @return Wrapped task that restores trace context on execution
     */
    public static <T> Callable<T> wrap(Callable<T> task) {
        TraceInfo current = get();
        Map<String, String> currentHeaders = getPropagatedHeaders();
        return () -> {
            TraceInfo previous = get();
            Map<String, String> previousHeaders = getPropagatedHeaders();
            try {
                if (current != null) {
                    set(current);
                }
                if (!currentHeaders.isEmpty()) {
                    setPropagatedHeaders(currentHeaders);
                }
                return task.call();
            } finally {
                if (previous != null) {
                    set(previous);
                } else {
                    clear();
                }
                if (!previousHeaders.isEmpty()) {
                    setPropagatedHeaders(previousHeaders);
                } else {
                    clearPropagatedHeaders();
                }
            }
        };
    }

    // Private constructor to prevent instantiation
    private TraceContext() {
    }
}
