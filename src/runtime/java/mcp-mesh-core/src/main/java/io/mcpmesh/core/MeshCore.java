package io.mcpmesh.core;

import jnr.ffi.LibraryLoader;
import jnr.ffi.Pointer;
import jnr.ffi.annotations.Encoding;

/**
 * JNR-FFI interface to the MCP Mesh Rust core library.
 *
 * <p>This interface maps directly to the C FFI functions exported by the Rust core.
 * Data is exchanged as JSON strings for universal compatibility.
 *
 * <p>Thread Safety: All functions are designed to be safe to call from any thread.
 * Strings returned by mesh_* functions must be freed with mesh_free_string.
 * Handles returned by mesh_start_agent must be freed with mesh_free_handle.
 */
@Encoding("UTF-8")
public interface MeshCore {

    /**
     * Load the native library.
     *
     * @return The loaded MeshCore instance
     * @throws UnsatisfiedLinkError if the library cannot be loaded
     */
    static MeshCore load() {
        return NativeLoader.load();
    }

    // ==========================================================================
    // Lifecycle Functions
    // ==========================================================================

    /**
     * Start an agent from JSON specification.
     *
     * @param specJson JSON string containing AgentSpec
     * @return Handle to agent, or NULL on error (check mesh_last_error)
     */
    Pointer mesh_start_agent(String specJson);

    /**
     * Request graceful shutdown of agent.
     *
     * <p>Sends unregister to registry, stops heartbeat loop.
     * Non-blocking - use mesh_next_event to wait for shutdown event.
     *
     * @param handle Agent handle from mesh_start_agent
     */
    void mesh_shutdown(Pointer handle);

    /**
     * Free agent handle and associated resources.
     *
     * <p>If the agent is still running, this will trigger graceful shutdown
     * and wait briefly (up to 2 seconds) for the agent to unregister.
     *
     * @param handle Agent handle from mesh_start_agent
     */
    void mesh_free_handle(Pointer handle);

    // ==========================================================================
    // Event Functions
    // ==========================================================================

    /**
     * Get next event from agent runtime.
     *
     * <p>Blocks until event available or timeout.
     *
     * @param handle Agent handle
     * @param timeoutMs Timeout in milliseconds (-1 for infinite, 0 for non-blocking)
     * @return JSON string (caller must free with mesh_free_string), or NULL on timeout/shutdown
     */
    Pointer mesh_next_event(Pointer handle, long timeoutMs);

    /**
     * Check if agent is still running.
     *
     * @param handle Agent handle
     * @return 1 if running, 0 if shutdown/error
     */
    int mesh_is_running(Pointer handle);

    // ==========================================================================
    // Health Reporting
    // ==========================================================================

    /**
     * Report agent health status.
     *
     * @param handle Agent handle
     * @param status Health status: "healthy", "degraded", or "unhealthy"
     * @return 0 on success, -1 on error
     */
    int mesh_report_health(Pointer handle, String status);

    // ==========================================================================
    // Config Resolution Functions
    // ==========================================================================

    /**
     * Resolve configuration value with priority: ENV > param > default.
     *
     * <p>For http_host, auto-detects external IP if no value provided.
     *
     * @param keyName Config key (e.g., "http_host", "registry_url", "namespace")
     * @param paramValue Optional value from code/config (may be null)
     * @return Resolved value (caller must free with mesh_free_string), or NULL if unknown key
     */
    Pointer mesh_resolve_config(String keyName, String paramValue);

    /**
     * Resolve integer configuration value with priority: ENV > param > default.
     *
     * @param keyName Config key (e.g., "http_port", "health_interval")
     * @param paramValue Value from code/config (-1 for none)
     * @return Resolved value, or -1 if unknown key or no value available
     */
    long mesh_resolve_config_int(String keyName, long paramValue);

    /**
     * Auto-detect external IP address.
     *
     * <p>Uses UDP socket trick to find IP that routes to external networks.
     * Falls back to "localhost" if detection fails.
     *
     * @return IP address string (caller must free with mesh_free_string)
     */
    Pointer mesh_auto_detect_ip();

    // ==========================================================================
    // Tracing Functions
    // ==========================================================================

    /**
     * Check if tracing is enabled.
     *
     * <p>Checks MCP_MESH_TRACING environment variable.
     *
     * @return 1 if tracing is enabled, 0 otherwise
     */
    int mesh_is_tracing_enabled();

    /**
     * Initialize the trace publisher.
     *
     * <p>Must be called before mesh_publish_span. Connects to Redis.
     *
     * @return 1 on success, 0 on failure
     */
    int mesh_init_trace_publisher();

    /**
     * Check if trace publisher is available.
     *
     * @return 1 if publisher is initialized and ready, 0 otherwise
     */
    int mesh_is_trace_publisher_available();

    /**
     * Publish a trace span to Redis.
     *
     * <p>Non-blocking - returns immediately. The span is queued for async publishing.
     *
     * @param spanJson JSON string containing span data
     * @return 1 on success (queued), 0 on failure
     */
    int mesh_publish_span(String spanJson);

    // ==========================================================================
    // Utility Functions
    // ==========================================================================

    /**
     * Get last error message.
     *
     * <p>Thread-local, cleared on next mesh_* call.
     *
     * @return Error message (caller must free with mesh_free_string), or NULL if no error
     */
    Pointer mesh_last_error();

    /**
     * Free string returned by mesh_* functions.
     *
     * @param s String pointer to free (may be NULL)
     */
    void mesh_free_string(Pointer s);

    /**
     * Get library version string.
     *
     * @return Version string (do not free)
     */
    String mesh_version();
}
