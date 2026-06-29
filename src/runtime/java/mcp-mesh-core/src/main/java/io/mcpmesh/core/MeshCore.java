package io.mcpmesh.core;

import jnr.ffi.LibraryLoader;
import jnr.ffi.Pointer;
import jnr.ffi.annotations.Delegate;
import jnr.ffi.annotations.Encoding;
import jnr.ffi.byref.PointerByReference;

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

    // ==========================================================================
    // MeshJob Functions (Phase 1 — see MESHJOB_DESIGN.org)
    // ==========================================================================
    //
    // All MeshJob C-ABI functions return int32:
    //   * 0  = success
    //   * negative (typically -1) = error; call mesh_last_error() for details
    // String outputs are written via PointerByReference out-parameters; caller
    // frees with mesh_free_string. Opaque handles are owned by Java and must
    // be freed with the matching mesh_*_free function (or leaked).
    //
    // Mirrors:
    //   * jobs_py.rs (PyO3 bindings — Python SDK)
    //   * jobs_napi.rs (napi-rs bindings — TypeScript SDK)
    // The C ABI is the JNR-FFI consumption point.

    // ---- JobController (producer-side) ---------------------------------------

    /**
     * Construct a JobController bound to (jobId, instanceId) against the
     * given registryUrl. Spawns a per-controller background batching tick so
     * mid-flight updateProgress calls reach the registry on the configured
     * cadence (default 2s); the tick is torn down with a final flush when
     * the handle is freed via mesh_job_controller_free.
     *
     * @param jobId       Job UUID this controller is bound to
     * @param instanceId  Instance ID submitting deltas to the registry
     * @param registryUrl Registry base URL
     * @param outHandle   Out-param: receives the opaque handle on success
     * @return 0 on success, -1 on error (see mesh_last_error)
     */
    int mesh_job_controller_new(String jobId, String instanceId, String registryUrl, PointerByReference outHandle);

    /**
     * Enqueue a progress update. Coalesces with any prior pending progress
     * for this job — only the latest survives the next batch flush.
     *
     * @param handle  Controller handle from mesh_job_controller_new
     * @param progress Progress value (typically 0.0..1.0)
     * @param message Optional progress message (may be null)
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_update_progress(Pointer handle, double progress, String message);

    /**
     * Mark the job complete with the given result (JSON-encoded). Flushes
     * immediately.
     *
     * @param handle     Controller handle
     * @param resultJson JSON string encoding the job result
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_complete(Pointer handle, String resultJson);

    /**
     * Mark the job failed with the given error reason. Flushes immediately.
     *
     * @param handle Controller handle
     * @param error  Error reason (free-form string)
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_fail(Pointer handle, String error);

    /**
     * Voluntarily release the lease so a peer replica can re-claim and
     * retry (issue #895). Used by the Java dispatch wrapper when a
     * {@code task=true} handler raises a {@link io.mcpmesh.MeshTool#retryOn()}-
     * matched exception. The registry resets {@code owner_instance_id} on
     * receipt so a peer replica picks up the row within ~5s.
     *
     * <p>Note: release does NOT increment {@code attempt_count} — the claim
     * that picked the row up already counted this attempt; the next claim
     * will count the next attempt. Marks terminal locally before the backend
     * call to fence racing progress updates from the now-defunct attempt.
     *
     * @param handle Controller handle
     * @param reason Optional reason (may be null or empty for "no reason given")
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_release_lease(Pointer handle, String reason);

    /**
     * Transition the job to {@code input_required}, signalling the consumer
     * that the handler is blocked awaiting an external answer. STATUS-ONLY:
     * posts the {@code input_required} delta (with {@code prompt} carried on
     * the existing {@code progress_message} field) and returns once posted —
     * it does NOT await the answer. Compose it with the event primitives for
     * request-and-await: call {@code mesh_job_controller_request_input(prompt)},
     * then park on {@code mesh_job_controller_recv_event(["answer"])}; an
     * external party answers via {@code mesh_job_proxy_send_event}; the handler
     * resumes and calls {@code mesh_job_controller_complete}.
     *
     * <p>Flushes IMMEDIATELY (not via the coalescing batch tick) because the
     * consumer is blocked on this control-plane transition. NON-terminal: the
     * handler keeps running; complete / fail exit {@code input_required}.
     *
     * @param handle Controller handle
     * @param prompt Optional prompt (may be null for "no prompt")
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_request_input(Pointer handle, String prompt);

    /**
     * Whether complete / fail has already been called on this controller.
     *
     * @param handle Controller handle
     * @return 1 if terminal, 0 if not, -1 on error
     */
    int mesh_job_controller_is_terminal(Pointer handle);

    /**
     * Whether the cancel token bound to this controller's job in the
     * process-wide cancel registry has been fired. Returns 0 (not cancelled)
     * when the job is not currently registered (no mesh_run_as_job scope
     * active). Used by Java fixtures whose blocking primitives (e.g.
     * Thread.sleep) cannot be interrupted by a Tokio cancel token firing —
     * the fixture polls this between sleep intervals so a mid-flight cancel
     * can break out instead of running to natural completion. Distinct from
     * mesh_job_controller_is_terminal: terminal reflects local
     * complete/fail/release intent; cancelled reflects an external cancel
     * signal (HTTP route, deadline trip, etc.).
     *
     * @param handle Controller handle
     * @return 1 if cancel token fired, 0 if not (or job not registered), -1 on error
     */
    int mesh_job_controller_is_cancelled(Pointer handle);

    /**
     * Wait for the next event posted to this job's event channel
     * (mirror of {@code JobController::recv_event} in the Rust core,
     * issue #1032). Returns the event as a JSON string written to
     * outEventJson; on a clean timeout writes a null pointer and
     * returns 0.
     *
     * <p>The C ABI cannot pass a nullable double, so {@code timeoutSecs}
     * uses a negative-sentinel convention: pass a negative value (e.g.
     * {@code -1.0}) to express "no timeout" (mirrors Java's
     * {@code Optional<Duration>::empty()} on the wrapper). NaN /
     * Infinity / finite overflow (e.g. {@code Double.MAX_VALUE}) all
     * reject with -1.
     *
     * @param handle         Controller handle
     * @param typesJson      Optional JSON array of event-type strings to
     *                       filter on (e.g. {@code ["signal","cancel"]});
     *                       null or a JSON {@code null} means "all types"
     * @param timeoutSecs    Wall-clock timeout in seconds; negative means
     *                       "no timeout" (block until event arrives or
     *                       cancellation fires)
     * @param outEventJson   Out-param: receives the event JSON string
     *                       (caller frees via mesh_free_string), or
     *                       NULL on clean timeout
     * @return 0 on success (event delivered OR clean timeout — distinguish
     *         via whether {@code outEventJson} carries a non-null pointer),
     *         -1 on invalid args, -2 on JobNotFound, -3 on other backend
     *         errors (see {@link #mesh_last_error})
     */
    int mesh_job_controller_recv_event(
        Pointer handle, String typesJson, double timeoutSecs, PointerByReference outEventJson);

    /**
     * Read the job ID this controller is bound to.
     *
     * @param handle    Controller handle
     * @param outJobId  Out-param: receives the job-id string (caller frees via mesh_free_string)
     * @return 0 on success, -1 on error
     */
    int mesh_job_controller_job_id(Pointer handle, PointerByReference outJobId);

    /**
     * Free a JobController handle returned by mesh_job_controller_new.
     * Drops the inner controller AND the background batching tick (which
     * triggers a final flush of any pending deltas).
     *
     * @param handle Controller handle (may be null)
     */
    void mesh_job_controller_free(Pointer handle);

    // ---- JobProxy (consumer-side) --------------------------------------------

    /**
     * Submit a new job via the registry and return a JobProxy handle.
     *
     * @param argsJson  JSON object encoding SubmitJobArgs (see jobs_ffi.rs)
     * @param outHandle Out-param: receives the opaque proxy handle on success
     * @return 0 on success, -1 on error
     */
    int mesh_submit_job(String argsJson, PointerByReference outHandle);

    /**
     * Construct a JobProxy bound to a known jobId + registryUrl. Normally
     * callers obtain a proxy via mesh_submit_job rather than constructing
     * one directly.
     *
     * @param jobId       Job UUID
     * @param registryUrl Registry base URL
     * @param outHandle   Out-param: receives the opaque proxy handle on success
     * @return 0 on success, -1 on error
     */
    int mesh_job_proxy_new(String jobId, String registryUrl, PointerByReference outHandle);

    /**
     * Read the job id this proxy is bound to.
     *
     * @param handle   Proxy handle
     * @param outJobId Out-param: receives the job-id string (caller frees via mesh_free_string)
     * @return 0 on success, -1 on error
     */
    int mesh_job_proxy_job_id(Pointer handle, PointerByReference outJobId);

    /**
     * Read the latest job state from the registry (single GET). The full Job
     * row is serialized as JSON.
     *
     * @param handle      Proxy handle
     * @param outJobJson  Out-param: receives the JSON string (caller frees via mesh_free_string)
     * @return 0 on success, -1 on error
     */
    int mesh_job_proxy_status(Pointer handle, PointerByReference outJobJson);

    /**
     * Poll until the job reaches a terminal state. On success writes the
     * job result (JSON-encoded) to outResultJson.
     *
     * @param handle         Proxy handle
     * @param timeoutSecs    Wall-clock timeout (negative = no timeout)
     * @param outResultJson  Out-param: receives the JSON string (caller frees via mesh_free_string)
     * @return 0 on success, -1 on error
     */
    int mesh_job_proxy_wait(Pointer handle, double timeoutSecs, PointerByReference outResultJson);

    /**
     * Request cancellation. The registry forwards the signal to the owner
     * replica when alive.
     *
     * @param handle Proxy handle
     * @param reason Optional cancel reason (may be null)
     * @return 0 on success, -1 on error
     */
    int mesh_job_proxy_cancel(Pointer handle, String reason);

    /**
     * Post an event into this job's event channel (mirror of
     * {@code JobProxy::send_event} in the Rust core, issue #1032).
     * The running handler (inside a {@code task=true} job) will see
     * the event on its next {@code recvEvent} call — or wake immediately
     * if it's currently long-polling.
     *
     * @param handle           Proxy handle
     * @param eventType        Event-type tag (e.g. {@code "signal"},
     *                         {@code "user_input"}) — required, non-null
     * @param payloadJson      Optional JSON-encoded payload (object,
     *                         array, or scalar); null is treated as an
     *                         empty JSON object {@code {}} matching the
     *                         Python {@code payload=None} normalization
     * @param outReceiptJson   Out-param: receives the receipt JSON
     *                         string {@code {job_id, seq, created_at}}
     *                         (caller frees via mesh_free_string)
     * @return 0 on success, -1 on invalid args, -2 on JobNotFound,
     *         -3 on JobTerminal (job already in a terminal state),
     *         -4 on other backend errors (see {@link #mesh_last_error}).
     *         Distinct error codes let the Java SDK map -2 and -3 to
     *         typed {@code JobNotFoundException} /
     *         {@code JobTerminalException}.
     */
    int mesh_job_proxy_send_event(
        Pointer handle, String eventType, String payloadJson, PointerByReference outReceiptJson);

    /**
     * Fetch a single batch of events from this job's event log with
     * {@code seq > after}, optionally filtered by {@code types}. Java's
     * {@code MeshJobs.subscribeEvents} blocking iterator is built on
     * top of this primitive — callers manage their own cursor between
     * calls. Mirror of {@code JobProxy::list_events} in the Rust core.
     *
     * <p>The result is a JSON envelope
     * {@code {"events":[...],"next_after":N}} written to
     * {@code outEnvelopeJson}. {@code next_after} is the registry-
     * supplied watermark the caller should feed back as {@code after}
     * on the next call so empty pages caused by server-side
     * {@code types} filtering still advance the cursor.
     *
     * <p>The C ABI cannot pass a nullable double, so {@code timeoutSecs}
     * uses the same negative-sentinel convention as
     * {@link #mesh_job_controller_recv_event}: pass a negative value
     * (e.g. {@code -1.0}) to express "no timeout"; NaN / Infinity /
     * finite overflow all reject with -1.
     *
     * @param handle             Proxy handle
     * @param after              Cursor — only events with
     *                           {@code seq > after} are returned. Pass
     *                           {@code 0} for "from the beginning".
     * @param typesJson          Optional JSON array of event-type
     *                           strings to filter on (e.g.
     *                           {@code ["work","progress"]}); null or
     *                           a JSON {@code null} means "all types"
     * @param timeoutSecs        Long-poll budget in seconds; negative
     *                           means "no timeout" (single immediate
     *                           read; rarely needed)
     * @param outEnvelopeJson    Out-param: receives the envelope JSON
     *                           string (caller frees via
     *                           {@code mesh_free_string})
     * @return 0 on success (envelope written; events may be empty),
     *         -1 on invalid args, -2 on JobNotFound, -3 on other
     *         backend errors (see {@link #mesh_last_error}).
     *         Distinct error codes let the Java SDK map -2 to a typed
     *         {@code JobNotFoundException}.
     */
    int mesh_job_proxy_list_events(
        Pointer handle,
        long after,
        String typesJson,
        double timeoutSecs,
        PointerByReference outEnvelopeJson);

    /**
     * Free a JobProxy handle returned by mesh_submit_job / mesh_job_proxy_new.
     *
     * @param handle Proxy handle (may be null)
     */
    void mesh_job_proxy_free(Pointer handle);

    // ---- Context + cancel registry ------------------------------------------

    /**
     * Snapshot of the active job context on the current Rust task, or null
     * if no job is in scope. Writes a JSON object of shape
     * {@code {"job_id": str, "deadline_secs_remaining": int|null}} or
     * a null pointer.
     *
     * <p>Note: this reflects the Rust task-local context only. Java code
     * should read its own ThreadLocal mirror (see {@link io.mcpmesh.JobContext}
     * once added).
     *
     * @param outSnapshotJson Out-param: receives the JSON string or null pointer
     * @return 0 on success, -1 on error
     */
    int mesh_current_job(PointerByReference outSnapshotJson);

    /**
     * Compute the X-Mesh-Job-Id / X-Mesh-Timeout header values for the
     * active Rust-side job context, if any. Writes a JSON object or null.
     *
     * @param outHeadersJson Out-param: receives the JSON string or null pointer
     * @return 0 on success, -1 on error
     */
    int mesh_inject_job_headers(PointerByReference outHeadersJson);

    /**
     * Fire the cancel token registered for jobId in the process-wide cancel
     * registry, if any.
     *
     * @param jobId Job UUID
     * @return 1 if a token was found and fired, 0 if no active job, -1 on error
     */
    int mesh_cancel_active_job(String jobId);

    /**
     * Block until the cancel token bound for {@code jobId} in the process-
     * wide cancel registry fires, OR until the job is unregistered naturally
     * (ended without cancel). Resolves immediately if the job is not
     * currently registered.
     *
     * <p>Used by {@link io.mcpmesh.spring.McpHttpClient} via a watcher
     * thread wrapped in {@link java.util.concurrent.CompletableFuture#runAsync}
     * to abort in-flight outbound HTTP calls when the producer's job is
     * cancelled mid-flight. Mirror of the TypeScript SDK's
     * {@code awaitJobCancel(jobId)} napi (PR #897) — same primitive, sync
     * because JNR-FFI doesn't expose async returns.
     *
     * <p>This call BLOCKS the calling thread until the token fires; callers
     * must invoke it on a dedicated daemon thread (e.g., via
     * {@link java.util.concurrent.CompletableFuture#runAsync}). The watcher
     * future MUST be cancelled in a {@code finally} block so it doesn't leak
     * if the outbound call completes naturally.
     *
     * @param jobId the job ID whose cancel token to await
     * @return 0 on success (token resolved or job unregistered), -1 on
     *         invalid input (see {@link #mesh_last_error})
     */
    int mesh_await_job_cancel(String jobId);

    /**
     * Read-only probe: has the cancel token for {@code jobId} fired?
     *
     * <p>{@link #mesh_await_job_cancel} resolves on BOTH explicit cancel and
     * natural job end without telling the caller which happened. Callers that
     * must distinguish (the outbound-call cancel watcher in
     * {@code McpHttpClient} — a natural-end wake must NOT abort still-healthy
     * in-flight calls) call this immediately after the await returns: on
     * explicit cancel the registry entry is still present with its token
     * fired (returns 1); on natural end the entry was already removed
     * (returns 0). Never fires the token itself, so it is safe to call in
     * races with a re-claim of the same job id.
     *
     * @param jobId the job ID to probe
     * @return 1 if an entry is registered and its cancel token has fired,
     *         0 otherwise (not registered, or registered but not cancelled),
     *         -1 on invalid input (see {@link #mesh_last_error})
     */
    int mesh_job_cancel_fired(String jobId);

    /**
     * Callback type for {@link MeshCore#mesh_run_as_job}. The callback is
     * invoked synchronously from the FFI runtime's block_on; its int return
     * value propagates as mesh_run_as_job's return value.
     */
    interface RunAsJobCallback {
        @Delegate
        int invoke(Pointer userData);
    }

    /**
     * Run a Java-provided callback inside a fresh run_as_job scope so the
     * cancel-registry entry under the snapshot's job_id is bound for the
     * duration of the callback. snapshotJson encodes
     * {@code {"job_id": str, "deadline_secs": number|null}}.
     *
     * <p>The Rust task-local context is NOT visible to Java code in the
     * callback — Java must mirror it in its own ThreadLocal. The Rust side
     * handles cancel-registry binding (so {@code POST /jobs/{id}/cancel}
     * fires the in-flight cancel token) and header injection on Rust-
     * originated outbound work.
     *
     * @param snapshotJson Job context snapshot JSON
     * @param callback     Java callback invoked inside the scope
     * @param userData     Opaque pointer passed back to the callback (may be null)
     * @return The callback's return value (0 = success, non-zero = caller-defined),
     *         or -1 if the snapshot JSON is invalid (see mesh_last_error)
     */
    int mesh_run_as_job(String snapshotJson, RunAsJobCallback callback, Pointer userData);
}
