package io.mcpmesh.spring;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshToolCallException;
import io.mcpmesh.types.MeshToolUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Proxy implementation for remote mesh tools.
 *
 * <p>Handles communication with remote agents via MCP protocol.
 * The proxy is thread-safe and supports dynamic endpoint updates.
 *
 * <p>The generic type parameter T specifies the expected return type
 * from the remote tool. The proxy uses this type for automatic
 * deserialization of MCP responses.
 *
 * @param <T> The expected return type from the tool
 */
public class McpMeshToolProxy<T> implements McpMeshTool<T> {

    private static final Logger log = LoggerFactory.getLogger(McpMeshToolProxy.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final String capability;
    private final McpHttpClient mcpClient;
    private final Type returnType;
    private final AtomicReference<EndpointInfo> endpointRef = new AtomicReference<>();

    public McpMeshToolProxy(String capability) {
        this(capability, new McpHttpClient(), null);
    }

    public McpMeshToolProxy(String capability, McpHttpClient mcpClient) {
        this(capability, mcpClient, null);
    }

    public McpMeshToolProxy(String capability, Type returnType) {
        this(capability, new McpHttpClient(), returnType);
    }

    public McpMeshToolProxy(String capability, McpHttpClient mcpClient, Type returnType) {
        this.capability = capability;
        this.mcpClient = mcpClient;
        this.returnType = returnType;
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
    public T call() {
        return call(Map.of());
    }

    @Override
    public T call(Map<String, Object> params) {
        EndpointInfo info = endpointRef.get();
        if (info == null || !info.available()) {
            throw new MeshToolUnavailableException(capability);
        }

        log.debug("Calling tool {} at {} with params: {}", info.functionName(), info.endpoint(), params);
        return mcpClient.callTool(info.endpoint(), info.functionName(), params, returnType);
    }

    @Override
    public T call(Object... args) {
        if (args.length == 0) {
            return call(Map.of());
        }

        // Single non-String argument → treat as params object (record/POJO)
        if (args.length == 1 && !(args[0] instanceof String)) {
            Map<String, Object> params = OBJECT_MAPPER.convertValue(
                args[0],
                new TypeReference<Map<String, Object>>() {}
            );
            return call(params);
        }

        // Otherwise, treat as key-value pairs
        if (args.length % 2 != 0) {
            throw new IllegalArgumentException(
                "Expected key-value pairs (even number of args) or a single params object"
            );
        }

        Map<String, Object> params = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i += 2) {
            String key = (String) args[i];
            Object value = args[i + 1];
            params.put(key, value);
        }

        return call(params);
    }

    @Override
    public CompletableFuture<T> callAsync() {
        return CompletableFuture.supplyAsync(this::call);
    }

    @Override
    public CompletableFuture<T> callAsync(Map<String, Object> params) {
        return CompletableFuture.supplyAsync(() -> call(params));
    }

    @Override
    public CompletableFuture<T> callAsync(Object... args) {
        return CompletableFuture.supplyAsync(() -> call(args));
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
