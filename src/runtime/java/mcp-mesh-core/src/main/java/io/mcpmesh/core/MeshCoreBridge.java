package io.mcpmesh.core;

import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.function.Function;
import java.util.function.ToIntFunction;

/**
 * Static bridge to Rust core utility functions.
 *
 * <p>Provides Java wrappers around the JNR-FFI native calls, handling
 * Pointer-to-String conversion and memory management (mesh_free_string).
 *
 * <p>All methods are thread-safe. The native library is loaded lazily on first use.
 * If the native library cannot be loaded or a native function fails, the error
 * propagates immediately (fail-fast). There are no Java fallbacks.
 *
 * <p>Usage:
 * <pre>
 * String json = MeshCoreBridge.extractJson(responseText);
 * String traceId = MeshCoreBridge.generateTraceId();
 * String prompt = MeshCoreBridge.formatSystemPrompt("anthropic", basePrompt, ...);
 * </pre>
 */
public final class MeshCoreBridge {

    private static final Logger log = LoggerFactory.getLogger(MeshCoreBridge.class);

    private static volatile MeshCore core;
    private static volatile boolean loaded = false;

    private MeshCoreBridge() {
    }

    // =========================================================================
    // Response Parsing
    // =========================================================================

    /**
     * Extract JSON from text that may contain markdown code fences or mixed content.
     *
     * @param text The text to extract JSON from
     * @return Extracted JSON string, or null if no JSON found
     */
    public static String extractJson(String text) {
        if (text == null) return null;
        return callNativeString(c -> c.mesh_extract_json(text));
    }

    /**
     * Strip markdown code fences from text.
     *
     * @param text The text to strip
     * @return Stripped text, or null on error
     */
    public static String stripCodeFences(String text) {
        if (text == null) return null;
        return callNativeString(c -> c.mesh_strip_code_fences(text));
    }

    // =========================================================================
    // Schema Normalization
    // =========================================================================

    /**
     * Make a JSON schema strict.
     *
     * @param schemaJson JSON schema string
     * @param addAllRequired true to add all properties to required array
     * @return Strict schema JSON, or null on error
     */
    public static String makeSchemaStrict(String schemaJson, boolean addAllRequired) {
        if (schemaJson == null) return null;
        return callNativeString(c -> c.mesh_make_schema_strict(schemaJson, addAllRequired ? 1 : 0));
    }

    /**
     * Sanitize a JSON schema by removing unsupported validation keywords.
     *
     * @param schemaJson JSON schema string
     * @return Sanitized schema JSON, or null on error
     */
    public static String sanitizeSchema(String schemaJson) {
        if (schemaJson == null) return null;
        return callNativeString(c -> c.mesh_sanitize_schema(schemaJson));
    }

    /**
     * Detect if a schema contains media-related parameters.
     *
     * @param schemaJson JSON schema string
     * @return true if media params detected, false if not detected
     */
    public static boolean detectMediaParams(String schemaJson) {
        if (schemaJson == null) return false;
        return callNativeInt(c -> c.mesh_detect_media_params(schemaJson)) == 1;
    }

    /**
     * Check if a schema is simple (few fields, no nesting).
     *
     * @param schemaJson JSON schema string
     * @return true if simple (defaults to true for null input)
     */
    public static boolean isSimpleSchema(String schemaJson) {
        if (schemaJson == null) return true;
        return callNativeInt(c -> c.mesh_is_simple_schema(schemaJson)) == 1;
    }

    // =========================================================================
    // Trace Context
    // =========================================================================

    /**
     * Generate an OpenTelemetry-compliant trace ID (32-char hex).
     *
     * @return Trace ID, or null on error
     */
    public static String generateTraceId() {
        return callNativeString(MeshCore::mesh_generate_trace_id);
    }

    /**
     * Generate an OpenTelemetry-compliant span ID (16-char hex).
     *
     * @return Span ID, or null on error
     */
    public static String generateSpanId() {
        return callNativeString(MeshCore::mesh_generate_span_id);
    }

    /**
     * Check if a header name matches any prefix in the propagation allowlist.
     *
     * @param headerName Header name to check
     * @param allowlistCsv Comma-separated list of allowed header prefixes
     * @return true if matches, false if not detected
     */
    public static boolean matchesPropagateHeader(String headerName, String allowlistCsv) {
        if (headerName == null || allowlistCsv == null) return false;
        return callNativeInt(c -> c.mesh_matches_propagate_header(headerName, allowlistCsv)) == 1;
    }

    /**
     * Inject trace context into tool call arguments.
     *
     * @param argsJson JSON string of tool arguments
     * @param traceId Trace ID to inject
     * @param spanId Span ID to inject
     * @param propagatedHeadersJson JSON of propagated headers (may be null)
     * @return Updated args JSON, or null on error
     */
    public static String injectTraceContext(String argsJson, String traceId, String spanId, String propagatedHeadersJson) {
        if (argsJson == null || traceId == null || spanId == null) return null;
        return callNativeString(c -> c.mesh_inject_trace_context(argsJson, traceId, spanId, propagatedHeadersJson));
    }

    /**
     * Extract trace context from headers and body.
     *
     * @param headersJson JSON string of HTTP headers
     * @param bodyJson JSON string of request body
     * @return JSON with extracted trace context, or null on error
     */
    public static String extractTraceContext(String headersJson, String bodyJson) {
        return callNativeString(c -> c.mesh_extract_trace_context(headersJson, bodyJson));
    }

