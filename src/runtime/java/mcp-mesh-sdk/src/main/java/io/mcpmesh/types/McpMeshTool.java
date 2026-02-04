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
 * <h2>Type Parameter</h2>
 * <p>The type parameter {@code T} specifies the expected return type from the tool.
 * The SDK will automatically deserialize MCP responses to this type.
 *
 * <h2>Usage Examples</h2>
 *
 * <h3>Primitive Types</h3>
 * <pre>{@code
 * McpMeshTool<Integer> calculator;
 * int sum = calculator.call(Map.of("a", 5, "b", 3));  // Returns Integer
 * }</pre>
 *
 * <h3>With Map (Java 9+)</h3>
 * <pre>{@code
 * McpMeshTool<String> dateService;
 * String today = dateService.call(Map.of(
 *     "format", "iso",
 *     "timezone", "UTC"
 * ));
 * }</pre>
 *
 * <h3>Complex Types (Records/POJOs)</h3>
 * <pre>{@code
 * McpMeshTool<Employee> employeeService;
 * Employee emp = employeeService.call(Map.of("id", 123));
 *
 * // With records
 * record WeatherData(double temp, String condition) {}
 * McpMeshTool<WeatherData> weatherService;
 * WeatherData weather = weatherService.call(Map.of("city", "London"));
 * }</pre>
 *
 * <h3>Object as Parameters (Records/POJOs)</h3>
 * <p>Instead of manually building a Map, pass a record or POJO directly:
 * <pre>{@code
 * // Define a params record (or use the domain object)
 * record CreateEmployeeParams(String firstName, String lastName, String dept) {}
 *
 * McpMeshTool<Employee> createEmployeeTool;
 * Employee created = createEmployeeTool.call(
 *     new CreateEmployeeParams("Alice", "Smith", "Engineering")
 * );
 *
 * // Or with an existing domain object
 * Employee template = new Employee(0, "Bob", "Jones", "Sales", 0.0);
 * Employee created = createEmployeeTool.call(template);
 * }</pre>
 *
 * <h3>Collections</h3>
 * <pre>{@code
 * McpMeshTool<List<Employee>> employeeListService;
 * List<Employee> employees = employeeListService.call(Map.of("dept", "eng"));
 * }</pre>
 *
 * <h3>Async Call</h3>
 * <pre>{@code
 * McpMeshTool<WeatherData> weatherService;
 * CompletableFuture<WeatherData> future = weatherService.callAsync(
 *     Map.of("city", "London")
 * );
 * future.thenAccept(weather -> System.out.println(weather.temp()));
 * }</pre>
 *
 * <h3>Graceful Degradation</h3>
 * <pre>{@code
 * McpMeshTool<String> dateService;
 * if (dateService.isAvailable()) {
 *     String today = dateService.call();
 * } else {
 *     // Fallback to local implementation
 *     String today = LocalDate.now().toString();
 * }
 * }</pre>
 *
 * @param <T> The expected return type from the tool
 * @see io.mcpmesh.MeshTool#dependencies()
 * @see io.mcpmesh.Selector
 */
public interface McpMeshTool<T> {

    // =========================================================================
    // Synchronous Calls
    // =========================================================================

    /**
     * Call the remote tool with no parameters.
     *
     * @return The tool's response, deserialized to type T
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    T call();

    /**
     * Call the remote tool with parameters as a Map.
     *
     * @param params Parameters to pass to the tool
     * @return The tool's response, deserialized to type T
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    T call(Map<String, Object> params);

    /**
     * Call the remote tool with flexible argument handling.
     *
     * <p>This method intelligently handles different argument patterns:
     *
     * <h4>Single object (record/POJO) - converted to parameters:</h4>
     * <pre>{@code
     * record AddParams(int a, int b) {}
     * calculator.call(new AddParams(5, 3));  // → {a: 5, b: 3}
     *
     * Employee emp = new Employee(1, "Alice", "Smith", "Eng", 100000);
     * employeeTool.call(emp);  // → {id: 1, firstName: "Alice", ...}
     * }</pre>
     *
     * <h4>Key-value pairs:</h4>
     * <pre>{@code
     * calculator.call("a", 5, "b", 3);  // → {a: 5, b: 3}
     * employeeTool.call("id", 123);     // → {id: 123}
     * }</pre>
     *
     * @param args Either a single params object (record/POJO) or alternating key-value pairs
     * @return The tool's response, deserialized to type T
     * @throws IllegalArgumentException if key-value pairs have odd length
     * @throws MeshToolUnavailableException if the tool is not available
     * @throws MeshToolCallException if the call fails
     */
    T call(Object... args);

    // =========================================================================
    // Asynchronous Calls
    // =========================================================================

    /**
     * Asynchronously call the remote tool with no parameters.
     *
     * @return A future that completes with the tool's response, deserialized to type T
     */
    CompletableFuture<T> callAsync();

    /**
     * Asynchronously call the remote tool with parameters.
     *
     * @param params Parameters to pass to the tool
     * @return A future that completes with the tool's response, deserialized to type T
     */
    CompletableFuture<T> callAsync(Map<String, Object> params);

    /**
     * Asynchronously call the remote tool with varargs key-value pairs.
     *
     * @param keyValuePairs Alternating key-value pairs
     * @return A future that completes with the tool's response, deserialized to type T
     */
    CompletableFuture<T> callAsync(Object... keyValuePairs);

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
