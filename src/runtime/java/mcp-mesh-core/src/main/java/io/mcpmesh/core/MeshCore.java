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

    /**
     * Update the HTTP port after auto-detection.
     *
     * <p>Call this after the HTTP server starts with port=0 to update
     * the registry with the actual assigned port.
     *
     * @param handle Agent handle
     * @param port The actual port the HTTP server is listening on
     * @return 0 on success, -1 on error
     */
    int mesh_update_port(Pointer handle, int port);

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
     * Get TLS configuration resolved from environment variables.
     *
     * Returns JSON with TLS mode, cert paths, and enabled status.
     * SDKs should call this instead of reading TLS env vars directly.
     *
     * @return JSON string (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_get_tls_config();

    /**
     * Prepare TLS credentials (fetch from Vault if configured, write secure temp files).
     * Must be called before mesh_get_tls_config() when using non-file providers.
     *
     * @param agent_name Agent name for certificate CN
     * @return JSON string with TLS config, or null on error
     */
    Pointer mesh_prepare_tls(String agent_name);

    /**
     * Clean up temporary TLS credential files.
     */
    void mesh_cleanup_tls();

    /**
     * Get library version string.
     *
     * @return Version string (do not free)
     */
    String mesh_version();

    // ==========================================================================
    // Response Parsing Functions
    // ==========================================================================

    /**
     * Extract JSON from text that may contain markdown code fences or mixed content.
     *
     * @param text The text to extract JSON from
     * @return JSON string (caller must free with mesh_free_string), or NULL if no JSON found
     */
    Pointer mesh_extract_json(String text);

    /**
     * Strip markdown code fences from text.
     *
     * @param text The text to strip code fences from
     * @return Stripped text (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_strip_code_fences(String text);

    // ==========================================================================
    // Schema Normalization Functions
    // ==========================================================================

    /**
     * Make a JSON schema strict (add additionalProperties: false, all properties required).
     *
     * @param schemaJson JSON schema string
     * @param addAllRequired 1 to add all properties to required array, 0 otherwise
     * @return Strict schema JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_make_schema_strict(String schemaJson, int addAllRequired);

    /**
     * Sanitize a JSON schema by removing validation keywords unsupported by LLM APIs.
     *
     * @param schemaJson JSON schema string
     * @return Sanitized schema JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_sanitize_schema(String schemaJson);

    /**
     * Detect if a schema contains media-related parameters (image, audio, etc.).
     *
     * @param schemaJson JSON schema string
     * @return 1 if media params detected, 0 otherwise
     */
    int mesh_detect_media_params(String schemaJson);

    /**
     * Check if a schema is simple (few fields, no nesting).
     *
     * @param schemaJson JSON schema string
     * @return 1 if simple, 0 if complex
     */
    int mesh_is_simple_schema(String schemaJson);

    /**
     * Normalize a raw JSON Schema and return a JSON envelope with
     * {@code {canonical, hash, verdict, warnings}} (issue #547).
     *
     * <p>Mirrors the Python {@code normalize_schema_py} and napi
     * {@code normalizeSchema} bindings so Java agents emit identical
     * canonical forms and content hashes for cross-runtime capability matching.
     *
     * <p>On error returns a JSON envelope with {@code verdict="BLOCK"} rather
     * than null so callers can always parse the response.
     *
     * @param rawJson Raw JSON Schema string
     * @param origin  Origin runtime hint: "python", "typescript", "java", or unknown.
     *                May be null.
     * @return JSON envelope (caller must free with mesh_free_string)
     */
    Pointer mesh_normalize_schema(String rawJson, String origin);

    // ==========================================================================
    // Trace Context Functions
    // ==========================================================================

    /**
     * Generate an OpenTelemetry-compliant trace ID (32-character hex string).
     *
     * @return Trace ID (caller must free with mesh_free_string)
     */
    Pointer mesh_generate_trace_id();

    /**
     * Generate an OpenTelemetry-compliant span ID (16-character hex string).
     *
     * @return Span ID (caller must free with mesh_free_string)
     */
    Pointer mesh_generate_span_id();

    /**
     * Inject trace context into tool call arguments.
     *
     * @param argsJson JSON string of tool arguments
     * @param traceId Trace ID to inject
     * @param spanId Span ID to inject
     * @param propagatedHeadersJson JSON string of propagated headers (may be null)
     * @return Updated args JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_inject_trace_context(String argsJson, String traceId, String spanId, String propagatedHeadersJson);

    /**
     * Extract trace context from headers and body.
     *
     * @param headersJson JSON string of HTTP headers
     * @param bodyJson JSON string of request body
     * @return JSON with extracted trace context (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_extract_trace_context(String headersJson, String bodyJson);

    /**
     * Filter headers by propagation allowlist.
     *
     * @param headersJson JSON string of headers to filter
     * @param allowlistCsv Comma-separated list of allowed header prefixes
     * @return Filtered headers JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_filter_propagation_headers(String headersJson, String allowlistCsv);

    /**
     * Check if a header name matches any prefix in the propagation allowlist.
     *
     * @param headerName Header name to check
     * @param allowlistCsv Comma-separated list of allowed header prefixes
     * @return 1 if matches, 0 otherwise
     */
    int mesh_matches_propagate_header(String headerName, String allowlistCsv);

    // ==========================================================================
    // MCP Client Functions
    // ==========================================================================

    /**
     * Build a JSON-RPC request string.
     *
     * @param method JSON-RPC method name
     * @param paramsJson JSON string of parameters
     * @param requestId Request ID string
     * @return JSON-RPC request string (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_build_jsonrpc_request(String method, String paramsJson, String requestId);

    /**
     * Generate a unique request ID for JSON-RPC calls.
     *
     * @return Request ID string (caller must free with mesh_free_string)
     */
    Pointer mesh_generate_request_id();

    /**
     * Parse SSE (Server-Sent Events) response text to extract JSON content.
     *
     * @param responseText The SSE-formatted response text
     * @return Extracted JSON content (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_parse_sse_response(String responseText);

    /**
     * Extract content from a JSON-RPC result node.
     *
     * @param resultJson JSON string of the result object
     * @return Extracted content JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_extract_content(String resultJson);

    // ==========================================================================
    // Provider Functions
    // ==========================================================================

    /**
     * Determine the output mode for a provider.
     *
     * @param provider Vendor name (e.g., "anthropic", "openai", "gemini")
     * @param isStringType 1 if the return type is String, 0 otherwise
     * @param hasTools 1 if tools are present, 0 otherwise
     * @param overrideMode Optional override mode (may be null)
     * @return Output mode string (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_determine_output_mode(String provider, int isStringType, int hasTools, String overrideMode);

    /**
     * Format system prompt with vendor-specific additions.
     *
     * @param provider Vendor name (e.g., "anthropic", "openai", "gemini")
     * @param basePrompt Base system prompt text
     * @param hasTools 1 if tools are present, 0 otherwise
     * @param hasMediaParams 1 if media parameters are present, 0 otherwise
     * @param schemaJson Optional JSON schema string (may be null)
     * @param schemaName Optional schema name (may be null)
     * @param outputMode Output mode: "text", "hint", or "strict"
     * @return Complete system prompt (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_format_system_prompt(String provider, String basePrompt, int hasTools, int hasMediaParams, String schemaJson, String schemaName, String outputMode);

    /**
     * Build the response_format object for structured output.
     *
     * @param provider Vendor name
     * @param schemaJson JSON schema string
     * @param schemaName Schema name
     * @param hasTools 1 if tools are present, 0 otherwise
     * @return Response format JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_build_response_format(String provider, String schemaJson, String schemaName, int hasTools);

    /**
     * Get vendor capabilities as JSON.
     *
     * @param provider Vendor name
     * @return Capabilities JSON (caller must free with mesh_free_string), or NULL on error
     */
    Pointer mesh_get_vendor_capabilities(String provider);
}