    /**
     * Filter headers by propagation allowlist.
     *
     * @param headersJson JSON string of headers
     * @param allowlistCsv Comma-separated allowlist
     * @return Filtered headers JSON, or null on error
     */
    public static String filterPropagationHeaders(String headersJson, String allowlistCsv) {
        return callNativeString(c -> c.mesh_filter_propagation_headers(headersJson, allowlistCsv));
    }

    // =========================================================================
    // MCP Client
    // =========================================================================

    /**
     * Parse SSE response text to extract JSON content.
     *
     * @param responseText SSE-formatted response
     * @return Extracted JSON content, or null on error
     */
    public static String parseSseResponse(String responseText) {
        if (responseText == null) return null;
        return callNativeString(c -> c.mesh_parse_sse_response(responseText));
    }

    /**
     * Build a JSON-RPC request string.
     *
     * @param method JSON-RPC method name
     * @param paramsJson JSON parameters
     * @param requestId Request ID
     * @return JSON-RPC request string, or null on error
     */
    public static String buildJsonrpcRequest(String method, String paramsJson, String requestId) {
        if (method == null || paramsJson == null || requestId == null) return null;
        return callNativeString(c -> c.mesh_build_jsonrpc_request(method, paramsJson, requestId));
    }

    /**
     * Generate a unique request ID.
     *
     * @return Request ID string, or null on error
     */
    public static String generateRequestId() {
        return callNativeString(MeshCore::mesh_generate_request_id);
    }

    /**
     * Extract content from a JSON-RPC result node.
     *
     * @param resultJson JSON result string
     * @return Extracted content JSON, or null on error
     */
    public static String extractContent(String resultJson) {
        if (resultJson == null) return null;
        return callNativeString(c -> c.mesh_extract_content(resultJson));
    }

    // =========================================================================
    // Provider
    // =========================================================================

    /**
     * Determine the output mode for a provider.
     *
     * @param provider Vendor name
     * @param isStringType true if return type is String
     * @param hasTools true if tools are present
     * @param overrideMode Optional override mode (may be null)
     * @return Output mode string ("text", "hint", or "strict"), or null on error
     */
    public static String determineOutputMode(String provider, boolean isStringType, boolean hasTools, String overrideMode) {
        if (provider == null) return null;
        return callNativeString(c -> c.mesh_determine_output_mode(provider, isStringType ? 1 : 0, hasTools ? 1 : 0, overrideMode));
    }

    /**
     * Format system prompt with vendor-specific additions.
     *
     * @param provider Vendor name
     * @param basePrompt Base system prompt text
     * @param hasTools true if tools are present
     * @param hasMediaParams true if media parameters are present
     * @param schemaJson Optional JSON schema string (may be null)
     * @param schemaName Optional schema name (may be null)
     * @param outputMode Output mode: "text", "hint", or "strict"
     * @return Complete system prompt, or null on error
     */
    public static String formatSystemPrompt(String provider, String basePrompt, boolean hasTools, boolean hasMediaParams, String schemaJson, String schemaName, String outputMode) {
        if (provider == null || outputMode == null) return null;
        return callNativeString(c -> c.mesh_format_system_prompt(
            provider,
            basePrompt != null ? basePrompt : "",
            hasTools ? 1 : 0,
            hasMediaParams ? 1 : 0,
            schemaJson,
            schemaName,
            outputMode
        ));
    }

    /**
     * Build the response_format object for structured output.
     *
     * @param provider Vendor name
     * @param schemaJson JSON schema string
     * @param schemaName Schema name
     * @param hasTools true if tools are present
     * @return Response format JSON, or null on error
     */
    public static String buildResponseFormat(String provider, String schemaJson, String schemaName, boolean hasTools) {
        if (provider == null || schemaJson == null || schemaName == null) return null;
        return callNativeString(c -> c.mesh_build_response_format(provider, schemaJson, schemaName, hasTools ? 1 : 0));
    }

    /**
     * Get vendor capabilities as JSON.
     *
     * @param provider Vendor name
     * @return Capabilities JSON, or null on error
     */
    public static String getVendorCapabilities(String provider) {
        if (provider == null) return null;
        return callNativeString(c -> c.mesh_get_vendor_capabilities(provider));
    }

    // =========================================================================
    // Internal Helpers
    // =========================================================================

    /**
     * Call a native function that returns a Pointer (string), converting to Java String.
     * Returns null if the native function returns null. Throws on native load/link errors.
     */
    private static String callNativeString(Function<MeshCore, Pointer> nativeCall) {
        MeshCore c = ensureLoaded();
        Pointer result = nativeCall.apply(c);
        if (result == null) return null;
        try {
            return result.getString(0);
        } finally {
            c.mesh_free_string(result);
        }
    }

    /**
     * Call a native function that returns an int.
     * Throws on native load/link errors.
     */
    private static int callNativeInt(ToIntFunction<MeshCore> nativeCall) {
        MeshCore c = ensureLoaded();
        return nativeCall.applyAsInt(c);
    }

    /**
     * Ensure the native library is loaded.
     *
     * @return MeshCore instance (never null)
     * @throws UnsatisfiedLinkError if the native library cannot be loaded
     * @throws RuntimeException if loading fails for any other reason
     */
    private static MeshCore ensureLoaded() {
        if (loaded) {
            if (core == null) {
                throw new UnsatisfiedLinkError("Rust core native library failed to load (previous attempt failed)");
            }
            return core;
        }
        synchronized (MeshCoreBridge.class) {
            if (loaded) {
                if (core == null) {
                    throw new UnsatisfiedLinkError("Rust core native library failed to load (previous attempt failed)");
                }
                return core;
            }
            try {
                core = MeshCore.load();
                log.debug("Rust core native library loaded");
            } finally {
                loaded = true;
            }
            return core;
        }
    }
}
