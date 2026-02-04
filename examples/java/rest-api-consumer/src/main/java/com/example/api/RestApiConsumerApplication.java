package com.example.api;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteUtils;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Example Spring Boot REST API that consumes mesh agents via @MeshRoute.
 *
 * <p>This demonstrates how to:
 * <ul>
 *   <li>Use @MeshRoute to declare mesh dependencies on REST endpoints</li>
 *   <li>Inject dependencies via @MeshInject parameter annotation</li>
 *   <li>Access dependencies via request attributes</li>
 *   <li>Handle optional dependencies gracefully</li>
 * </ul>
 *
 * <h2>Running this Example</h2>
 * <pre>
 * # 1. Start the registry
 * meshctl start --registry-only -d
 *
 * # 2. Start a greeter agent (provides 'greet' capability)
 * meshctl start examples/java/basic-tool-agent -d
 *
 * # 3. Start this REST API consumer
 * cd examples/java/rest-api-consumer
 * mvn spring-boot:run
 *
 * # 4. Call the REST endpoint
 * curl http://localhost:8080/api/greet?name=World
 * </pre>
 */
@SpringBootApplication
@MeshAgent(name = "rest-api-consumer", version = "1.0.0")
public class RestApiConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(RestApiConsumerApplication.class, args);
    }
}

/**
 * REST controller demonstrating @MeshRoute usage patterns.
 */
@RestController
@RequestMapping("/api")
class ApiController {

    private static final Logger log = LoggerFactory.getLogger(ApiController.class);

    /**
     * Example 1: Using @MeshInject for clean parameter injection.
     *
     * <p>The @MeshInject annotation directly injects the resolved McpMeshTool
     * into the method parameter. This is the recommended approach for most cases.
     *
     * <p>Note: The parameter name "greeting" matches the capability name, so no
     * annotation is needed - just like @MeshTool dependency injection.
     */
    @GetMapping("/greet")
    @MeshRoute(
        dependencies = @MeshDependency(capability = "greeting"),
        description = "Greet a user via the greeter mesh agent"
    )
    public ResponseEntity<Map<String, Object>> greetWithInject(
            @RequestParam(defaultValue = "World") String name,
            McpMeshTool<Map<String, Object>> greeting) {  // Parameter name matches capability

        log.info("Greeting {} via mesh agent", name);

        // Call the remote greeter agent
        Map<String, Object> result = greeting.call(Map.of("name", name));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent");
        response.put("result", result);
        response.put("timestamp", LocalDateTime.now().toString());

        return ResponseEntity.ok(response);
    }

    /**
     * Example 2: Using MeshRouteUtils for request attribute access.
     *
     * <p>This approach is useful when you need more control over dependency
     * access or want to check availability before calling.
     */
    @GetMapping("/greet-alt")
    @MeshRoute(
        dependencies = @MeshDependency(capability = "greeting"),
        description = "Alternative greeting endpoint using request attributes"
    )
    public ResponseEntity<Map<String, Object>> greetWithAttributes(
            @RequestParam(defaultValue = "World") String name,
            HttpServletRequest request) {

        log.info("Greeting {} via mesh agent (attribute access)", name);

        // Access dependency via utility method
        McpMeshTool greeterTool = MeshRouteUtils.getDependency(request, "greeting");

        if (greeterTool == null || !greeterTool.isAvailable()) {
            return ResponseEntity.status(503)
                .body(Map.of("error", "Greeter service not available"));
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) greeterTool.call(Map.of("name", name));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent");
        response.put("result", result);
        response.put("timestamp", LocalDateTime.now().toString());

        return ResponseEntity.ok(response);
    }

    /**
     * Example 3: Multiple dependencies showing both injection styles.
     *
     * <p>This demonstrates:
     * <ul>
     *   <li>Plain McpMeshTool with matching parameter name (greeting)</li>
     *   <li>@MeshInject when capability name differs from parameter name (agent_info → infoTool)</li>
     * </ul>
     */
    @PostMapping("/process")
    @MeshRoute(
        dependencies = {
            @MeshDependency(capability = "greeting"),
            @MeshDependency(capability = "agent_info")
        },
        description = "Process data using multiple mesh agents"
    )
    public ResponseEntity<Map<String, Object>> processWithMultipleDeps(
            @RequestBody Map<String, Object> input,
            McpMeshTool<Map<String, Object>> greeting,  // Parameter name matches capability
            @MeshInject("agent_info") McpMeshTool<Map<String, Object>> infoTool) {  // Explicit when names differ

        log.info("Processing with multiple mesh agents");

        // Call both agents
        String name = (String) input.getOrDefault("name", "Guest");
        Map<String, Object> greetingResult = greeting.call(Map.of("name", name));
        Map<String, Object> info = infoTool.call();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("greeting", greetingResult);
        response.put("agentInfo", info);
        response.put("timestamp", LocalDateTime.now().toString());

        return ResponseEntity.ok(response);
    }

    /**
     * Example 4: Optional dependency with graceful fallback.
     *
     * <p>When failOnMissingDependency=false, the route will execute even
     * if dependencies are unavailable. Check availability before calling.
     */
    @GetMapping("/optional-greet")
    @MeshRoute(
        dependencies = @MeshDependency(capability = "greeting"),
        failOnMissingDependency = false,
        description = "Greeting with fallback if agent unavailable"
    )
    public ResponseEntity<Map<String, Object>> greetWithFallback(
            @RequestParam(defaultValue = "World") String name,
            McpMeshTool<Map<String, Object>> greeting) {  // Parameter name matches capability

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("timestamp", LocalDateTime.now().toString());

        if (greeting != null && greeting.isAvailable()) {
            log.info("Using mesh agent to greet {}", name);
            Map<String, Object> result = greeting.call(Map.of("name", name));
            response.put("source", "mesh-agent");
            response.put("result", result);
        } else {
            log.info("Mesh agent unavailable, using fallback for {}", name);
            response.put("source", "local-fallback");
            response.put("result", Map.of("message", "Hello, " + name + "! (from fallback)"));
        }

        return ResponseEntity.ok(response);
    }

    /**
     * Health check endpoint (no mesh dependencies).
     */
    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(Map.of(
            "status", "healthy",
            "timestamp", LocalDateTime.now().toString()
        ));
    }
}
