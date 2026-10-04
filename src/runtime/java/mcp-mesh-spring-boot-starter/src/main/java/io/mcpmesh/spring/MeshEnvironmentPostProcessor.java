package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.MutablePropertySources;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Function;

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
 * <p>Applies to every application the mesh runtime runs in (issue #1592) — the
 * starter's auto-configuration starts the runtime for any app on its classpath,
 * including a consumer-only {@code @MeshRoute} / {@code @MeshService} app with no
 * {@code @MeshAgent}. Precedence depends on whether the app opted in:
 * <ul>
 *   <li><b>{@code @MeshAgent} on the main class</b>: the mapped values take the
 *       HIGHEST precedence, overriding the app's own configuration — mesh owns
 *       this agent's port and TLS (unchanged behaviour).</li>
 *   <li><b>Any other app</b>: the mapped values take the LOWEST precedence (just
 *       above {@code defaultProperties}). They only fill gaps: an explicit
 *       {@code server.port} / {@code server.ssl.*} from application properties,
 *       the command line or a test ({@code @SpringBootTest} {@code RANDOM_PORT},
 *       {@code properties=}) wins. A route-only gateway deployed by the Helm chart,
 *       which always sets {@code MCP_MESH_HTTP_PORT}, keeps its configured port.</li>
 * </ul>
 *
 * <p>Skipped entirely for a Spring Cloud bootstrap context and for an app that
 * excludes {@link MeshAutoConfiguration}. {@code MCP_MESH_TLS_MODE} without a
 * certificate and key still fails fast in every app: TLS was asked for.
 */
public class MeshEnvironmentPostProcessor implements EnvironmentPostProcessor {

    /** Spring Cloud's bootstrap property source name — the standard bootstrap-context check. */
    static final String BOOTSTRAP_PROPERTY_SOURCE = "bootstrap";

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        process(environment, application, System::getenv);
    }

    /** The env-injectable core of {@link #postProcessEnvironment} (tests supply {@code getenv}). */
    void process(ConfigurableEnvironment environment, SpringApplication application,
                 Function<String, String> getenv) {
        if (environment.getPropertySources().contains(BOOTSTRAP_PROPERTY_SOURCE)) return;
        if (meshAutoConfigurationExcluded(environment, application)) return;

        boolean meshAgentMain = application.getAllSources().stream()
            .filter(s -> s instanceof Class<?>)
            .map(s -> (Class<?>) s)
            .anyMatch(c -> c.isAnnotationPresent(MeshAgent.class));

        String meshPort = getenv.apply("MCP_MESH_HTTP_PORT");
        if (meshPort != null && !meshPort.isBlank()) {
            Map<String, Object> props = new LinkedHashMap<>();
            props.put("server.port", meshPort);
            add(environment, new MapPropertySource("meshPortOverride", props), meshAgentMain);
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
            String val = getenv.apply(envVar);
            if (val != null && !val.isBlank()) {
                mediaProps.put(prop, val);
            }
        });
        if (!mediaProps.isEmpty()) {
            add(environment, new MapPropertySource("meshMediaProperties", mediaProps), meshAgentMain);
        }

        // Map TLS env vars to Spring Boot SSL properties (PEM-based, Spring Boot 3.1+)
        String tlsMode = environment.getProperty("MCP_MESH_TLS_MODE", "off");
        if (!"off".equalsIgnoreCase(tlsMode) && !tlsMode.isEmpty()) {
            String provider = getenv.apply("MCP_MESH_TLS_PROVIDER");
            MeshTlsConfig.requireSupportedProvider(tlsMode, provider);
            String certPath = environment.getProperty("MCP_MESH_TLS_CERT");
            String keyPath = environment.getProperty("MCP_MESH_TLS_KEY");
            String caPath = environment.getProperty("MCP_MESH_TLS_CA");

            // For non-file providers (e.g., vault), try to prepare TLS early
            if (provider != null && !"file".equalsIgnoreCase(provider) && (certPath == null || keyPath == null)) {
                String agentName = getenv.apply("MCP_MESH_AGENT_NAME");
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
                        String advice = "vault".equalsIgnoreCase(provider.trim())
                            ? ". Ensure Vault is reachable and VAULT_TOKEN is valid."
                            : ".";
                        throw new IllegalStateException(
                            "MCP_MESH_TLS_PROVIDER=" + provider + " but TLS preparation failed: " + e.getMessage()
                                + advice, e);
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
                add(environment, new MapPropertySource("meshTlsProperties", sslProps), meshAgentMain);
            } else if (provider == null || "file".equalsIgnoreCase(provider)) {
                // Only throw for file provider -- non-file providers will configure TLS later
                throw new IllegalStateException(
                    "MCP_MESH_TLS_MODE=" + tlsMode + " but MCP_MESH_TLS_CERT or MCP_MESH_TLS_KEY is not set");
            }
        }
    }

    /**
     * Highest precedence for a {@code @MeshAgent} main class (mesh owns its
     * server config); otherwise lowest, just above {@code defaultProperties},
     * so the app's own configuration wins and the mesh values fill gaps.
     */
    private static void add(ConfigurableEnvironment environment, MapPropertySource source, boolean override) {
        MutablePropertySources sources = environment.getPropertySources();
        if (override) {
            sources.addFirst(source);
        } else if (sources.contains("defaultProperties")) {
            sources.addBefore("defaultProperties", source);
        } else {
            sources.addLast(source);
        }
    }

    /**
     * Whether the app switched the mesh off by excluding
     * {@link MeshAutoConfiguration} — via {@code spring.autoconfigure.exclude}
     * (bound the way Spring Boot's {@code AutoConfigurationImportSelector} binds
     * it, so both the comma-separated and the indexed YAML list forms count) or
     * {@code @SpringBootApplication(exclude = ...)} on a source class.
     */
    private static boolean meshAutoConfigurationExcluded(
            ConfigurableEnvironment environment, SpringApplication application) {
        String meshAutoConfig = MeshAutoConfiguration.class.getName();
        String[] excluded = Binder.get(environment)
            .bind("spring.autoconfigure.exclude", String[].class)
            .orElse(new String[0]);
        for (String name : excluded) {
            if (meshAutoConfig.equals(name.trim())) {
                return true;
            }
        }
        for (Object source : application.getAllSources()) {
            if (!(source instanceof Class<?> c)) {
                continue;
            }
            EnableAutoConfiguration eac =
                AnnotatedElementUtils.findMergedAnnotation(c, EnableAutoConfiguration.class);
            if (eac == null) {
                continue;
            }
            for (Class<?> ex : eac.exclude()) {
                if (ex == MeshAutoConfiguration.class) {
                    return true;
                }
            }
            for (String name : eac.excludeName()) {
                if (meshAutoConfig.equals(name)) {
                    return true;
                }
            }
        }
        return false;
    }
}
