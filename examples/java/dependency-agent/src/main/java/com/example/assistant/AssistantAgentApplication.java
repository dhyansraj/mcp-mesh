package com.example.assistant;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * MCP Mesh agent demonstrating @MeshTool dependencies.
 *
 * <p>This example shows:
 * <ul>
 *   <li>@MeshTool with dependencies - declaring required capabilities</li>
 *   <li>McpMeshTool injection - mesh proxy automatically injected</li>
 *   <li>Graceful degradation - fallback when dependency unavailable</li>
 *   <li>Auto-rewiring - proxy updates when topology changes</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Start a date service provider (Python example)
 * meshctl start -d examples/date-service/date_service.py
 *
 * # Or start the Java basic-tool-agent as a simple provider
 * # (This example will use fallback if no date_service is available)
 *
 * # Run this agent
 * cd examples/java/dependency-agent
 * mvn spring-boot:run
 *
 * # Test with meshctl
 * meshctl list                                    # Shows assistant agent
 * meshctl call smart_greeting '{"name": "World"}'  # Uses date_service or fallback
 * </pre>
 *
 * <h2>Testing Graceful Degradation</h2>
 * <pre>
 * # Call without date_service running - uses fallback
 * meshctl call smart_greeting '{"name": "World"}'
 * # Output: "Hello, World! Today is 2026-01-29 (local fallback)"
 *
 * # Start date_service, call again - uses injected dependency
 * meshctl start -d examples/date-service/date_service.py
 * meshctl call smart_greeting '{"name": "World"}'
 * # Output: "Hello, World! Today is Wednesday, January 29, 2026"
 * </pre>
 */
@MeshAgent(
    name = "assistant",
    version = "1.0.0",
    description = "Assistant with mesh dependencies",
    port = 9001
)
@SpringBootApplication
public class AssistantAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(AssistantAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Assistant Agent...");
        SpringApplication.run(AssistantAgentApplication.class, args);
    }

    /**
     * Smart greeting with date from mesh dependency.
     *
     * <p>The {@code dateService} parameter is automatically injected by the mesh
     * when a matching capability is available. If unavailable, it will be null.
     *
     * @param name        The name to greet
     * @param dateService Injected mesh proxy for date_service capability (may be null)
     * @return Greeting with date
     */
    @MeshTool(
        capability = "smart_greeting",
        description = "Greet with current date from mesh",
        tags = {"greeting", "assistant", "java"},
        dependencies = @Selector(capability = "date_service")
    )
    public GreetingResponse smartGreet(
        @Param(value = "name", description = "The name to greet") String name,
        McpMeshTool<String> dateService
    ) {
        log.info("Smart greeting for: {}", name);

        String dateString;
        String source;

        if (dateService != null && dateService.isAvailable()) {
            // Call the remote date_service via mesh
            log.info("Using mesh date_service at: {}", dateService.getEndpoint());
            try {
                // Call with no parameters - date_service returns a formatted string
                dateString = dateService.call();
                source = "mesh:" + dateService.getCapability();
            } catch (Exception e) {
                log.warn("Failed to call date_service, using fallback: {}", e.getMessage());
                dateString = LocalDate.now().toString();
                source = "fallback (call failed)";
            }
        } else {
            // Graceful degradation - use local date
            log.info("date_service unavailable, using local fallback");
            dateString = LocalDate.now().toString();
            source = "local fallback";
        }

        String message = String.format("Hello, %s! Today is %s", name, dateString);
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);

        return new GreetingResponse(message, timestamp, source);
    }

    /**
     * Get agent status including dependency information.
     *
     * @param dateService Injected mesh proxy (may be null)
     * @return Agent status
     */
    @MeshTool(
        capability = "agent_status",
        description = "Get agent status with dependency info",
        tags = {"status", "info", "java"},
        dependencies = @Selector(capability = "date_service")
    )
    public AgentStatus getStatus(McpMeshTool<String> dateService) {
        boolean dateServiceAvailable = dateService != null && dateService.isAvailable();
        String dateServiceEndpoint = dateServiceAvailable ? dateService.getEndpoint() : null;

        return new AgentStatus(
            "assistant",
            "1.0.0",
            "Java " + System.getProperty("java.version"),
            System.getProperty("os.name"),
            dateServiceAvailable,
            dateServiceEndpoint
        );
    }

    /**
     * Greeting response record.
     */
    public record GreetingResponse(
        String message,
        String timestamp,
        String source
    ) {}

    /**
     * Agent status record with dependency information.
     */
    public record AgentStatus(
        String name,
        String version,
        String runtime,
        String platform,
        boolean dateServiceAvailable,
        String dateServiceEndpoint
    ) {}
}
