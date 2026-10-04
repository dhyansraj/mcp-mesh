package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.NativeLoader;
import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.util.Locale;
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

    /** Issue #1596: the refusal a Java agent configured for SPIRE starts with. */
    static final String SPIRE_UNSUPPORTED_MESSAGE =
        "MCP_MESH_TLS_PROVIDER=spire is not supported by the Java runtime; use file or vault.";

    /**
     * Refuse a credential provider the Java runtime cannot serve, before any
     * native call is made (issue #1596).
     *
     * <p>The native library the Java runtime loads is built without the
     * {@code spire} feature, and Spring's EnvironmentPostProcessor needs TLS
     * material before an in-process Workload API fetch could run, so
     * {@code spire} can never succeed here. Without this check the attempt
     * reached the core and surfaced as a Vault-specific error.
     * A TLS mode that normalizes to off ignores the provider, as the core does.
     */
    static void requireSupportedProvider(String tlsMode, String provider) {
        if ("off".equals(normalizeMode(tlsMode))) {
            return;
        }
        if ("spire".equals(normalizeProvider(provider))) {
            throw new IllegalStateException(SPIRE_UNSUPPORTED_MESSAGE);
        }
    }

    /**
     * Normalize {@code MCP_MESH_TLS_MODE} exactly as the native core does
     * ({@code TlsMode::from_str_value} in {@code tls.rs}): trimmed and
     * case-insensitive; unset, blank and unrecognized values all mean
     * {@code off}, the last with a warning. Returns {@code off},
     * {@code auto} or {@code strict}.
     */
    static String normalizeMode(String raw) {
        if (raw == null) {
            return "off";
        }
        String value = raw.trim().toLowerCase(Locale.ROOT);
        switch (value) {
            case "auto":
            case "strict":
                return value;
            case "":
            case "off":
                return "off";
            default:
                log.warn("Unknown MCP_MESH_TLS_MODE '{}', defaulting to off", raw.trim());
                return "off";
        }
    }

    /**
     * Normalize {@code MCP_MESH_TLS_PROVIDER}: trimmed and lower-cased, with
     * unset or blank returned as {@code null} (the core then uses {@code file}).
     */
    static String normalizeProvider(String raw) {
        if (raw == null) {
            return null;
        }
        String value = raw.trim();
        return value.isEmpty() ? null : value.toLowerCase(Locale.ROOT);
    }

    /**
     * Prepare TLS credentials (fetch from Vault, write secure temp files).
     * Must be called before get() when using non-file providers.
     * Results are cached globally in Rust core.
     */
    public static synchronized void prepareTls(String agentName) {
        if (cached != null) return; // Already resolved
        requireSupportedProvider(System.getenv("MCP_MESH_TLS_MODE"), System.getenv("MCP_MESH_TLS_PROVIDER"));

        try {
            MeshCore core = NativeLoader.load();
            Pointer ptr = core.mesh_prepare_tls(agentName);
            if (ptr == null) {
                String errMsg = "unknown error";
                Pointer errPtr = core.mesh_last_error();
                if (errPtr != null) {
                    try {
                        errMsg = errPtr.getString(0);
                    } finally {
                        core.mesh_free_string(errPtr);
                    }
                }
                throw new RuntimeException("mesh_prepare_tls failed: " + errMsg);
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
                if (cached.enabled) {
                    log.info("TLS prepared: mode={} cert={}", cached.mode, cached.certPath);
                }
            } finally {
                core.mesh_free_string(ptr);
            }
        } catch (Exception e) {
            throw new RuntimeException("Failed to prepare TLS: " + e.getMessage(), e);
        }
    }

    /**
     * Clean up temporary TLS credential files and clear cached state.
     * Call during agent shutdown.
     */
    public static synchronized void cleanupTls() {
        try {
            MeshCore core = NativeLoader.load();
            core.mesh_cleanup_tls();
            cached = null;
            log.debug("TLS credentials cleaned up");
        } catch (Exception e) {
            log.debug("TLS cleanup failed: {}", e.getMessage());
        }
    }

    public static synchronized MeshTlsConfig get() {
        if (cached != null) return cached;

        try {
            MeshCore core = NativeLoader.load();
            Pointer ptr = core.mesh_get_tls_config();
            if (ptr == null) {
                // Check if null means error vs genuinely disabled
                Pointer errPtr = core.mesh_last_error();
                if (errPtr != null) {
                    try {
                        String errMsg = errPtr.getString(0);
                        log.warn("mesh_get_tls_config failed: {}", errMsg);
                    } finally {
                        core.mesh_free_string(errPtr);
                    }
                }
                log.debug("TLS disabled (no config from Rust core)");
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
            log.error("Failed to load TLS config from Rust core: {}", e.getMessage());
            // Return fallback but don't cache — allows retry on next call
            return new MeshTlsConfig(false, "off", null, null, null);
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
