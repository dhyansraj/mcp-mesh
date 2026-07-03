package io.mcpmesh.spring;

import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Factory for creating and caching McpMeshTool proxies.
 *
 * <p>Proxies are cached by endpoint:functionName to allow reuse when the same
 * remote tool is used by multiple functions. This matches Python SDK behavior.
 *
 * <p>Within an endpoint:functionName, proxies are further split by the
 * <em>resolved return type</em> of the injection site. Two consumers of the
 * same remote tool that declare different type params — e.g.
 * {@code McpMeshTool<Object>} and {@code McpMeshTool<List<Object>>} — must NOT
 * share one proxy: a shared proxy would carry a single {@code returnType} set
 * by whichever consumer resolved first, so the same code would deserialize
 * differently from run to run (a real parallel-run nondeterminism bug). Keying
 * on the return type as well guarantees a consumer's declared type ALWAYS
 * governs its own calls' deserialization, regardless of resolution order.
 *
 * <p>When topology changes, proxies can be invalidated to force recreation
 * with updated endpoint information; topology operations act on ALL of a
 * tool's per-type proxies at once.
 */
public class McpMeshToolProxyFactory {

    private static final Logger log = LoggerFactory.getLogger(McpMeshToolProxyFactory.class);

    // Sub-key for the untyped/dynamic-parse variant. null (untyped) and a
    // literal Object.class target both deserialize dynamically and identically,
    // so they collapse to this single key (one proxy for the common untyped
    // case). Angle brackets guarantee it can never collide with a real
    // Type#getTypeName(), which always begins with a package/class identifier.
    private static final String DYNAMIC_TYPE_KEY = "<dynamic>";

    // Outer key: "endpoint:functionName" -> { returnType-key -> proxy }.
    @SuppressWarnings("rawtypes")
    private final Map<String, Map<String, McpMeshToolProxy>> proxyCache = new ConcurrentHashMap<>();

    private final McpHttpClient mcpClient;
    private volatile ExecutionTracer tracer;

    public McpMeshToolProxyFactory() {
        this.mcpClient = new McpHttpClient();
    }

    public McpMeshToolProxyFactory(McpHttpClient mcpClient) {
        this.mcpClient = mcpClient;
    }

    /**
     * Set the ExecutionTracer for all proxies (existing and future).
     */
    public void setTracer(ExecutionTracer tracer) {
        this.tracer = tracer;
        proxyCache.values().forEach(byType -> byType.values().forEach(p -> p.setTracer(tracer)));
    }

    /**
     * Get or create a proxy for the given endpoint and function.
     *
     * <p>If a proxy already exists for this endpoint:function combination,
     * returns the cached instance. Otherwise creates a new proxy.
     *
     * @param endpoint     The remote endpoint URL (e.g., "http://localhost:9001")
     * @param functionName The function name at the endpoint (e.g., "addition")
     * @return The proxy (cached or newly created)
     */
    @SuppressWarnings({"rawtypes", "unchecked"})
    public McpMeshTool getOrCreateProxy(String endpoint, String functionName) {
        return getOrCreateProxy(endpoint, functionName, null);
    }

    /**
     * Get or create a typed proxy for the given endpoint and function.
     *
     * <p>If a proxy already exists for this endpoint:function combination AND
     * the same resolved return type, returns the cached instance. Otherwise
     * creates a new proxy with the specified return type for automatic
     * deserialization.
     *
     * @param endpoint     The remote endpoint URL (e.g., "http://localhost:9001")
     * @param functionName The function name at the endpoint (e.g., "addition")
     * @param returnType   The expected return type (e.g., Integer.class, or a ParameterizedType)
     * @param <T>          The return type
     * @return The proxy (cached or newly created)
     */
    @SuppressWarnings({"rawtypes", "unchecked"})
    public <T> McpMeshTool<T> getOrCreateProxy(String endpoint, String functionName, Type returnType) {
        String cacheKey = buildCacheKey(endpoint, functionName);
        String typeKey = buildTypeKey(returnType);

        // Each distinct declared return type gets its OWN proxy, so its
        // deserialization is never influenced by another consumer of the same
        // tool that resolved first with a different type. The returnType is set
        // once at creation and never mutated cross-type.
        //
        // Retry guards a detach race: a concurrent invalidateProxy can remove
        // the inner map after computeIfAbsent captured it, which would orphan a
        // proxy inserted into the now-detached map (invisible to all future
        // fan-outs). Re-check that the inner map is still the one bound under
        // cacheKey; if not, another thread detached it — loop and re-bind.
        while (true) {
            Map<String, McpMeshToolProxy> byType = proxyCache.computeIfAbsent(
                cacheKey, k -> new ConcurrentHashMap<>());

            McpMeshToolProxy proxy = byType.computeIfAbsent(typeKey, key -> {
                log.debug("Creating new proxy for {}:{} with returnType={}", endpoint, functionName, returnType);
                McpMeshToolProxy newProxy = new McpMeshToolProxy(functionName, mcpClient, returnType);
                newProxy.updateEndpoint(endpoint, functionName);
                if (tracer != null) {
                    newProxy.setTracer(tracer);
                }
                return newProxy;
            });

            if (proxyCache.get(cacheKey) == byType) {
                return (McpMeshTool<T>) proxy;
            }
        }
    }

