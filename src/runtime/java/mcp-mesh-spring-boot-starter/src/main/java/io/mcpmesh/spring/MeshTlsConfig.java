package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.NativeLoader;
import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * TLS configuration resolved from Rust core (cached).
 *
 * <p>Calls mesh_get_tls_config() via FFI and parses the JSON result.
 * The configuration is cached after the first call since TLS settings
 * do not change during agent lifetime.
 */
public class MeshTlsConfig {
    private static final Logger log = LoggerFactory.getLogger(MeshTlsConfig.class);
    private static MeshTlsConfig cached;

    private final boolean enabled;
    private final String mode;
    private final String certPath;
    private final String keyPath;
    private final String caPath;

    private MeshTlsConfig(boolean enabled, String mode, String certPath, String keyPath, String caPath) {
        this.enabled = enabled;
        this.mode = mode;
        this.certPath = certPath;
        this.keyPath = keyPath;
        this.caPath = caPath;
    }

    public static synchronized MeshTlsConfig get() {
        if (cached != null) return cached;

        try {
            MeshCore core = NativeLoader.load();
            Pointer ptr = core.mesh_get_tls_config();
            if (ptr == null) {
                log.debug("mesh_get_tls_config returned null, TLS disabled");
                cached = new MeshTlsConfig(false, "off", null, null, null);
                return cached;
            }
            try {
                String json = ptr.getString(0);
                ObjectMapper mapper = new ObjectMapper();
                JsonNode node = mapper.readTree(json);
                cached = new MeshTlsConfig(
                    node.path("enabled").asBoolean(false),
                    node.path("mode").asText("off"),
                    node.has("cert_path") && !node.get("cert_path").isNull() ? node.get("cert_path").asText() : null,
                    node.has("key_path") && !node.get("key_path").isNull() ? node.get("key_path").asText() : null,
                    node.has("ca_path") && !node.get("ca_path").isNull() ? node.get("ca_path").asText() : null
                );
            } finally {
                core.mesh_free_string(ptr);
            }
        } catch (Exception e) {
            log.debug("Failed to load TLS config from Rust core: {}", e.getMessage());
            cached = new MeshTlsConfig(false, "off", null, null, null);
        }

        if (cached.enabled) {
            log.info("TLS mode: {}", cached.mode);
        }
        return cached;
    }

    public boolean isEnabled() { return enabled; }
    public String getMode() { return mode; }
    public String getCertPath() { return certPath; }
    public String getKeyPath() { return keyPath; }
    public String getCaPath() { return caPath; }
}
