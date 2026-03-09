package io.mcpmesh.spring;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TraceInfo;
import io.mcpmesh.types.MeshToolCallException;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.FileInputStream;
import java.io.IOException;
import java.lang.reflect.Type;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.spec.InvalidKeySpecException;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;

/**
 * HTTP client for calling remote MCP servers.
 *
 * <p>Implements the MCP JSON-RPC protocol for tool invocation.
 */
public class McpHttpClient {

    private static final Logger log = LoggerFactory.getLogger(McpHttpClient.class);
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;

    public McpHttpClient() {
        this(MeshObjectMappers.create());
    }

    public McpHttpClient(ObjectMapper objectMapper) {
        OkHttpClient.Builder builder = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS);

        MeshTlsConfig tlsConfig = MeshTlsConfig.get();
        if (tlsConfig.isEnabled() && tlsConfig.getCertPath() != null && tlsConfig.getKeyPath() != null) {
            try {
                SSLContext sslContext = buildSslContext(tlsConfig);
                builder.sslSocketFactory(sslContext.getSocketFactory(), buildTrustManager(tlsConfig));
                // Skip hostname verification: --tls-auto certs have SANs for
                // 127.0.0.1/::1 only; agents may bind to other IPs in K8s.
                builder.hostnameVerifier((hostname, session) -> true);
                log.info("OkHttpClient configured with mTLS (mode={})", tlsConfig.getMode());
            } catch (Exception e) {
                log.error("Failed to configure mTLS for OkHttpClient — outgoing proxy calls will not use mTLS", e);
            }
        }

