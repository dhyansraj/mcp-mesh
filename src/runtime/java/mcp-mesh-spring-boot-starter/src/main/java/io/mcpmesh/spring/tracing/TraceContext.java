package io.mcpmesh.spring.tracing;

import io.mcpmesh.JobContext;
import io.mcpmesh.core.MeshCoreBridge;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.function.Supplier;

/**
 * Thread-safe trace context storage using ThreadLocal.
 *
 * <p>For async operations (CompletableFuture, @Async, etc.), use the
 * {@link #wrap(Runnable)} or {@link #wrap(Callable)} methods to propagate context.
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

    /** Pre-built CSV of propagate header allowlist entries for Rust core calls. */
    private static final String PROPAGATE_HEADERS_CSV;

    static {
        String envVal = System.getenv("MCP_MESH_PROPAGATE_HEADERS");
        List<String> names = new ArrayList<>();
        if (envVal != null && !envVal.trim().isEmpty()) {
            for (String name : envVal.split(",")) {
                String trimmed = name.trim();
                if (!trimmed.isEmpty()) {
                    names.add(trimmed.toLowerCase());
                }
            }
        }
        // Always propagate mesh infrastructure headers
        if (!names.contains("x-mesh-timeout")) {
            names.add("x-mesh-timeout");
        }
        // Phase B MeshJob substrate: x-mesh-job-id is captured here so the
        // inbound MeshToolWrapper can dispatch task=true tools through the
        // job pipeline (build a JobController + bind both Java/native
        // contexts). Adding it to the propagate list also means outbound
        // calls forward it to downstream task=true tools — matching the
        // Python / TypeScript propagation behavior.
        if (!names.contains("x-mesh-job-id")) {
            names.add("x-mesh-job-id");
        }
        // Issue #1263: the calling job's identity rides a DEDICATED carrier —
        // x-mesh-calling-job-id + x-mesh-calling-claim-epoch — kept strictly
        // separate from the push-dispatch protocol pair (x-mesh-job-id /
        // x-mesh-claim-epoch). Seeding the protocol pair on an outbound call
        // would make a nested same-instance task=true call self-dispatch as
        // the CALLER's job (owner + epoch match) and auto-complete it with the
        // wrong result — see MeshToolWrapper.invokeInternal's dispatch gate.
        // Both the inbound capture (TracingFilter) and outbound extra-header
        // filtering key off this allowlist, so the carrier pair must be present
        // for the provider-side MeshCallContext accessor to observe it.
        if (!names.contains("x-mesh-calling-job-id")) {
            names.add("x-mesh-calling-job-id");
        }
        if (!names.contains("x-mesh-calling-claim-epoch")) {
            names.add("x-mesh-calling-claim-epoch");
        }
        PROPAGATE_HEADERS = Collections.unmodifiableList(names);
        PROPAGATE_HEADERS_CSV = String.join(",", PROPAGATE_HEADERS);
    }

    static final ThreadLocal<Map<String, String>> PROPAGATED_HEADERS =
        ThreadLocal.withInitial(Collections::emptyMap);

    /**
     * Thread-local sink for LLM token-usage metadata produced by a {@code @MeshLlm}
     * agentic loop. Mirrors the Python {@code _llm_metadata} contextvar: the
     * {@code MeshLlmAgentProxy} accumulates per-iteration usage and writes the totals
     * here; {@code ExecutionTracer.endSpan} reads and clears it when finalizing the
     * consumer span so the dashboard can attribute tokens to that span.
     */
    private static final ThreadLocal<LlmMetadata> LLM_METADATA = new ThreadLocal<>();

    /** Accumulated LLM token-usage metadata for the active consumer span. */
    public record LlmMetadata(String provider, String model, long inputTokens, long outputTokens) {}

    /**
     * Thread-local storage for trace context.
     * Use {@link #wrap(Runnable)} or {@link #wrap(Callable)} for async propagation.
     */
    private static final ThreadLocal<TraceInfo> CONTEXT = new ThreadLocal<>();

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

    /** Issue #1263: dedicated calling-job identity carrier header names. */
    public static final String CALLING_JOB_ID_HEADER = "x-mesh-calling-job-id";
    public static final String CALLING_CLAIM_EPOCH_HEADER = "x-mesh-calling-claim-epoch";

    /**
     * Issue #1263: the calling job's identity headers, derived from the active
     * {@link JobContext} on this thread. Returns {@code x-mesh-calling-job-id}
     * (when a job is in scope with a non-empty id) plus
     * {@code x-mesh-calling-claim-epoch} (only when the snapshot carries a
     * non-null claim generation — a null epoch seeds just the id). Empty when no
     * job is active.
     *
     * <p>Deliberately a DEDICATED carrier, NOT the push-dispatch protocol pair
     * ({@code x-mesh-job-id} / {@code x-mesh-claim-epoch}): seeding the protocol
     * pair on an outbound call would make a nested same-instance
     * {@code task=true} call self-dispatch as the caller's job and auto-complete
     * it — see {@code MeshToolWrapper.invokeInternal}'s dispatch gate.
     */
    public static Map<String, String> callingJobHeaders() {
        JobContext.Snapshot snap = JobContext.current();
        if (snap == null || snap.jobId == null || snap.jobId.isEmpty()) {
            return Collections.emptyMap();
        }
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put(CALLING_JOB_ID_HEADER, snap.jobId);
        if (snap.claimEpoch != null) {
            headers.put(CALLING_CLAIM_EPOCH_HEADER, String.valueOf(snap.claimEpoch));
        }
        return headers;
    }

    /**
     * Issue #1263: overlay the active job's calling-identity onto an outbound
     * header map. When a job is in scope, the pair is REPLACED atomically — any
     * inherited calling-* pair is removed first so a stale foreign epoch can
     * never ride along with a fresh id (both or none, from ONE snapshot). When
     * no job is active this is a no-op, so an inherited calling-* pair
     * propagates transitively through non-job intermediaries unchanged.
     *
     * <p>Called by {@code McpHttpClient} on every downstream tool call so a
     * provider can fence out-of-epoch writes via
     * {@code MeshCallContext.callingJob()} without the caller threading identity
     * through the payload.
     */
    public static void applyCallingJobIdentity(Map<String, String> headers) {
        Map<String, String> identity = callingJobHeaders();
        if (identity.isEmpty()) {
            return;
        }
        headers.remove(CALLING_JOB_ID_HEADER);
        headers.remove(CALLING_CLAIM_EPOCH_HEADER);
        headers.putAll(identity);
    }

    /**
     * Publish accumulated LLM token-usage metadata for the active consumer span.
     *
     * <p>Called by {@code MeshLlmAgentProxy} after the agentic loop completes; read and
     * cleared by {@code ExecutionTracer.endSpan}. Mirrors Python's {@code set_llm_metadata}.
     */
    public static void setLlmMetadata(String provider, String model, long inputTokens, long outputTokens) {
        LLM_METADATA.set(new LlmMetadata(provider, model, inputTokens, outputTokens));
    }

    /** Get the current LLM token-usage metadata, or null if none was set on this thread. */
    public static LlmMetadata getLlmMetadata() {
        return LLM_METADATA.get();
    }

    /** Clear the current LLM token-usage metadata. */
    public static void clearLlmMetadata() {
        LLM_METADATA.remove();
    }

    /**
     * Check if a header name matches the propagate headers allowlist.
     *
     * <p>Each allowlist entry is either an exact match (plain token) or a
     * prefix match (trailing {@code *}). Matching is case-insensitive.
     * <ul>
     *   <li>{@code authorization} matches only {@code authorization}.</li>
     *   <li>{@code x-trace-*} matches {@code x-trace-id}, {@code x-trace-parent}, etc.</li>
     * </ul>
     *
     * <p>Delegates to Rust core for consistent cross-SDK behavior.
     *
     * @param name Header name to check
     * @return true if the name matches any entry in the allowlist
     */
    public static boolean matchesPropagateHeader(String name) {
        if (PROPAGATE_HEADERS.isEmpty()) return false;
        return MeshCoreBridge.matchesPropagateHeader(name, PROPAGATE_HEADERS_CSV);
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

    /**
     * Wrap a Supplier to propagate trace context to another thread.
     *
     * <p>Use this with {@code CompletableFuture.supplyAsync(TraceContext.wrapSupplier(supplier))}
     * to ensure trace context is available in the async task.
     *
     * @param supplier The supplier to wrap
     * @param <T> Return type of the supplier
     * @return Wrapped supplier that restores trace context on execution
     */
    public static <T> Supplier<T> wrapSupplier(Supplier<T> supplier) {
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
                return supplier.get();
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
