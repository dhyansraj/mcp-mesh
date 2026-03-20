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
 * Maps MCP_MESH environment variables to Spring Boot properties.
 *
 * <p>Handles mappings where Spring Boot's relaxed binding would otherwise resolve
 * env vars incorrectly (e.g., MCP_MESH_MEDIA_STORAGE_BUCKET becomes
 * {@code mcp.mesh.media.storage.bucket} instead of {@code mcp.mesh.media.storage-bucket}).
 *
 * <p>Mappings include:
 * <ul>
 *   <li>MCP_MESH_HTTP_PORT &rarr; server.port</li>
 *   <li>MCP_MESH_MEDIA_STORAGE* &rarr; mcp.mesh.media.storage-*</li>
 *   <li>MCP_MESH_TLS_* &rarr; server.ssl.*</li>
 * </ul>
 *
 * <p>Only applies to applications whose main class is annotated with {@link MeshAgent}.
 * Non-mesh Spring Boot apps sharing the starter dependency are not affected.
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

        // Map media config env vars to Spring properties.
        // Spring's relaxed binding splits MCP_MESH_MEDIA_STORAGE_BUCKET into
        // mcp.mesh.media.storage.bucket (5 levels), but the actual property is
        // mcp.mesh.media.storage-bucket (4 levels, kebab-case). Explicit mapping fixes this.
        Map<String, Object> mediaProps = new LinkedHashMap<>();
        Map.of(
            "MCP_MESH_MEDIA_STORAGE",          "mesh.media.storage",
            "MCP_MESH_MEDIA_STORAGE_PATH",     "mesh.media.storage-path",
            "MCP_MESH_MEDIA_STORAGE_BUCKET",   "mesh.media.storage-bucket",
            "MCP_MESH_MEDIA_STORAGE_ENDPOINT", "mesh.media.storage-endpoint",
            "MCP_MESH_MEDIA_STORAGE_PREFIX",   "mesh.media.storage-prefix"
        ).forEach((envVar, prop) -> {
            String val = System.getenv(envVar);
            if (val != null && !val.isBlank()) {
                mediaProps.put(prop, val);
            }
        });
        if (!mediaProps.isEmpty()) {
            environment.getPropertySources().addFirst(
                new MapPropertySource("meshMediaProperties", mediaProps));
        }

        // Map TLS env vars to Spring Boot SSL properties (PEM-based, Spring Boot 3.1+)
        String tlsMode = environment.getProperty("MCP_MESH_TLS_MODE", "off");
        if (!"off".equalsIgnoreCase(tlsMode) && !tlsMode.isEmpty()) {
            String provider = System.getenv("MCP_MESH_TLS_PROVIDER");
            String certPath = environment.getProperty("MCP_MESH_TLS_CERT");
            String keyPath = environment.getProperty("MCP_MESH_TLS_KEY");
            String caPath = environment.getProperty("MCP_MESH_TLS_CA");

            // For non-file providers (e.g., vault), try to prepare TLS early
            if (provider != null && !"file".equalsIgnoreCase(provider) && (certPath == null || keyPath == null)) {
                String agentName = System.getenv("MCP_MESH_AGENT_NAME");
                if (agentName != null && !agentName.isBlank()) {
                    try {
                        MeshTlsConfig.prepareTls(agentName);
                        MeshTlsConfig config = MeshTlsConfig.get();
                        if (config.isEnabled()) {
                            certPath = config.getCertPath();
                            keyPath = config.getKeyPath();
                            caPath = config.getCaPath();
                        }
                    } catch (Exception e) {
                        throw new IllegalStateException(
                            "MCP_MESH_TLS_PROVIDER=" + provider + " but TLS preparation failed: " + e.getMessage()
                                + ". Ensure Vault is reachable and VAULT_TOKEN is valid.", e);
                    }
                }
            }

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
            } else if (provider == null || "file".equalsIgnoreCase(provider)) {
                // Only throw for file provider -- non-file providers will configure TLS later
                throw new IllegalStateException(
                    "MCP_MESH_TLS_MODE=" + tlsMode + " but MCP_MESH_TLS_CERT or MCP_MESH_TLS_KEY is not set");
            }
        }
    }
}
