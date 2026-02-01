package io.mcpmesh.spring.tracing;

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
        return () -> {
            TraceInfo previous = get();
            try {
                if (current != null) {
                    set(current);
                }
                task.run();
            } finally {
                if (previous != null) {
                    set(previous);
                } else {
                    clear();
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
        return () -> {
            TraceInfo previous = get();
            try {
                if (current != null) {
                    set(current);
                }
                return task.call();
            } finally {
                if (previous != null) {
                    set(previous);
                } else {
                    clear();
                }
            }
        };
    }

    // Private constructor to prevent instantiation
    private TraceContext() {
    }
}
