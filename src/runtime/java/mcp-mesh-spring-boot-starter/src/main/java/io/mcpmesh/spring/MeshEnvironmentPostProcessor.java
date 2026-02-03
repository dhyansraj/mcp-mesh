package io.mcpmesh.spring;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.util.HashMap;
import java.util.Map;

/**
 * Maps MCP_MESH_HTTP_PORT environment variable to Spring Boot's server.port.
 *
 * <p>This ensures Java agents behave consistently with Python/TypeScript agents
 * where MCP_MESH_HTTP_PORT controls both the HTTP server port and mesh registration.
 *
 * <p>Priority: MCP_MESH_HTTP_PORT takes precedence over application.properties server.port.
 */
public class MeshEnvironmentPostProcessor implements EnvironmentPostProcessor {

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        String meshPort = System.getenv("MCP_MESH_HTTP_PORT");
        if (meshPort != null && !meshPort.isBlank()) {
            Map<String, Object> props = new HashMap<>();
            props.put("server.port", meshPort);
            // addFirst gives highest priority, overriding application.properties
            environment.getPropertySources().addFirst(new MapPropertySource("meshPortOverride", props));
        }
    }
}
