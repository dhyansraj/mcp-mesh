package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshToolCallException;
import io.mcpmesh.types.MeshToolUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Proxy implementation for remote mesh tools.
 *
 * <p>Handles communication with remote agents via MCP protocol.
 * The proxy is thread-safe and supports dynamic endpoint updates.
 */
public class McpMeshToolProxy implements McpMeshTool {

    private static final Logger log = LoggerFactory.getLogger(McpMeshToolProxy.class);

    private final String capability;
    private final McpHttpClient mcpClient;
    private final AtomicReference<EndpointInfo> endpointRef = new AtomicReference<>();

    public McpMeshToolProxy(String capability) {
        this.capability = capability;
        this.mcpClient = new McpHttpClient();
    }

    public McpMeshToolProxy(String capability, McpHttpClient mcpClient) {
        this.capability = capability;
        this.mcpClient = mcpClient;
    }

    void updateEndpoint(String endpoint, String functionName) {
        endpointRef.set(new EndpointInfo(endpoint, functionName, true));
    }

    void markUnavailable() {
        EndpointInfo current = endpointRef.get();
        if (current != null) {
            endpointRef.set(new EndpointInfo(current.endpoint(), current.functionName(), false));
        }
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> T call() {
        return call(Map.of());
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> T call(Map<String, Object> params) {
        EndpointInfo info = endpointRef.get();
        if (info == null || !info.available()) {
            throw new MeshToolUnavailableException(capability);
        }

        log.debug("Calling tool {} at {} with params: {}", info.functionName(), info.endpoint(), params);
        return mcpClient.callTool(info.endpoint(), info.functionName(), params);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> T call(Object... keyValuePairs) {
        if (keyValuePairs.length % 2 != 0) {
            throw new IllegalArgumentException("keyValuePairs must have even length");
        }

        Map<String, Object> params = new LinkedHashMap<>();
        for (int i = 0; i < keyValuePairs.length; i += 2) {
            String key = (String) keyValuePairs[i];
            Object value = keyValuePairs[i + 1];
            params.put(key, value);
        }

        return call(params);
    }

    @Override
    public <T> CompletableFuture<T> callAsync() {
        return CompletableFuture.supplyAsync(this::call);
    }

    @Override
    public <T> CompletableFuture<T> callAsync(Map<String, Object> params) {
        return CompletableFuture.supplyAsync(() -> call(params));
    }

    @Override
    public <T> CompletableFuture<T> callAsync(Object... keyValuePairs) {
        return CompletableFuture.supplyAsync(() -> call(keyValuePairs));
    }

    @Override
    public String getCapability() {
        return capability;
    }

    @Override
    public String getEndpoint() {
        EndpointInfo info = endpointRef.get();
        return info != null ? info.endpoint() : null;
    }

    @Override
    public String getFunctionName() {
        EndpointInfo info = endpointRef.get();
        return info != null ? info.functionName() : null;
    }

    @Override
    public boolean isAvailable() {
        EndpointInfo info = endpointRef.get();
        return info != null && info.available();
    }

    private record EndpointInfo(String endpoint, String functionName, boolean available) {}
}
