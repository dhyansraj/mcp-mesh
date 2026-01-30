package com.example.greeter;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

/**
 * Basic MCP Mesh agent example with a simple greeting tool.
 *
 * <p>This demonstrates:
 * <ul>
 *   <li>@MeshAgent for agent configuration</li>
 *   <li>@MeshTool for capability registration</li>
 *   <li>@Param for tool parameter documentation</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * mvn spring-boot:run
 *
 * # Or with environment overrides
 * MCP_MESH_HTTP_PORT=9001 mvn spring-boot:run
 *
 * # Test with meshctl
 * meshctl list                    # Should show "greeter" agent
 * meshctl list -t                 # Should show "greeting" tool
 * meshctl call greeting '{"name": "World"}'
 * </pre>
 */
@MeshAgent(
    name = "greeter",
    version = "1.0.0",
    description = "Simple greeting service",
    port = 9000
)
@SpringBootApplication
public class GreeterAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(GreeterAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Greeter Agent...");
        SpringApplication.run(GreeterAgentApplication.class, args);
    }

    /**
     * Greet a user by name.
     *
     * @param name The name to greet
     * @return A greeting message
     */
    @MeshTool(
        capability = "greeting",
        description = "Greet a user by name",
        tags = {"greeting", "utility", "java"}
    )
    public GreetingResponse greet(
        @Param(value = "name", description = "The name to greet") String name
    ) {
        log.info("Greeting: {}", name);

        String timestamp = LocalDateTime.now()
            .format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);

        String message = String.format("Hello, %s! Welcome to MCP Mesh.", name);

        return new GreetingResponse(message, timestamp, "greeter-java");
    }

    /**
     * Get agent information.
     *
     * @return Agent metadata
     */
    @MeshTool(
        capability = "agent_info",
        description = "Get information about this agent",
        tags = {"info", "metadata", "java"}
    )
    public AgentInfo getInfo() {
        return new AgentInfo(
            "greeter",
            "1.0.0",
            "Java " + System.getProperty("java.version"),
            System.getProperty("os.name")
        );
    }

    /**
     * Add two numbers using the remote calculator service.
     * Demonstrates cross-agent tool calls (Java -> TypeScript).
     *
     * @param a First number
     * @param b Second number
     * @param calculator Injected calculator tool from mesh
     * @return Calculation result with metadata
     */
    @MeshTool(
        capability = "add_via_mesh",
        description = "Add two numbers using the remote calculator service (cross-agent call)",
        tags = {"math", "cross-agent", "java"},
        dependencies = @Selector(capability = "add")
    )
    public CalculationResult addViaMesh(
        @Param(value = "a", description = "First number") int a,
        @Param(value = "b", description = "Second number") int b,
        McpMeshTool calculator
    ) {
        log.info("addViaMesh called: {} + {} via {}", a, b, calculator.getCapability());

        // Call the remote calculator's add tool
        Object result = calculator.call(Map.of("a", a, "b", b));

        log.info("Remote calculator response: {} (type: {})", result,
            result != null ? result.getClass().getSimpleName() : "null");

        // Extract result - handle both String and Map responses
        int sum = 0;
        if (result instanceof String str) {
            // Calculator returns just the number as a string
            sum = Integer.parseInt(str);
        } else if (result instanceof Number num) {
            sum = num.intValue();
        } else if (result instanceof Map<?, ?> map) {
            // Handle map response with result or sum field
            Object value = map.get("result");
            if (value == null) {
                value = map.get("sum");
            }
            if (value instanceof Number num) {
                sum = num.intValue();
            } else if (value instanceof String str) {
                sum = Integer.parseInt(str);
            }
        }

        return new CalculationResult(
            a,
            b,
            "+",
            sum,
            "greeter-java → calculator-typescript",
            calculator.getEndpoint()
        );
    }

    /**
     * Calculation result record.
     */
    public record CalculationResult(
        int operandA,
        int operandB,
        String operation,
        int result,
        String callPath,
        String remoteEndpoint
    ) {}

    /**
     * Greeting response record.
     */
    public record GreetingResponse(
        String message,
        String timestamp,
        String source
    ) {}

    /**
     * Agent information record.
     */
    public record AgentInfo(
        String name,
        String version,
        String runtime,
        String platform
    ) {}
}
