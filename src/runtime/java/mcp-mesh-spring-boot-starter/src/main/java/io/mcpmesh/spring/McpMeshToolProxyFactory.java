package io.mcpmesh.spring;

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
 * <p>When topology changes, proxies can be invalidated to force recreation
 * with updated endpoint information.
 */
public class McpMeshToolProxyFactory {

    private static final Logger log = LoggerFactory.getLogger(McpMeshToolProxyFactory.class);

    // Cache key: "endpoint:functionName" → proxy
    @SuppressWarnings("rawtypes")
    private final Map<String, McpMeshToolProxy> proxyCache = new ConcurrentHashMap<>();

    private final McpHttpClient mcpClient;

    public McpMeshToolProxyFactory() {
        this.mcpClient = new McpHttpClient();
    }

    public McpMeshToolProxyFactory(McpHttpClient mcpClient) {
        this.mcpClient = mcpClient;
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
     * <p>If a proxy already exists for this endpoint:function combination,
     * returns the cached instance. Otherwise creates a new proxy with the
     * specified return type for automatic deserialization.
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

        return proxyCache.computeIfAbsent(cacheKey, key -> {
            log.debug("Creating new proxy for {}:{} with returnType={}", endpoint, functionName, returnType);
            McpMeshToolProxy proxy = new McpMeshToolProxy(functionName, mcpClient, returnType);
            proxy.updateEndpoint(endpoint, functionName);
            return proxy;
        });
    }

    /**
     * Update an existing proxy's endpoint or create a new one.
     *
     * <p>This is useful when the same capability moves to a different agent.
     *
     * @param endpoint     The remote endpoint URL
     * @param functionName The function name
     * @return The updated or new proxy
     */
    public McpMeshTool updateOrCreateProxy(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);

        McpMeshToolProxy proxy = proxyCache.get(cacheKey);
        if (proxy != null) {
            proxy.updateEndpoint(endpoint, functionName);
            return proxy;
        }

        return getOrCreateProxy(endpoint, functionName);
    }

    /**
     * Invalidate a cached proxy.
     *
     * <p>Call this when topology changes and the proxy should be recreated.
     *
     * @param endpoint     The remote endpoint URL
     * @param functionName The function name
     */
    public void invalidateProxy(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);
        McpMeshToolProxy removed = proxyCache.remove(cacheKey);
        if (removed != null) {
            removed.markUnavailable();
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
    public void markUnavailable(String endpoint, String functionName) {
        String cacheKey = buildCacheKey(endpoint, functionName);
        McpMeshToolProxy proxy = proxyCache.get(cacheKey);
        if (proxy != null) {
            proxy.markUnavailable();
            log.debug("Marked proxy unavailable for {}:{}", endpoint, functionName);
        }
    }

    /**
     * Clear all cached proxies.
     *
     * <p>Call this on agent shutdown or major topology reset.
     */
    public void clearAll() {
        proxyCache.values().forEach(McpMeshToolProxy::markUnavailable);
        proxyCache.clear();
        log.info("Cleared all cached proxies");
    }

    /**
     * Get the number of cached proxies.
     */
    public int getCacheSize() {
        return proxyCache.size();
    }

    /**
     * Check if a proxy exists in the cache.
     */
    public boolean hasProxy(String endpoint, String functionName) {
        return proxyCache.containsKey(buildCacheKey(endpoint, functionName));
    }

    private String buildCacheKey(String endpoint, String functionName) {
        return endpoint + ":" + functionName;
    }
}
