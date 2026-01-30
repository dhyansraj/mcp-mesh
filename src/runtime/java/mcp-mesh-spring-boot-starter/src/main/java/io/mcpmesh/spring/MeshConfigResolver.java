package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCore;
import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Resolves configuration values via the Rust core with priority: ENV > param > default.
 *
 * <p>This class delegates to the Rust core for consistent config resolution across
 * all MCP Mesh SDKs (Python, TypeScript, Java). The Rust core handles:
 * <ul>
 *   <li>Environment variable resolution (MCP_MESH_*)</li>
 *   <li>Parameter value fallback</li>
 *   <li>Default values</li>
 *   <li>Auto-detection of external IP for http_host</li>
 * </ul>
 *
 * <p>This ensures Java agents behave identically to Python and TypeScript agents
 * when resolving configuration values.
 */
public class MeshConfigResolver {

    private static final Logger log = LoggerFactory.getLogger(MeshConfigResolver.class);

    private final MeshCore core;

    /**
     * Create a new config resolver that delegates to Rust core.
     */
    public MeshConfigResolver() {
        this.core = MeshCore.load();
    }

    /**
     * Create a new config resolver with a specific MeshCore instance.
     *
     * @param core The MeshCore instance to use
     */
    public MeshConfigResolver(MeshCore core) {
        this.core = core;
    }

    /**
     * Resolve a string configuration value via Rust core.
     *
     * <p>Resolution priority: ENV > param > default (with auto-detect for http_host).
     *
     * @param key        Config key name (e.g., "http_host", "registry_url", "namespace")
     * @param paramValue Optional value from code/config (may be null)
     * @return Resolved value, or null if unknown key
     */
    public String resolve(String key, String paramValue) {
        Pointer result = core.mesh_resolve_config(key, paramValue);
        if (result == null) {
            log.debug("Config '{}' resolved to null (unknown key or no value)", key);
            return null;
        }
        try {
            String value = result.getString(0);
            log.debug("Config '{}' resolved to: {}", key, value);
            return value;
        } finally {
            core.mesh_free_string(result);
        }
    }

    /**
     * Resolve an integer configuration value via Rust core.
     *
     * @param key        Config key name (e.g., "http_port", "health_interval")
     * @param paramValue Value from code/config (-1 for none)
     * @return Resolved value, or -1 if unknown key or no value
     */
    public int resolveInt(String key, int paramValue) {
        long result = core.mesh_resolve_config_int(key, paramValue);
        log.debug("Config '{}' (int) resolved to: {}", key, result);
        return (int) result;
    }

    /**
     * Auto-detect external IP address via Rust core.
     *
     * <p>Uses UDP socket trick to find IP that routes to external networks.
     * Falls back to "localhost" if detection fails.
     *
     * @return IP address string
     */
    public String autoDetectIp() {
        Pointer result = core.mesh_auto_detect_ip();
        if (result == null) {
            log.warn("Auto-detect IP returned null, falling back to localhost");
            return "localhost";
        }
        try {
            String ip = result.getString(0);
            log.debug("Auto-detected IP: {}", ip);
            return ip;
        } finally {
            core.mesh_free_string(result);
        }
    }

    // =========================================================================
    // Legacy methods for backwards compatibility
    // =========================================================================

    /**
     * Resolve a string configuration value (legacy signature).
     *
     * <p>This method is provided for backwards compatibility. It converts the
     * old 3-parameter signature to the new Rust-delegating implementation.
     *
     * @param key             Config key (e.g., "AGENT_NAME" - will be lowercased)
     * @param annotationValue Value from annotation (may be null)
     * @param propertiesValue Value from properties (may be null)
     * @return Resolved value
     * @deprecated Use {@link #resolve(String, String)} instead
     */
    @Deprecated
    public String resolve(String key, String annotationValue, String propertiesValue) {
        // Convert old key format (AGENT_NAME) to new format (agent_name)
        String normalizedKey = key.toLowerCase();

        // Prefer annotation value, then properties value as param
        String paramValue = annotationValue;
        if ((paramValue == null || paramValue.isBlank()) && propertiesValue != null && !propertiesValue.isBlank()) {
            paramValue = propertiesValue;
        }

        return resolve(normalizedKey, paramValue);
    }

    /**
     * Resolve an integer configuration value (legacy signature).
     *
     * <p>This method is provided for backwards compatibility.
     *
     * @param key             Config key (e.g., "HTTP_PORT" - will be lowercased)
     * @param annotationValue Value from annotation
     * @param propertiesValue Value from properties
     * @return Resolved value
     * @deprecated Use {@link #resolveInt(String, int)} instead
     */
    @Deprecated
    public int resolveInt(String key, int annotationValue, int propertiesValue) {
        // Convert old key format to new format
        String normalizedKey = key.toLowerCase();

        // Prefer annotation value if non-zero, otherwise properties value
        int paramValue = annotationValue != 0 ? annotationValue : propertiesValue;

        return resolveInt(normalizedKey, paramValue);
    }

    /**
     * Check if debug mode is enabled.
     *
     * @return true if MCP_MESH_DEBUG=true
     */
    public boolean isDebugEnabled() {
        String debug = System.getenv("MCP_MESH_DEBUG");
        if (debug == null) {
            debug = System.getProperty("MCP_MESH_DEBUG");
        }
        return "true".equalsIgnoreCase(debug);
    }

    /**
     * Get log level from environment.
     *
     * @return Log level string or "info" as default
     */
    public String getLogLevel() {
        String level = System.getenv("MCP_MESH_LOG_LEVEL");
        if (level == null) {
            level = System.getProperty("MCP_MESH_LOG_LEVEL");
        }
        return level != null ? level : "info";
    }
}