        this.httpClient = builder.build();
        this.objectMapper = objectMapper;
    }

    /**
     * Call a tool on a remote MCP server.
     *
     * @param endpoint     The MCP server endpoint (e.g., http://localhost:9000)
     * @param functionName The tool/function name to call
     * @param params       Parameters to pass to the tool
     * @param <T>          Expected return type
     * @return The tool result
     * @throws MeshToolCallException if the call fails
     */
    public <T> T callTool(String endpoint, String functionName, Map<String, Object> params) {
        return callTool(endpoint, functionName, params, null);
    }

    /**
     * Call a tool on a remote MCP server with typed response deserialization.
     *
     * @param endpoint     The MCP server endpoint (e.g., http://localhost:9000)
     * @param functionName The tool/function name to call
     * @param params       Parameters to pass to the tool
     * @param returnType   The expected return type for deserialization (null for dynamic typing)
     * @param <T>          Expected return type
     * @return The tool result, deserialized to the specified type
     * @throws MeshToolCallException if the call fails
     */
    @SuppressWarnings("unchecked")
    public <T> T callTool(String endpoint, String functionName, Map<String, Object> params, Type returnType) {
        return callTool(endpoint, functionName, params, returnType, null);
    }

    /**
     * Call a tool on a remote MCP server with typed response deserialization and per-call headers.
     *
     * <p>Per-call headers are filtered by the MCP_MESH_PROPAGATE_HEADERS allowlist
     * and merge on top of session-level propagated headers (per-call wins).
     *
     * @param endpoint     The MCP server endpoint (e.g., http://localhost:9000)
     * @param functionName The tool/function name to call
     * @param params       Parameters to pass to the tool
     * @param returnType   The expected return type for deserialization (null for dynamic typing)
     * @param extraHeaders Per-call headers to inject into the downstream request (may be null)
     * @param <T>          Expected return type
     * @return The tool result, deserialized to the specified type
     * @throws MeshToolCallException if the call fails
     */
    @SuppressWarnings("unchecked")
    public <T> T callTool(String endpoint, String functionName, Map<String, Object> params, Type returnType, Map<String, String> extraHeaders) {
        try {
            // Build MCP tools/call request
            // Use /mcp endpoint (stateless transport) - not /mcp/v1
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            // Get current trace context for propagation
            TraceInfo traceInfo = TraceContext.get();

            // Inject trace context into arguments for TypeScript agents
            // (FastMCP doesn't expose HTTP headers to tool handlers)
            Map<String, Object> argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
            if (traceInfo != null) {
                argsWithTrace.put("_trace_id", traceInfo.getTraceId());
                if (traceInfo.getSpanId() != null) {
                    argsWithTrace.put("_parent_span", traceInfo.getSpanId());
                }
                log.trace("Injecting trace context into args: trace={}, parent={}",
                    traceInfo.getTraceId().substring(0, 8),
                    traceInfo.getSpanId() != null ? traceInfo.getSpanId().substring(0, 8) : "null");
            }

            // Build merged headers: session propagated + per-call (per-call wins, filtered by allowlist)
            Map<String, String> propagatedHeaders = TraceContext.getPropagatedHeaders();
            Map<String, String> mergedHeaders = new LinkedHashMap<>(propagatedHeaders);
            if (extraHeaders != null) {
                for (Map.Entry<String, String> entry : extraHeaders.entrySet()) {
                    if (TraceContext.matchesPropagateHeader(entry.getKey())) {
                        mergedHeaders.put(entry.getKey().toLowerCase(), entry.getValue());
                    }
                }
            }
            if (!mergedHeaders.isEmpty()) {
                argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                log.trace("Injecting {} merged headers into args", mergedHeaders.size());
            }

            Map<String, Object> request = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "method", "tools/call",
                "params", Map.of(
                    "name", functionName,
                    "arguments", argsWithTrace
                )
            );

            String requestBody = objectMapper.writeValueAsString(request);
            log.debug("Calling tool {} at {}: {}", functionName, url, requestBody);

            // Build request with trace headers for Python/Java agents
            Request.Builder requestBuilder = new Request.Builder()
                .url(url)
                .post(RequestBody.create(requestBody, JSON))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream");

            // Inject trace context into HTTP headers
            if (traceInfo != null) {
                requestBuilder.header("X-Trace-ID", traceInfo.getTraceId());
                if (traceInfo.getSpanId() != null) {
                    requestBuilder.header("X-Parent-Span", traceInfo.getSpanId());
                }
                log.trace("Injecting trace headers: X-Trace-ID={}, X-Parent-Span={}",
                    traceInfo.getTraceId().substring(0, 8),
                    traceInfo.getSpanId() != null ? traceInfo.getSpanId().substring(0, 8) : "null");
            }

            // Inject merged headers as HTTP headers (propagated + per-call)
            for (Map.Entry<String, String> entry : mergedHeaders.entrySet()) {
                requestBuilder.header(entry.getKey(), entry.getValue());
            }

            Request httpRequest = requestBuilder.build();

            try (Response response = httpClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful()) {
                    throw new MeshToolCallException(functionName, functionName,
                        "HTTP " + response.code() + ": " + response.message());
                }

                ResponseBody body = response.body();
                if (body == null) {
                    throw new MeshToolCallException(functionName, functionName, "Empty response body");
                }

                String responseBody = body.string();
                log.debug("Tool response: {}", responseBody);

                // Handle SSE (Server-Sent Events) format from MCP servers
                // SSE format: "event: message\nid: ...\ndata: {JSON}\n\n"
                String jsonContent = responseBody;
                if (responseBody.startsWith("event:") || responseBody.contains("\ndata: ")) {
                    jsonContent = extractJsonFromSse(responseBody);
                    log.debug("Extracted JSON from SSE: {}", jsonContent);
                }

                // Parse JSON-RPC response
                JsonNode responseNode = objectMapper.readTree(jsonContent);

                if (responseNode.has("error")) {
                    JsonNode error = responseNode.get("error");
                    String errorMessage = error.has("message") ?
                        error.get("message").asText() : "Unknown error";
                    throw new MeshToolCallException(functionName, functionName, errorMessage);
                }

                if (responseNode.has("result")) {
                    JsonNode result = responseNode.get("result");

                    // Handle MCP content array response - extract the text content
                    String textContent = null;
                    if (result.has("content") && result.get("content").isArray()) {
                        JsonNode content = result.get("content");
                        if (content.size() > 0) {
                            JsonNode firstContent = content.get(0);
                            if (firstContent.has("text")) {
                                textContent = firstContent.get("text").asText();
                            }
                        }
                    }

                    // Check if the tool call returned an error
                    if (result.has("isError") && result.get("isError").asBoolean()) {
                        String errorText = textContent != null ? textContent : "Unknown tool error";
                        throw new MeshToolCallException(functionName, functionName, errorText);
                    }

                    // Deserialize based on return type
                    return deserializeResult(textContent, result, returnType);
                }

                return null;
            }
        } catch (MeshToolCallException e) {
            throw e;
        } catch (IOException e) {
            throw new MeshToolCallException(functionName, functionName, e);
        } catch (Exception e) {
            throw new MeshToolCallException(functionName, functionName, e);
        }
    }

    /**
     * Call a tool asynchronously.
     */
    public <T> CompletableFuture<T> callToolAsync(String endpoint, String functionName,
                                                   Map<String, Object> params) {
        return CompletableFuture.supplyAsync(() -> callTool(endpoint, functionName, params));
    }

    /**
     * List available tools on a remote MCP server.
     */
    public JsonNode listTools(String endpoint) {
        try {
            // Use /mcp endpoint (stateless transport)
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            Map<String, Object> request = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "method", "tools/list",
                "params", Map.of()
            );

            String requestBody = objectMapper.writeValueAsString(request);

            Request httpRequest = new Request.Builder()
                .url(url)
                .post(RequestBody.create(requestBody, JSON))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream")
                .build();

            try (Response response = httpClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful()) {
                    log.warn("Failed to list tools at {}: HTTP {}", endpoint, response.code());
                    return null;
                }

                ResponseBody body = response.body();
                if (body == null) {
                    return null;
                }

                JsonNode responseNode = objectMapper.readTree(body.string());
                return responseNode.has("result") ? responseNode.get("result") : null;
            }
        } catch (Exception e) {
            log.warn("Failed to list tools at {}: {}", endpoint, e.getMessage());
            return null;
        }
    }

    /**
     * Deserialize the result to the specified type.
     *
     * @param textContent The extracted text content from MCP response (may be null)
     * @param resultNode  The result JsonNode from MCP response
     * @param returnType  The target type for deserialization (null for dynamic typing)
     * @return The deserialized result
     */
    @SuppressWarnings("unchecked")
    private <T> T deserializeResult(String textContent, JsonNode resultNode, Type returnType) {
        try {
            // If we have text content, try to deserialize it
            if (textContent != null) {
                if (returnType != null) {
                    Class<?> rawType = getRawType(returnType);

                    // Handle primitive wrappers and String specially
                    if (rawType == String.class) {
                        return (T) textContent;
                    } else if (rawType == Integer.class || rawType == int.class) {
                        return (T) Integer.valueOf(textContent);
                    } else if (rawType == Long.class || rawType == long.class) {
                        return (T) Long.valueOf(textContent);
                    } else if (rawType == Double.class || rawType == double.class) {
                        return (T) Double.valueOf(textContent);
                    } else if (rawType == Boolean.class || rawType == boolean.class) {
                        return (T) Boolean.valueOf(textContent);
                    } else {
                        // Try to parse as JSON for complex types
                        return objectMapper.readValue(textContent,
                            objectMapper.getTypeFactory().constructType(returnType));
                    }
                } else {
                    // No type specified - try JSON parsing, fallback to string
                    try {
                        return (T) objectMapper.readValue(textContent,
                            new TypeReference<Map<String, Object>>() {});
                    } catch (Exception e) {
                        return (T) textContent;
                    }
                }
            }

            // No text content - deserialize the result node directly
            if (returnType != null) {
                return objectMapper.treeToValue(resultNode,
                    objectMapper.getTypeFactory().constructType(returnType));
            } else {
                return objectMapper.treeToValue(resultNode, (Class<T>) Object.class);
            }
        } catch (Exception e) {
            if (returnType != null) {
                // When returnType is explicitly provided, propagate the error
                // rather than silently returning the wrong type
                throw new RuntimeException(
                    "Failed to deserialize result to " + returnType + ": " + e.getMessage(), e);
            }
            log.warn("Failed to deserialize result: {}", e.getMessage());
            // Fallback to string only when no type was specified
            if (textContent != null) {
                return (T) textContent;
            }
            throw new RuntimeException("Failed to deserialize result", e);
        }
    }

    /**
     * Get the raw type from a potentially parameterized type.
     */
    private Class<?> getRawType(Type type) {
        if (type instanceof Class<?>) {
            return (Class<?>) type;
        } else if (type instanceof java.lang.reflect.ParameterizedType pt) {
            return (Class<?>) pt.getRawType();
        }
        return Object.class;
    }

    /**
     * Extract JSON content from SSE (Server-Sent Events) format.
     *
     * <p>SSE format looks like:
     * <pre>
     * event: message
     * id: some-id
     * data: {"jsonrpc":"2.0","id":1,"result":{...}}
     * </pre>
     *
     * @param sseContent The SSE-formatted response
     * @return The extracted JSON content from the data: line
     */
    private String extractJsonFromSse(String sseContent) {
        // Find all data: lines and concatenate them (for multi-line data)
        StringBuilder jsonBuilder = new StringBuilder();
        for (String line : sseContent.split("\n")) {
            if (line.startsWith("data: ")) {
                jsonBuilder.append(line.substring(6)); // Remove "data: " prefix
            } else if (line.startsWith("data:")) {
                jsonBuilder.append(line.substring(5)); // Handle "data:" without space
            }
        }
        String json = jsonBuilder.toString().trim();
        return json.isEmpty() ? sseContent : json;
    }

    private static SSLContext buildSslContext(MeshTlsConfig config) throws Exception {
        KeyStore keyStore = KeyStore.getInstance("PKCS12");
        keyStore.load(null, null);

        CertificateFactory cf = CertificateFactory.getInstance("X.509");

        Certificate[] certChain;
        try (FileInputStream certIs = new FileInputStream(config.getCertPath())) {
            Collection<? extends Certificate> certs = cf.generateCertificates(certIs);
            certChain = certs.toArray(new Certificate[0]);
        }

        byte[] keyBytes = Files.readAllBytes(Paths.get(config.getKeyPath()));
        // Strip PEM headers/footers using regex to avoid false positive from secret detection hooks
        String keyPem = new String(keyBytes)
            .replaceAll("-----BEGIN [A-Z ]+-----", "")
            .replaceAll("-----END [A-Z ]+-----", "")
            .replaceAll("\\s", "");
        byte[] decoded = Base64.getDecoder().decode(keyPem);
        PKCS8EncodedKeySpec keySpec = new PKCS8EncodedKeySpec(decoded);

        PrivateKey privateKey;
        try {
            privateKey = KeyFactory.getInstance("RSA").generatePrivate(keySpec);
        } catch (InvalidKeySpecException e) {
            privateKey = KeyFactory.getInstance("EC").generatePrivate(keySpec);
        }

        keyStore.setKeyEntry("mesh-client", privateKey, new char[0], certChain);

        KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        kmf.init(keyStore, new char[0]);

        TrustManager[] trustManagers = null;
        if (config.getCaPath() != null) {
            KeyStore trustStore = KeyStore.getInstance("PKCS12");
            trustStore.load(null, null);
            try (FileInputStream caIs = new FileInputStream(config.getCaPath())) {
                int i = 0;
                for (Certificate cert : cf.generateCertificates(caIs)) {
                    trustStore.setCertificateEntry("mesh-ca-" + i++, cert);
                }
            }
            TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(trustStore);
            trustManagers = tmf.getTrustManagers();
        }

        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(kmf.getKeyManagers(), trustManagers, null);
        return sslContext;
    }

    private static X509TrustManager buildTrustManager(MeshTlsConfig config) throws Exception {
        if (config.getCaPath() != null) {
            CertificateFactory cf = CertificateFactory.getInstance("X.509");
            KeyStore trustStore = KeyStore.getInstance("PKCS12");
            trustStore.load(null, null);
            try (FileInputStream caIs = new FileInputStream(config.getCaPath())) {
                int i = 0;
                for (Certificate cert : cf.generateCertificates(caIs)) {
                    trustStore.setCertificateEntry("mesh-ca-" + i++, cert);
                }
            }
            TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(trustStore);
            for (TrustManager tm : tmf.getTrustManagers()) {
                if (tm instanceof X509TrustManager) {
                    return (X509TrustManager) tm;
                }
            }
        }
        TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        tmf.init((KeyStore) null);
        for (TrustManager tm : tmf.getTrustManagers()) {
            if (tm instanceof X509TrustManager) {
                return (X509TrustManager) tm;
            }
        }
        throw new IllegalStateException("No X509TrustManager found");
    }

    /**
     * Close the HTTP client and release resources.
     */
    public void close() {
        httpClient.dispatcher().executorService().shutdown();
        httpClient.connectionPool().evictAll();
    }
}
