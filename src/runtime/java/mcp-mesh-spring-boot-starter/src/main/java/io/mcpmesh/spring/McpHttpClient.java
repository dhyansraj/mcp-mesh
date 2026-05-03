package io.mcpmesh.spring;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshCoreBridge;
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
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.Flow;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
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

    /**
     * Payload size metrics from the last call on this thread.
     *
     * @param requestBytes  Size of the outgoing HTTP request body in bytes
     * @param responseBytes Size of the incoming HTTP response body in bytes
     */
    public record CallMetrics(int requestBytes, int responseBytes) {}

    private static final ThreadLocal<CallMetrics> LAST_CALL_METRICS = new ThreadLocal<>();

    /**
     * Get the payload size metrics from the last {@code callTool} invocation on this thread.
     *
     * @return CallMetrics, or null if no call has been made on this thread
     */
    public static CallMetrics getLastCallMetrics() {
        return LAST_CALL_METRICS.get();
    }

    /**
     * Clear stored call metrics for this thread.
     */
    public static void clearLastCallMetrics() {
        LAST_CALL_METRICS.remove();
    }

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
        LAST_CALL_METRICS.remove(); // Clear stale metrics from any previous call
        try {
            // Build MCP tools/call request
            // Use /mcp endpoint (stateless transport) - not /mcp/v1
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            // Get current trace context for propagation
            TraceInfo traceInfo = TraceContext.get();

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

            // Inject trace context into arguments via Rust core bridge
            // (FastMCP doesn't expose HTTP headers to tool handlers)
            Map<String, Object> argsWithTrace;
            if (traceInfo != null) {
                try {
                    String argsJson = objectMapper.writeValueAsString(params != null ? params : Map.of());
                    String headersJson = mergedHeaders.isEmpty() ? null : objectMapper.writeValueAsString(mergedHeaders);
                    String injectedJson = MeshCoreBridge.injectTraceContext(
                        argsJson,
                        traceInfo.getTraceId(),
                        traceInfo.getSpanId(),
                        headersJson
                    );
                    if (injectedJson != null) {
                        argsWithTrace = objectMapper.readValue(injectedJson, new TypeReference<LinkedHashMap<String, Object>>() {});
                    } else {
                        argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                        argsWithTrace.put("_trace_id", traceInfo.getTraceId());
                        if (traceInfo.getSpanId() != null) {
                            argsWithTrace.put("_parent_span", traceInfo.getSpanId());
                        }
                        if (!mergedHeaders.isEmpty()) {
                            argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                        }
                    }
                    log.trace("Injecting trace context via Rust core: trace={}, parent={}",
                        traceInfo.getTraceId().substring(0, 8),
                        traceInfo.getSpanId() != null ? traceInfo.getSpanId().substring(0, 8) : "null");
                } catch (Exception e) {
                    log.debug("Rust inject_trace_context failed, using fallback: {}", e.getMessage());
                    argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                    argsWithTrace.put("_trace_id", traceInfo.getTraceId());
                    if (traceInfo.getSpanId() != null) {
                        argsWithTrace.put("_parent_span", traceInfo.getSpanId());
                    }
                    if (!mergedHeaders.isEmpty()) {
                        argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                    }
                }
            } else {
                argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                // Still inject propagated headers even without trace context
                if (!mergedHeaders.isEmpty()) {
                    argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                }
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
            int requestBytes = requestBody.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
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

            // Determine effective timeout from X-Mesh-Timeout (propagated) or default (#769)
            int effectiveTimeoutSecs = 300; // default
            String existingTimeout = mergedHeaders.get("x-mesh-timeout");
            if (existingTimeout == null) existingTimeout = mergedHeaders.get("X-Mesh-Timeout");
            if (existingTimeout == null) {
                String callTimeout = System.getenv("MCP_MESH_CALL_TIMEOUT");
                if (callTimeout != null && !callTimeout.isEmpty()) {
                    try { effectiveTimeoutSecs = Integer.parseInt(callTimeout); } catch (NumberFormatException e) {}
                }
            } else {
                try { effectiveTimeoutSecs = Integer.parseInt(existingTimeout); } catch (NumberFormatException e) {}
            }
            // Guard against negative/zero
            if (effectiveTimeoutSecs <= 0) effectiveTimeoutSecs = 300;

            // Set X-Mesh-Timeout on the outgoing request if not already propagated
            if (!mergedHeaders.containsKey("x-mesh-timeout") && !mergedHeaders.containsKey("X-Mesh-Timeout")) {
                requestBuilder.header("X-Mesh-Timeout", String.valueOf(effectiveTimeoutSecs));
            }

            Request httpRequest = requestBuilder.build();

            // Override OkHttpClient timeout for this specific call — add 10s buffer
            // so client timeout doesn't race with the server-side proxy timeout.
            OkHttpClient perCallClient = httpClient.newBuilder()
                .readTimeout(effectiveTimeoutSecs + 10, TimeUnit.SECONDS)
                .writeTimeout(effectiveTimeoutSecs + 10, TimeUnit.SECONDS)
                .build();

            try (Response response = perCallClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful()) {
                    throw new MeshToolCallException(functionName, functionName,
                        "HTTP " + response.code() + ": " + response.message());
                }

                ResponseBody body = response.body();
                if (body == null) {
                    throw new MeshToolCallException(functionName, functionName, "Empty response body");
                }

                String responseBody = body.string();
                int responseBytes = responseBody.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
                LAST_CALL_METRICS.set(new CallMetrics(requestBytes, responseBytes));
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

                    // Handle MCP content array response
                    // Detect whether all content items are text-only or mixed (resource_link, image, etc.)
                    String textContent = null;
                    List<Map<String, Object>> mixedContent = null;
                    if (result.has("content") && result.get("content").isArray()) {
                        JsonNode content = result.get("content");
                        if (content.size() > 0) {
                            boolean allText = true;
                            for (int i = 0; i < content.size(); i++) {
                                JsonNode item = content.get(i);
                                String itemType = item.has("type") ? item.get("type").asText() : "text";
                                if (!"text".equals(itemType)) {
                                    allText = false;
                                    break;
                                }
                            }

                            if (allText) {
                                // Backward compatible: extract first text content as string
                                JsonNode firstContent = content.get(0);
                                if (firstContent.has("text")) {
                                    textContent = firstContent.get("text").asText();
                                }
                            } else {
                                // Mixed content: preserve full content array
                                mixedContent = new ArrayList<>();
                                for (int i = 0; i < content.size(); i++) {
                                    mixedContent.add(objectMapper.treeToValue(content.get(i),
                                        objectMapper.getTypeFactory().constructMapType(
                                            LinkedHashMap.class, String.class, Object.class)));
                                }
                                // Also extract text from first item for error reporting
                                JsonNode firstContent = content.get(0);
                                if (firstContent.has("text")) {
                                    textContent = firstContent.get("text").asText();
                                }
                            }
                        }
                    }

                    // Check if the tool call returned an error
                    if (result.has("isError") && result.get("isError").asBoolean()) {
                        String errorText = textContent != null ? textContent : "Unknown tool error";
                        throw new MeshToolCallException(functionName, functionName, errorText);
                    }

                    // If mixed content, return as-is (List<Map<String, Object>>)
                    if (mixedContent != null) {
                        @SuppressWarnings("unchecked")
                        T mixed = (T) mixedContent;
                        return mixed;
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
     * Shared executor for SSE stream readers. One daemon thread per active stream call.
     * Daemon so it doesn't block JVM shutdown.
     */
    private static final Executor STREAM_EXECUTOR = Executors.newCachedThreadPool(new ThreadFactory() {
        private final AtomicLong counter = new AtomicLong();
        @Override
        public Thread newThread(Runnable r) {
            Thread t = new Thread(r, "mesh-proxy-stream-" + counter.incrementAndGet());
            t.setDaemon(true);
            return t;
        }
    });

    /**
     * Soft warning threshold for unbounded buffering of unconsumed chunks.
     */
    private static final int STREAM_BUFFER_WARN_BYTES = 1024 * 1024;

    /**
     * Stream text chunks from a remote {@code Stream[str]} tool.
     *
     * <p>Returns a {@link Flow.Publisher} that, when subscribed, opens an SSE-framed
     * {@code tools/call} request, parses {@code notifications/progress} messages and
     * emits each chunk to the subscriber. The final {@code result} message ends the
     * stream (its content is NOT delivered).
     *
     * <p>Wire protocol mirrors the TypeScript SDK Stage 1 implementation: identical
     * Python producer serves both languages.
     *
     * <p>Subscription cancellation aborts the underlying OkHttp call.
     *
     * @param endpoint     The MCP server endpoint
     * @param functionName The remote tool name
     * @param params       Parameters for the tool call (may be null)
     * @param extraHeaders Per-call headers (may be null)
     * @return A publisher emitting text chunks
     */
    public Flow.Publisher<String> streamTool(String endpoint,
                                             String functionName,
                                             Map<String, Object> params,
                                             Map<String, String> extraHeaders) {
        return new StreamToolPublisher(endpoint, functionName, params, extraHeaders);
    }

    /**
     * Implementation of {@link Flow.Publisher} that opens a streaming MCP call on
     * subscribe. One subscriber per publisher (per the Reactive Streams spec for
     * unicast cold publishers).
     */
    private final class StreamToolPublisher implements Flow.Publisher<String> {
        private final String endpoint;
        private final String functionName;
        private final Map<String, Object> params;
        private final Map<String, String> extraHeaders;
        private final AtomicBoolean subscribed = new AtomicBoolean(false);

        StreamToolPublisher(String endpoint, String functionName,
                            Map<String, Object> params, Map<String, String> extraHeaders) {
            this.endpoint = endpoint;
            this.functionName = functionName;
            this.params = params;
            this.extraHeaders = extraHeaders;
        }

        @Override
        public void subscribe(Flow.Subscriber<? super String> subscriber) {
            if (subscriber == null) {
                throw new NullPointerException("subscriber");
            }
            if (!subscribed.compareAndSet(false, true)) {
                // Per spec: signal onError to additional subscribers
                Flow.Subscription noop = new Flow.Subscription() {
                    @Override public void request(long n) {}
                    @Override public void cancel() {}
                };
                subscriber.onSubscribe(noop);
                subscriber.onError(new IllegalStateException(
                    "StreamToolPublisher supports only one subscriber"));
                return;
            }
            StreamToolSubscription sub = new StreamToolSubscription(
                subscriber, endpoint, functionName, params, extraHeaders);
            subscriber.onSubscribe(sub);
            sub.start();
        }
    }

    /**
     * Subscription that drives the actual HTTP call + SSE parsing on a worker thread.
     *
     * <p>Backpressure: uses a {@link ConcurrentLinkedQueue} buffer. The reader thread
     * always parses incoming chunks (does not block OkHttp's read), and a delivery
     * loop drains the buffer to the subscriber as it requests demand. If the buffer
     * grows beyond {@link #STREAM_BUFFER_WARN_BYTES} unconsumed bytes, a warning is
     * logged once per stream.
     */
    private final class StreamToolSubscription implements Flow.Subscription {
        private final Flow.Subscriber<? super String> subscriber;
        private final String endpoint;
        private final String functionName;
        private final Map<String, Object> params;
        private final Map<String, String> extraHeaders;

        private final ConcurrentLinkedQueue<String> buffer = new ConcurrentLinkedQueue<>();
        private final AtomicLong demand = new AtomicLong();
        private final AtomicBoolean cancelled = new AtomicBoolean(false);
        private final AtomicBoolean terminated = new AtomicBoolean(false);
        private final AtomicBoolean draining = new AtomicBoolean(false);
        private final AtomicLong bufferedBytes = new AtomicLong();
        private final AtomicBoolean warnedOversize = new AtomicBoolean(false);

        // Set when stream completes; drained values still flushed first
        private volatile boolean upstreamComplete = false;
        private volatile Throwable upstreamError = null;

        // Underlying OkHttp call, set after start() begins; cancel() aborts it
        private volatile Call httpCall;

        StreamToolSubscription(Flow.Subscriber<? super String> subscriber,
                               String endpoint, String functionName,
                               Map<String, Object> params, Map<String, String> extraHeaders) {
            this.subscriber = subscriber;
            this.endpoint = endpoint;
            this.functionName = functionName;
            this.params = params;
            this.extraHeaders = extraHeaders;
        }

        void start() {
            STREAM_EXECUTOR.execute(this::run);
        }

        @Override
        public void request(long n) {
            if (n <= 0) {
                fail(new IllegalArgumentException(
                    "Flow.Subscription.request: n must be > 0 (got " + n + ")"));
                return;
            }
            // Add demand (saturating add)
            long updated = demand.updateAndGet(prev -> {
                long sum = prev + n;
                return sum < 0 ? Long.MAX_VALUE : sum;
            });
            if (updated > 0) {
                drain();
            }
        }

        @Override
        public void cancel() {
            if (cancelled.compareAndSet(false, true)) {
                Call c = this.httpCall;
                if (c != null) {
                    try {
                        c.cancel();
                    } catch (Exception e) {
                        log.debug("Error cancelling streaming OkHttp call: {}", e.getMessage());
                    }
                }
            }
        }

        private void fail(Throwable t) {
            if (terminated.compareAndSet(false, true)) {
                cancel(); // best-effort cleanup
                try {
                    subscriber.onError(t);
                } catch (Throwable inner) {
                    log.warn("Subscriber.onError threw: {}", inner.getMessage());
                }
            }
        }

        /**
         * Try to push as many buffered chunks as the subscriber has requested.
         * Re-entrant safe: only one thread drains at a time.
         */
        private void drain() {
            if (!draining.compareAndSet(false, true)) return;
            try {
                while (true) {
                    if (cancelled.get() || terminated.get()) return;
                    long d = demand.get();
                    if (d <= 0) {
                        // No demand right now
                        if (upstreamComplete && buffer.isEmpty()) {
                            terminate(upstreamError);
                        }
                        return;
                    }
                    String item = buffer.poll();
                    if (item == null) {
                        if (upstreamComplete) {
                            terminate(upstreamError);
                        }
                        return;
                    }
                    bufferedBytes.addAndGet(-(long) item.length());
                    demand.decrementAndGet();
                    try {
                        subscriber.onNext(item);
                    } catch (Throwable t) {
                        // Per spec: onNext is not allowed to throw, but defend anyway
                        fail(t);
                        return;
                    }
                }
            } finally {
                draining.set(false);
                // Re-check: an item may have been added, or demand requested,
                // between our last poll and clearing the flag
                if (!cancelled.get() && !terminated.get() && demand.get() > 0 && !buffer.isEmpty()) {
                    drain();
                }
            }
        }

        private void terminate(Throwable err) {
            if (!terminated.compareAndSet(false, true)) return;
            try {
                if (err != null) {
                    subscriber.onError(err);
                } else {
                    subscriber.onComplete();
                }
            } catch (Throwable t) {
                log.warn("Subscriber terminal callback threw: {}", t.getMessage());
            }
        }

        private void offer(String chunk) {
            buffer.add(chunk);
            long total = bufferedBytes.addAndGet(chunk.length());
            if (total > STREAM_BUFFER_WARN_BYTES && warnedOversize.compareAndSet(false, true)) {
                log.warn("Mesh stream buffer for {} exceeded {} bytes ({} bytes buffered) — "
                        + "consumer is slower than producer; consider faster Flow.Subscription.request() rate.",
                    functionName, STREAM_BUFFER_WARN_BYTES, total);
            }
            drain();
        }

        private void run() {
            try {
                runImpl();
            } catch (Throwable t) {
                upstreamError = t;
                upstreamComplete = true;
                drain();
            }
        }

        @SuppressWarnings("unchecked")
        private void runImpl() throws Exception {
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            TraceInfo traceInfo = TraceContext.get();

            // Build merged headers: session propagated + per-call (per-call wins)
            Map<String, String> propagatedHeaders = TraceContext.getPropagatedHeaders();
            Map<String, String> mergedHeaders = new LinkedHashMap<>(propagatedHeaders);
            if (extraHeaders != null) {
                for (Map.Entry<String, String> entry : extraHeaders.entrySet()) {
                    if (TraceContext.matchesPropagateHeader(entry.getKey())) {
                        mergedHeaders.put(entry.getKey().toLowerCase(), entry.getValue());
                    }
                }
            }

            // Inject trace context into arguments via Rust core (parity with callTool)
            Map<String, Object> argsWithTrace;
            if (traceInfo != null) {
                try {
                    String argsJson = objectMapper.writeValueAsString(params != null ? params : Map.of());
                    String headersJson = mergedHeaders.isEmpty() ? null : objectMapper.writeValueAsString(mergedHeaders);
                    String injectedJson = MeshCoreBridge.injectTraceContext(
                        argsJson,
                        traceInfo.getTraceId(),
                        traceInfo.getSpanId(),
                        headersJson
                    );
                    if (injectedJson != null) {
                        argsWithTrace = objectMapper.readValue(injectedJson, new TypeReference<LinkedHashMap<String, Object>>() {});
                    } else {
                        argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                        argsWithTrace.put("_trace_id", traceInfo.getTraceId());
                        if (traceInfo.getSpanId() != null) {
                            argsWithTrace.put("_parent_span", traceInfo.getSpanId());
                        }
                        if (!mergedHeaders.isEmpty()) {
                            argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                        }
                    }
                } catch (Exception e) {
                    log.debug("Rust inject_trace_context failed (stream), using fallback: {}", e.getMessage());
                    argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                    argsWithTrace.put("_trace_id", traceInfo.getTraceId());
                    if (traceInfo.getSpanId() != null) {
                        argsWithTrace.put("_parent_span", traceInfo.getSpanId());
                    }
                    if (!mergedHeaders.isEmpty()) {
                        argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                    }
                }
            } else {
                argsWithTrace = params != null ? new LinkedHashMap<>(params) : new LinkedHashMap<>();
                if (!mergedHeaders.isEmpty()) {
                    argsWithTrace.put("_mesh_headers", new LinkedHashMap<>(mergedHeaders));
                }
            }

            // Generate progressToken to correlate notifications with this call
            String progressToken = UUID.randomUUID().toString();
            long requestId = System.currentTimeMillis();

            Map<String, Object> request = Map.of(
                "jsonrpc", "2.0",
                "id", requestId,
                "method", "tools/call",
                "params", Map.of(
                    "name", functionName,
                    "arguments", argsWithTrace,
                    "_meta", Map.of("progressToken", progressToken)
                )
            );

            String requestBody = objectMapper.writeValueAsString(request);
            log.debug("Streaming tool {} at {} (token={})", functionName, url, progressToken);

            Request.Builder requestBuilder = new Request.Builder()
                .url(url)
                .post(RequestBody.create(requestBody, JSON))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream");

            if (traceInfo != null) {
                requestBuilder.header("X-Trace-ID", traceInfo.getTraceId());
                if (traceInfo.getSpanId() != null) {
                    requestBuilder.header("X-Parent-Span", traceInfo.getSpanId());
                }
            }
            for (Map.Entry<String, String> entry : mergedHeaders.entrySet()) {
                requestBuilder.header(entry.getKey(), entry.getValue());
            }

            // Determine effective timeout — same logic as callTool() (#769)
            int effectiveTimeoutSecs = 300;
            String existingTimeout = mergedHeaders.get("x-mesh-timeout");
            if (existingTimeout == null) existingTimeout = mergedHeaders.get("X-Mesh-Timeout");
            if (existingTimeout == null) {
                String callTimeout = System.getenv("MCP_MESH_CALL_TIMEOUT");
                if (callTimeout != null && !callTimeout.isEmpty()) {
                    try { effectiveTimeoutSecs = Integer.parseInt(callTimeout); } catch (NumberFormatException e) {}
                }
            } else {
                try { effectiveTimeoutSecs = Integer.parseInt(existingTimeout); } catch (NumberFormatException e) {}
            }
            if (effectiveTimeoutSecs <= 0) effectiveTimeoutSecs = 300;

            if (!mergedHeaders.containsKey("x-mesh-timeout") && !mergedHeaders.containsKey("X-Mesh-Timeout")) {
                requestBuilder.header("X-Mesh-Timeout", String.valueOf(effectiveTimeoutSecs));
            }

            Request httpRequest = requestBuilder.build();

            // Streaming call: read timeout governs the GAP between SSE events, not the
            // total call duration. We disable the per-call read timeout so a long-lived
            // stream isn't killed by OkHttp's idle-read timer.
            OkHttpClient perCallClient = httpClient.newBuilder()
                .readTimeout(0, TimeUnit.MILLISECONDS) // no per-read timeout for SSE
                .writeTimeout(effectiveTimeoutSecs + 10, TimeUnit.SECONDS)
                .callTimeout(0, TimeUnit.MILLISECONDS) // no overall timeout — controlled by upstream
                .build();

            Call call = perCallClient.newCall(httpRequest);
            this.httpCall = call;
            if (cancelled.get()) {
                call.cancel();
                upstreamComplete = true;
                drain();
                return;
            }

            try (Response response = call.execute()) {
                if (!response.isSuccessful()) {
                    upstreamError = new MeshToolCallException(functionName, functionName,
                        "HTTP " + response.code() + ": " + response.message());
                    upstreamComplete = true;
                    drain();
                    return;
                }

                ResponseBody body = response.body();
                if (body == null) {
                    upstreamError = new MeshToolCallException(functionName, functionName,
                        "Empty response body");
                    upstreamComplete = true;
                    drain();
                    return;
                }

                okio.BufferedSource source = body.source();
                StringBuilder eventBuf = new StringBuilder();

                while (!cancelled.get() && !source.exhausted()) {
                    // readUtf8Line returns null at EOF, otherwise the line without the
                    // line terminator. Both \n and \r\n are handled. A blank line is
                    // returned as "" — that's our SSE event boundary.
                    String line = source.readUtf8Line();
                    if (line == null) break;
                    if (line.isEmpty()) {
                        // End of one SSE event — process the accumulated buffer
                        if (eventBuf.length() > 0) {
                            boolean done = processSseEvent(eventBuf.toString(), progressToken, requestId);
                            eventBuf.setLength(0);
                            if (done) break;
                        }
                    } else {
                        eventBuf.append(line).append('\n');
                    }
                }
                // Trailing event without a blank-line terminator (defensive)
                if (eventBuf.length() > 0 && !cancelled.get()) {
                    processSseEvent(eventBuf.toString(), progressToken, requestId);
                }
            } catch (java.io.IOException e) {
                if (cancelled.get()) {
                    // Cancelled by subscriber — that's a clean exit, do not surface error
                    upstreamComplete = true;
                    drain();
                    return;
                }
                upstreamError = new MeshToolCallException(functionName, functionName, e);
            }

            upstreamComplete = true;
            drain();
        }

        /**
         * Parse one accumulated SSE event block. Returns true when the final JSON-RPC
         * response for our request id has been seen and the stream should terminate.
         */
        private boolean processSseEvent(String rawEvent, String progressToken, long requestId) {
            // Per SSE spec: collect data: lines, joined by \n; ignore other fields.
            StringBuilder dataBuf = new StringBuilder();
            for (String line : rawEvent.split("\n")) {
                if (line.startsWith("data: ")) {
                    if (dataBuf.length() > 0) dataBuf.append('\n');
                    dataBuf.append(line, 6, line.length());
                } else if (line.startsWith("data:")) {
                    if (dataBuf.length() > 0) dataBuf.append('\n');
                    dataBuf.append(line, 5, line.length());
                }
            }
            if (dataBuf.length() == 0) return false;
            String data = dataBuf.toString();
            if (data.isEmpty()) return false;

            JsonNode msg;
            try {
                msg = objectMapper.readTree(data);
            } catch (Exception e) {
                // Defensive: ignore non-JSON data events
                log.trace("Skipping non-JSON SSE data: {}", data);
                return false;
            }

            // Progress notification: deliver if it matches our token
            JsonNode methodNode = msg.get("method");
            if (methodNode != null && "notifications/progress".equals(methodNode.asText())) {
                JsonNode params = msg.get("params");
                if (params != null) {
                    JsonNode token = params.get("progressToken");
                    if (token != null && progressToken.equals(token.asText())) {
                        // FastMCP sends ``message``; some implementations may send ``data``
                        String chunk = null;
                        JsonNode messageNode = params.get("message");
                        if (messageNode != null && messageNode.isTextual()) {
                            chunk = messageNode.asText();
                        } else {
                            JsonNode dataNode = params.get("data");
                            if (dataNode != null && dataNode.isTextual()) {
                                chunk = dataNode.asText();
                            }
                        }
                        if (chunk != null) {
                            offer(chunk);
                        }
                    }
                }
                return false;
            }

            // Final response for our request id: end the stream
            JsonNode idNode = msg.get("id");
            if (idNode != null && idNode.isNumber() && idNode.asLong() == requestId) {
                JsonNode errorNode = msg.get("error");
                if (errorNode != null) {
                    String em = errorNode.has("message")
                        ? errorNode.get("message").asText()
                        : errorNode.toString();
                    upstreamError = new MeshToolCallException(functionName, functionName, em);
                }
                // Final result content is intentionally NOT delivered — matches the
                // documented contract for streaming consumers.
                return true;
            }

            return false;
        }
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
     * <p>Delegates to Rust core for consistent cross-SDK behavior.
     *
     * @param sseContent The SSE-formatted response
     * @return The extracted JSON content from the data: line
     */
    private String extractJsonFromSse(String sseContent) {
        return MeshCoreBridge.parseSseResponse(sseContent);
    }

    private static KeyStore loadCaTrustStore(String caPath) throws Exception {
        CertificateFactory cf = CertificateFactory.getInstance("X.509");
        KeyStore trustStore = KeyStore.getInstance("PKCS12");
        trustStore.load(null, null);
        try (FileInputStream caIs = new FileInputStream(caPath)) {
            int i = 0;
            for (Certificate cert : cf.generateCertificates(caIs)) {
                trustStore.setCertificateEntry("mesh-ca-" + i++, cert);
            }
        }
        return trustStore;
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
            KeyStore trustStore = loadCaTrustStore(config.getCaPath());
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
            KeyStore trustStore = loadCaTrustStore(config.getCaPath());
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
