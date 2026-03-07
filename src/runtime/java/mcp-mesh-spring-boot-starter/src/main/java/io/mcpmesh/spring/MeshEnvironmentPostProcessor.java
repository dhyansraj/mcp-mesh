package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Maps MCP_MESH_HTTP_PORT environment variable to Spring Boot's server.port.
 *
 * <p>This ensures Java agents behave consistently with Python/TypeScript agents
 * where MCP_MESH_HTTP_PORT controls both the HTTP server port and mesh registration.
 *
 * <p>Only applies to applications whose main class is annotated with {@link MeshAgent}.
 * Non-mesh Spring Boot apps sharing the starter dependency are not affected.
 *
 * <p>Priority: MCP_MESH_HTTP_PORT takes precedence over application.properties server.port.
 */
public class MeshEnvironmentPostProcessor implements EnvironmentPostProcessor {

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        // Only override port for actual mesh agents
        Set<Object> sources = application.getAllSources();
        boolean isMeshAgent = sources.stream()
            .filter(s -> s instanceof Class<?>)
            .map(s -> (Class<?>) s)
            .anyMatch(c -> c.isAnnotationPresent(MeshAgent.class));

        if (!isMeshAgent) return;

        String meshPort = System.getenv("MCP_MESH_HTTP_PORT");
        if (meshPort != null && !meshPort.isBlank()) {
            Map<String, Object> props = new HashMap<>();
            props.put("server.port", meshPort);
            // addFirst gives highest priority, overriding application.properties
            environment.getPropertySources().addFirst(new MapPropertySource("meshPortOverride", props));
        }

        // Map TLS env vars to Spring Boot SSL properties (PEM-based, Spring Boot 3.1+)
        String tlsMode = environment.getProperty("MCP_MESH_TLS_MODE", "off");
        if (!"off".equalsIgnoreCase(tlsMode) && !tlsMode.isEmpty()) {
            String certPath = environment.getProperty("MCP_MESH_TLS_CERT");
            String keyPath = environment.getProperty("MCP_MESH_TLS_KEY");
            String caPath = environment.getProperty("MCP_MESH_TLS_CA");

            if (certPath != null && keyPath != null) {
                Map<String, Object> sslProps = new LinkedHashMap<>();
                sslProps.put("server.ssl.certificate", certPath);
                sslProps.put("server.ssl.certificate-private-key", keyPath);
                if (caPath != null) {
                    sslProps.put("server.ssl.trust-certificate", caPath);
                    sslProps.put("server.ssl.client-auth", "need");
                }
                environment.getPropertySources().addFirst(
                    new MapPropertySource("meshTlsProperties", sslProps));
            }
        }
    }
}
