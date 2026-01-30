package io.mcpmesh.types;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Proxy interface for calling remote mesh tools.
 *
 * <p>Instances of this interface are injected into {@code @MeshTool} methods
 * as resolved dependencies. The proxy handles communication with remote agents
 * via MCP protocol.
 *
 * <h2>Usage Examples</h2>
 *
 * <h3>No Parameters</h3>
 * <pre>{@code
 * String today = dateService.call();
 * }</pre>
 *
 * <h3>With Map (Java 9+)</h3>
 * <pre>{@code
 * String today = dateService.call(Map.of(
 *     "format", "iso",
 *     "timezone", "UTC"
 * ));
 * }</pre>
 *
 * <h3>Varargs Shorthand</h3>
 * <pre>{@code
 * String today = dateService.call(
 *     "format", "iso",
 *     "timezone", "UTC"
 * );
 * }</pre>
 *
 * <h3>Typed Response</h3>
 * <pre>{@code
 * WeatherData weather = weatherService.call(Map.of("city", "London"));
 * }</pre>
 *
 * <h3>Async Call</h3>
 * <pre>{@code
 * CompletableFuture<WeatherData> future = weatherService.callAsync(
 *     Map.of("city", "London")
 * );
 * future.thenAccept(weather -> System.out.println(weather.temperature()));
 * }</pre>
 *
 * <h3>Graceful Degradation</h3>
 * <pre>{@code
 * if (dateService.isAvailable()) {
 *     String today = dateService.call();
 * } else {
 *     // Fallback to local implementation
 *     String today = LocalDate.now().toString();
 * }
 * }</pre>
 *
 * @see io.mcpmesh.MeshTool#dependencies()
 * @see io.mcpmesh.Selector
 */
public interface McpMeshTool {

    // =========================================================================
    // Synchronous Calls
    // =========================================================================

    /**
     * Call the remote tool with no parameters.
     *
     * @param <T> The expected return type
     * @return The tool's response
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    <T> T call();

    /**
     * Call the remote tool with parameters as a Map.
     *
     * @param <T>    The expected return type
     * @param params Parameters to pass to the tool
     * @return The tool's response
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    <T> T call(Map<String, Object> params);

    /**
     * Call the remote tool with varargs key-value pairs.
     *
     * <p>Example: {@code call("key1", val1, "key2", val2)}
     *
     * @param <T>           The expected return type
     * @param keyValuePairs Alternating key-value pairs
     * @return The tool's response
     * @throws IllegalArgumentException if odd number of arguments
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    <T> T call(Object... keyValuePairs);

    // =========================================================================
    // Asynchronous Calls
    // =========================================================================

    /**
     * Asynchronously call the remote tool with no parameters.
     *
     * @param <T> The expected return type
     * @return A future that completes with the tool's response
     */
    <T> CompletableFuture<T> callAsync();

    /**
     * Asynchronously call the remote tool with parameters.
     *
     * @param <T>    The expected return type
     * @param params Parameters to pass to the tool
     * @return A future that completes with the tool's response
     */
    <T> CompletableFuture<T> callAsync(Map<String, Object> params);

    /**
     * Asynchronously call the remote tool with varargs key-value pairs.
     *
     * @param <T>           The expected return type
     * @param keyValuePairs Alternating key-value pairs
     * @return A future that completes with the tool's response
     */
    <T> CompletableFuture<T> callAsync(Object... keyValuePairs);

    // =========================================================================
    // Metadata
    // =========================================================================

    /**
     * Get the capability name this proxy is bound to.
     *
     * @return The capability name
     */
    String getCapability();

    /**
     * Get the remote endpoint URL.
     *
     * @return The endpoint URL, or null if not connected
     */
    String getEndpoint();

    /**
     * Get the function/tool name at the remote endpoint.
     *
     * @return The function name
     */
    String getFunctionName();

    /**
     * Check if the proxy is connected to an available tool.
     *
     * <p>Use this for graceful degradation when dependencies are optional.
     *
     * @return true if the tool is available, false otherwise
     */
    boolean isAvailable();
}
