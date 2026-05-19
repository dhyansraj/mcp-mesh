package io.mcpmesh;

import io.mcpmesh.core.MeshException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Convenience helpers for the MeshJob event-injection primitive
 * (issue #1032). Static-only utility class — mirror of:
 * <ul>
 *   <li>Python {@code mesh.jobs} module ({@code mesh.jobs.post_event})</li>
 *   <li>TypeScript {@code mesh.jobs} namespace ({@code mesh.jobs.postEvent})</li>
 * </ul>
 *
 * <p>The primary surface is {@link #postEvent(String, String, Map)} —
 * a fire-and-forget helper that lets tool bodies post events to running
 * jobs without holding a {@link JobProxy} reference. Constructs (or
 * looks up from the process-wide LRU cache) a proxy bound to the
 * current agent's registry URL and forwards the call.
 *
 * <p>The {@link JobController#recvEvent(java.util.List, java.time.Duration)}
 * and {@link JobProxy#sendEvent(String, Map)} methods are the lower-level
 * primitives; this class is the small layer on top that takes care of
 * registry URL discovery + proxy caching.
 */
public final class MeshJobs {

    private static final Logger log = LoggerFactory.getLogger(MeshJobs.class);

    /**
     * Default cap for the process-wide {@code JobProxy} LRU cache.
     * Matches the Python/TS defaults exactly so cross-runtime tests
     * exercise identical eviction behavior. Override via the
     * {@code MCP_MESH_JOBPROXY_CACHE_MAX} environment variable.
     */
    private static final int PROXY_CACHE_DEFAULT_MAX = 256;

    /**
     * Process-wide LRU cache of {@link JobProxy} instances keyed by
     * {@code (registryUrl, jobId)}.
     *
     * <p>{@code postEvent} would otherwise construct a fresh proxy on
     * every call. Each proxy wraps a Rust {@code reqwest::Client} with
     * its own connection pool, so a steady-state sender firing
     * {@code postEvent} in a hot loop would force a fresh TCP/TLS
     * handshake against the registry on every call. Cache by
     * {@code (registryUrl, jobId)} for the process lifetime.
     *
     * <p>If a job is cancelled and re-submitted with the same id (rare
     * in practice), the cached proxy would just see a
     * {@link JobTerminalException} on its next sendEvent call — the
     * correct surface — and the caller can retry.
     *
     * <p><b>Implementation</b>: {@link LinkedHashMap} with
     * {@code accessOrder=true} for O(1) LRU semantics. Wrapped in
     * {@code synchronized} blocks because {@code LinkedHashMap} is NOT
     * thread-safe (even read access mutates the recency order under
     * access-order mode). The cache is a process resource — the
     * synchronisation overhead is negligible compared to the
     * eliminated FFI handshake cost.
     */
    private static final Object cacheLock = new Object();
    private static final LinkedHashMap<CacheKey, JobProxy> proxyCache =
        new LinkedHashMap<CacheKey, JobProxy>(16, 0.75f, /*accessOrder=*/true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<CacheKey, JobProxy> eldest) {
                // Bound the cache so a long-lived sender posting events
                // to many distinct jobs can't grow it without limit.
                // Closing the evicted proxy frees the underlying FFI
                // handle's reqwest::Client connection pool — without
                // close(), the native handle would leak until GC ran
                // (and GC of off-heap-backed objects is unpredictable).
                int max = proxyCacheMax();
                if (size() > max) {
                    try {
                        eldest.getValue().close();
                    } catch (RuntimeException e) {
                        log.warn("Failed to close evicted JobProxy for {}: {}",
                            eldest.getKey(), e.getMessage());
                    }
                    return true;
                }
                return false;
            }
        };

    private MeshJobs() {
        // Utility class — no instances.
    }

    /**
     * Post an event to a running job by ID. Convenience helper for tool
     * bodies that hold a {@code jobId} (e.g. from a request body, a
     * token lookup, or a stashed reference) but do NOT have a
     * {@link JobProxy} reference in scope.
     *
     * <p>The registry URL is discovered from the
     * {@code MCP_MESH_REGISTRY_URL} environment variable — the
     * configuration pipeline writes this on agent startup, matching
     * the convention used by every other job-substrate code path.
     *
     * <p>Cached proxies: this method caches one {@link JobProxy}
     * instance per {@code (registryUrl, jobId)} pair for the process
     * lifetime, eliminating the per-call FFI handshake cost. Override
     * the cap via {@code MCP_MESH_JOBPROXY_CACHE_MAX}.
     *
     * @param jobId     Target job's server-assigned ID
     * @param eventType Event-type tag (e.g. {@code "user_input"},
     *                  {@code "extend_deadline"})
     * @param payload   Optional payload; {@code null} normalises to
     *                  an empty JSON object {@code {}}
     * @return Receipt map with {@code job_id, seq, created_at}
     * @throws JobNotFoundException if the registry doesn't know the job
     * @throws JobTerminalException if the job is already terminal
     * @throws MeshException        for transport errors or missing
     *                              {@code MCP_MESH_REGISTRY_URL}
     */
    public static Map<String, Object> postEvent(
            String jobId, String eventType, Map<String, Object> payload) {
        if (jobId == null || jobId.isEmpty()) {
            throw new IllegalArgumentException("jobId is required");
        }
        if (eventType == null || eventType.isEmpty()) {
            throw new IllegalArgumentException("eventType is required");
        }
        String registryUrl = resolveRegistryUrl();
        JobProxy proxy = getOrCreateProxy(registryUrl, jobId);
        return proxy.sendEvent(eventType, payload);
    }

    /**
     * Subscribe to events posted to a running job by ID.
     *
     * <p>Returns a {@link EventSubscription} — a long-lived blocking
     * iterator over the job's event log. Each call manages its own
     * cursor, so multiple subscribers can observe the same job's
     * events independently without affecting the producer's
     * {@code recvEvent} consumption (the producer's cursor is
     * per-controller; this observer's cursor is per-subscription).
     *
     * <p>The iterator runs indefinitely until the caller breaks out
     * of the for-loop, calls {@link EventSubscription#close()}, or
     * the underlying registry raises {@link JobNotFoundException}.
     * There is no automatic terminal-state detection — use a
     * synthetic event type (e.g. {@code {"type":"ended"}}) posted by
     * your application to signal iteration end.
     *
     * <p>Mirrors:
     * <ul>
     *   <li>Python {@code mesh.jobs.subscribe_events(job_id, types, after, long_poll_secs)}</li>
     *   <li>TypeScript {@code mesh.jobs.subscribeEvents(jobId, options)}</li>
     * </ul>
     *
     * <p>The registry URL is discovered from {@code MCP_MESH_REGISTRY_URL}
     * (same convention as {@link #postEvent(String, String, Map)}).
     * Cached proxies: this method reuses the process-wide LRU cache,
     * so a subscriber and a {@code postEvent} caller targeting the
     * same job share one underlying {@link JobProxy}.
     *
     * <p>Recommended usage (try-with-resources):
     * <pre>{@code
     * try (EventSubscription sub = MeshJobs.subscribeEvents(jobId,
     *         SubscribeOptions.builder().types(List.of("progress")).build())) {
     *     while (sub.hasNext()) {
     *         Map<String, Object> event = sub.next();
     *         downstream.publish(event);
     *         if ("result".equals(event.get("type"))) break;
     *     }
     * }
     * }</pre>
     *
     * @param jobId   Target job's server-assigned ID
     * @param options Filter / cursor / long-poll knobs; use
     *                {@link SubscribeOptions#defaults()} or
     *                {@link #subscribeEvents(String)} for defaults
     * @return A blocking iterator over the job's events; caller MUST
     *         {@link EventSubscription#close()} (or try-with-resources)
     *         when done
     * @throws JobNotFoundException if the job has been reaped from
     *                              the registry (only raised when the
     *                              caller advances the iterator)
     * @throws MeshException        for transport errors or missing
     *                              {@code MCP_MESH_REGISTRY_URL}
     */
    public static EventSubscription subscribeEvents(String jobId, SubscribeOptions options) {
        if (jobId == null || jobId.isEmpty()) {
            throw new IllegalArgumentException("jobId is required");
        }
        if (options == null) {
            options = SubscribeOptions.defaults();
        }
        String registryUrl = resolveRegistryUrl();
        JobProxy proxy = getOrCreateProxy(registryUrl, jobId);
        return new EventSubscription(proxy, options);
    }

    /**
     * Convenience overload — {@link #subscribeEvents(String, SubscribeOptions)}
     * with {@link SubscribeOptions#defaults()}.
     */
    public static EventSubscription subscribeEvents(String jobId) {
        return subscribeEvents(jobId, SubscribeOptions.defaults());
    }

    /**
     * Discover the registry base URL the running agent is bound to.
     * Mirrors the {@code MCP_MESH_REGISTRY_URL} convention used by
     * Python's {@code _resolve_registry_url} and TypeScript's
     * {@code resolveRegistryUrl}.
     */
    static String resolveRegistryUrl() {
        String url = System.getenv("MCP_MESH_REGISTRY_URL");
        if (url == null || url.isEmpty()) {
            throw new MeshException(
                "MeshJobs.postEvent: MCP_MESH_REGISTRY_URL is not set; "
                    + "cannot resolve registry base URL. Ensure the calling "
                    + "process is running inside a mesh agent.");
        }
        return url;
    }

    /**
     * Resolve the LRU cache cap from {@code MCP_MESH_JOBPROXY_CACHE_MAX}
     * (env override; falls back to {@link #PROXY_CACHE_DEFAULT_MAX}).
     * Invalid / non-positive values fall back to the default so a
     * typo'd env doesn't silently disable the cache.
     */
    static int proxyCacheMax() {
        String raw = System.getenv("MCP_MESH_JOBPROXY_CACHE_MAX");
        if (raw == null || raw.isEmpty()) {
            return PROXY_CACHE_DEFAULT_MAX;
        }
        try {
            int value = Integer.parseInt(raw);
            return value > 0 ? value : PROXY_CACHE_DEFAULT_MAX;
        } catch (NumberFormatException e) {
            return PROXY_CACHE_DEFAULT_MAX;
        }
    }

    /**
     * Return a process-cached {@link JobProxy} for the given
     * {@code (registryUrl, jobId)} pair, constructing one on first
     * miss. Hit bumps the entry to the most-recent end (LRU); misses
     * on a full cache evict the least-recent entry via
     * {@code removeEldestEntry}.
     *
     * <p>Package-private for tests.
     */
    static JobProxy getOrCreateProxy(String registryUrl, String jobId) {
        CacheKey key = new CacheKey(registryUrl, jobId);
        synchronized (cacheLock) {
            JobProxy cached = proxyCache.get(key);
            if (cached != null) {
                return cached;
            }
            JobProxy proxy = JobProxy.open(jobId, registryUrl);
            // put() will trigger removeEldestEntry if we're over cap.
            proxyCache.put(key, proxy);
            return proxy;
        }
    }

    /**
     * Drop all cached proxies. Test-only — closes each evicted proxy
     * so a subsequent test starts from a clean cache state.
     */
    static void clearProxyCacheForTest() {
        synchronized (cacheLock) {
            for (JobProxy p : proxyCache.values()) {
                try {
                    p.close();
                } catch (RuntimeException ignored) {
                    // Test cleanup — swallow.
                }
            }
            proxyCache.clear();
        }
    }

    /**
     * Current cache size — test-only.
     */
    static int cacheSizeForTest() {
        synchronized (cacheLock) {
            return proxyCache.size();
        }
    }

    /**
     * Composite cache key. {@code record} keeps {@code equals}/
     * {@code hashCode} implementations honest and is non-null-safe by
     * construction — both fields are validated in
     * {@link #postEvent(String, String, Map)} before this is constructed.
     */
    record CacheKey(String registryUrl, String jobId) {}
}