    /**
     * Update the endpoint of all existing proxies for this endpoint:function,
     * or create the untyped/dynamic proxy if none exist yet.
     *
     * <p>This is useful when the same capability moves to a different agent.
     *
     * <p>Contract: when multiple return-type variants exist, ALL are updated,
     * and the returned representative is chosen deterministically — the
     * untyped/dynamic variant if present, otherwise the variant with the
     * lexicographically-smallest type key. Never an arbitrary iteration-order
     * pick (which would reintroduce run-to-run nondeterminism).
     *
     * @param endpoint     The remote endpoint URL
     * @param functionName The function name
     * @return The updated or new proxy (deterministic representative)
     */
    @SuppressWarnings("rawtypes")
    public McpMeshTool updateOrCreateProxy(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);

        Map<String, McpMeshToolProxy> byType = proxyCache.get(cacheKey);
        if (byType != null && !byType.isEmpty()) {
            byType.values().forEach(p -> p.updateEndpoint(endpoint, functionName));
            return pickRepresentative(byType);
        }

        return getOrCreateProxy(endpoint, functionName);
    }

    /**
     * Deterministically choose one proxy from an endpoint:function's per-type
     * variants: the untyped/dynamic variant when present, else the variant with
     * the lexicographically-smallest type key.
     */
    @SuppressWarnings("rawtypes")
    private McpMeshToolProxy pickRepresentative(Map<String, McpMeshToolProxy> byType) {
        McpMeshToolProxy dynamic = byType.get(DYNAMIC_TYPE_KEY);
        if (dynamic != null) {
            return dynamic;
        }
        return byType.entrySet().stream()
            .min(Map.Entry.comparingByKey())
            .map(Map.Entry::getValue)
            .orElse(null);
    }

    /**
     * Invalidate a cached proxy.
     *
     * <p>Call this when topology changes and the proxy should be recreated.
     *
     * @param endpoint     The remote endpoint URL
     * @param functionName The function name
     */
    @SuppressWarnings("rawtypes")
    public void invalidateProxy(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);
        Map<String, McpMeshToolProxy> removed = proxyCache.remove(cacheKey);
        if (removed != null) {
            removed.values().forEach(McpMeshToolProxy::markUnavailable);
            log.debug("Invalidated proxy for {}:{}", endpoint, functionName);
        }
    }

    /**
     * Mark a proxy as unavailable without removing from cache.
     *
     * <p>The proxy remains cached but calls will fail until endpoint is updated.
     *
     * @param endpoint     The remote endpoint URL
     * @param functionName The function name
     */
    @SuppressWarnings("rawtypes")
    public void markUnavailable(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);
        Map<String, McpMeshToolProxy> byType = proxyCache.get(cacheKey);
        if (byType != null) {
            byType.values().forEach(McpMeshToolProxy::markUnavailable);
            log.debug("Marked proxy unavailable for {}:{}", endpoint, functionName);
        }
    }

    /**
     * Clear all cached proxies.
     *
     * <p>Call this on agent shutdown or major topology reset.
     */
    @SuppressWarnings("rawtypes")
    public void clearAll() {
        proxyCache.values().forEach(byType -> byType.values().forEach(McpMeshToolProxy::markUnavailable));
        proxyCache.clear();
        log.info("Cleared all cached proxies");
    }

    /**
     * Get the number of cached proxies (across all endpoint:function and
     * return-type variants).
     */
    public int getCacheSize() {
        return proxyCache.values().stream().mapToInt(Map::size).sum();
    }

    /**
     * Check if a proxy exists in the cache for this endpoint:function (any
     * return-type variant).
     */
    public boolean hasProxy(String endpoint, String functionName) {
        Map<String, McpMeshToolProxy> byType = proxyCache.get(buildCacheKey(endpoint, functionName));
        return byType != null && !byType.isEmpty();
    }

    private String buildCacheKey(String endpoint, String functionName) {
        return endpoint + ":" + functionName;
    }

    /**
     * Stable per-return-type cache sub-key. Distinct declared types map to
     * distinct keys, so each injection site's deserialization is isolated.
     * {@code Type#getTypeName()} is a faithful, stable rendering for Class and
     * ParameterizedType targets; two Types that render identically deserialize
     * identically, so sharing is correct in that case.
     *
     * <p>{@code null} (untyped) and {@code Object.class} both use the dynamic
     * parse and deserialize byte-identically, so they collapse to a single
     * {@link #DYNAMIC_TYPE_KEY} — no duplicate proxy for the common untyped case.
     */
    private String buildTypeKey(Type returnType) {
        if (returnType == null || returnType == Object.class) {
            return DYNAMIC_TYPE_KEY;
        }
        return returnType.getTypeName();
    }
}
