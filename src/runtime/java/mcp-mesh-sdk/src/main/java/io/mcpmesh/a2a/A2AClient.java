package io.mcpmesh.a2a;

import io.mcpmesh.core.MeshObjectMappers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * Thin A2A v1.0 client — sync {@code tasks/send} + poll until terminal.
 *
 * <p>Phase 1 surface (issue #916): one synchronous {@link #send} call
 * that POSTs a JSON-RPC {@code tasks/send} request, then polls
 * {@code tasks/get} with exponential backoff (capped at
 * {@code pollIntervalMaxMs}) until the task reaches a terminal state
 * ({@code completed} / {@code failed} / {@code canceled}, case-insensitive
 * for the US/UK spelling) or the user-supplied timeout elapses.
 *
 * <p>One instance per (url, skillId, auth) tuple — a typical Spring
 * agent constructs one per {@code @MeshTool} method (with {@code static}
 * lifetime) so the underlying {@link HttpClient}'s connection pool is
 * amortized across calls.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2AClient} from the Python
 * runtime. Phase 3 ({@code submit} / {@code subscribe} / SSE) is
 * deferred to a follow-up PR.
 *
 * <p><b>Lifecycle on JDK 17:</b> This class implements {@link AutoCloseable}
 * for forward-compatibility, but the underlying {@link java.net.http.HttpClient}
 * does not expose a shutdown hook prior to JDK 21. Calling {@link #close()}
 * marks this instance closed (subsequent operations throw {@link A2AException})
 * but the HttpClient's internal selector and worker threads remain alive
 * until garbage collection. For long-running test suites or containers that
 * create and discard many instances, prefer holding a single shared
 * {@code A2AClient} instance for the process lifetime.
 *
 * <h2>Example</h2>
 * <pre>{@code
 * private static final A2AClient CLIENT = new A2AClient(
 *     "http://upstream.example.com/agents/date",
 *     "get-date");
 *
 * @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
 * @A2AConsumer
 * public Map<String, Object> currentDate() throws Exception {
 *     A2AResponse r = CLIENT.send(Map.of(
 *         "role", "user",
 *         "parts", List.of(Map.of("type", "text", "text", "now"))
 *     ));
 *     return new ObjectMapper().readValue(r.artifactText(), Map.class);
 * }
 * }</pre>
 */
public final class A2AClient implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(A2AClient.class);

    /** Default per-call deadline for {@link #send}. */
    public static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);

    /** Initial backoff between {@code tasks/get} polls. */
    static final long DEFAULT_POLL_INTERVAL_MS = 500L;
    /** Cap on the backoff between {@code tasks/get} polls. */
    static final long DEFAULT_POLL_INTERVAL_MAX_MS = 2000L;
    /** Backoff multiplier between consecutive {@code tasks/get} polls. */
    public static final double POLL_BACKOFF_FACTOR = 1.5d;

    private final URI url;
    private final String skillId;
    private final A2ABearer auth;
    private final Duration defaultTimeout;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final long pollIntervalMs;
    private final long pollIntervalMaxMs;
    private volatile boolean closed;

    public A2AClient(String url, String skillId) {
        this(url, skillId, null, DEFAULT_TIMEOUT);
    }

    public A2AClient(String url, String skillId, A2ABearer auth) {
        this(url, skillId, auth, DEFAULT_TIMEOUT);
    }

    public A2AClient(String url, String skillId, A2ABearer auth, Duration defaultTimeout) {
        this(url, skillId, auth, defaultTimeout, DEFAULT_POLL_INTERVAL_MS, DEFAULT_POLL_INTERVAL_MAX_MS);
    }

    /**
     * Full constructor letting the caller override the poll backoff knobs.
     *
     * @param pollIntervalMs    initial backoff (ms) between {@code tasks/get}
     *                          polls; falls back to {@link #DEFAULT_POLL_INTERVAL_MS}
     *                          when {@code <= 0}.
     * @param pollIntervalMaxMs cap (ms) on the exponential poll backoff;
     *                          falls back to {@link #DEFAULT_POLL_INTERVAL_MAX_MS}
     *                          when {@code <= 0}.
     */
    public A2AClient(String url, String skillId, A2ABearer auth, Duration defaultTimeout,
                     long pollIntervalMs, long pollIntervalMaxMs) {
        if (url == null || url.isEmpty()) {
            throw new IllegalArgumentException("A2AClient: url must be non-empty");
        }
        if (defaultTimeout == null || defaultTimeout.isZero() || defaultTimeout.isNegative()) {
            throw new IllegalArgumentException("A2AClient: defaultTimeout must be > 0");
        }
        // Trim trailing slashes to match the Python runtime's url.rstrip("/")
        // — keeps the on-the-wire URL stable regardless of how the user
        // wrote the constructor argument.
        String trimmed = url;
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        this.url = URI.create(trimmed);
        this.skillId = skillId;
        this.auth = auth;
        this.defaultTimeout = defaultTimeout;
        this.objectMapper = MeshObjectMappers.create();
        this.pollIntervalMs = pollIntervalMs > 0 ? pollIntervalMs : DEFAULT_POLL_INTERVAL_MS;
        this.pollIntervalMaxMs = pollIntervalMaxMs > 0 ? pollIntervalMaxMs : DEFAULT_POLL_INTERVAL_MAX_MS;
        // connectTimeout is the TCP-handshake budget; the per-call
        // request timeout is set on each HttpRequest below using the
        // user-supplied or default deadline.
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(defaultTimeout)
            .build();
    }

    /** The configured A2A endpoint. */
    public URI url() {
        return url;
    }

    /** The configured skill ID, or {@code null} if unset. */
    public String skillId() {
        return skillId;
    }

    /**
     * POST {@code tasks/send} and poll {@code tasks/get} until terminal
     * using the client's default timeout.
     *
     * @param message A2A v1.0 request message dict (typically
     *                {@code {"role":"user","parts":[{"type":"text","text":"..."}]}})
     * @return an {@link A2AResponse} carrying the artifact text + raw envelope.
     * @throws A2AException        on JSON-RPC error envelope, transport
     *                             failure, or malformed response.
     * @throws A2ATimeoutException if no terminal state arrives within
     *                             the deadline.
     */
    public A2AResponse send(Map<String, Object> message) {
        return send(message, defaultTimeout);
    }

    /**
     * POST {@code tasks/send} and poll {@code tasks/get} until terminal
     * using the supplied deadline.
     *
     * @param message     A2A v1.0 request message dict.
     * @param callTimeout per-call deadline override (must be > 0).
     */
    public A2AResponse send(Map<String, Object> message, Duration callTimeout) {
        if (closed) {
            throw new A2AException(
                "A2AClient(url=" + url + ") is closed; create a new instance instead.");
        }
        if (message == null) {
            throw new IllegalArgumentException("A2AClient.send: message must be non-null");
        }
        if (callTimeout == null || callTimeout.isZero() || callTimeout.isNegative()) {
            throw new IllegalArgumentException("A2AClient.send: callTimeout must be > 0");
        }

        String taskId = "c-" + UUID.randomUUID().toString().replace("-", "");
        long deadlineNanos = System.nanoTime() + callTimeout.toNanos();

        ObjectNode params = objectMapper.createObjectNode();
        params.put("id", taskId);
        params.set("message", objectMapper.valueToTree(message));

        Duration remaining = remainingOrMin(deadlineNanos);
        JsonNode result = postJsonRpc("tasks/send", params, 1, remaining);
        String state = readState(result);

        if (isTerminal(state)) {
            return buildResponse(taskId, result);
        }

        long intervalMs = pollIntervalMs;
        ObjectNode getParams = objectMapper.createObjectNode();
        getParams.put("id", taskId);

        while (System.nanoTime() < deadlineNanos) {
            sleepInterruptibly(intervalMs);
            // Re-check the deadline AFTER the sleep so a long sleep
            // does not push the next tasks/get past the user's
            // deadline. Bail out cleanly to surface the polling-level
            // timeout rather than the per-call HTTP timeout (which has
            // a less helpful message).
            long remainingNs = deadlineNanos - System.nanoTime();
            if (remainingNs <= 0) {
                break;
            }
            remaining = Duration.ofNanos(remainingNs);
            result = postJsonRpc("tasks/get", getParams, 2, remaining);
            state = readState(result);
            if (isTerminal(state)) {
                return buildResponse(taskId, result);
            }
            intervalMs = Math.min(pollIntervalMaxMs, (long) (intervalMs * POLL_BACKOFF_FACTOR));
        }

        throw new A2ATimeoutException(
            "A2A task '" + taskId + "' on " + url
                + " did not reach terminal state within " + callTimeout
                + " (last state='" + state + "')");
    }

    /**
     * POST {@code tasks/send} and return an {@link A2AJob} handle
     * WITHOUT polling.
     *
     * <p>Use this when the surrounding {@code @MeshTool} is decorated
     * with {@code task=true} and the bridging logic wants explicit
     * control over when to poll (typically via
     * {@link A2AJob#bridge} which mirrors progress into the
     * framework-injected {@link io.mcpmesh.JobController}).
     *
     * @param message A2A v1.0 request message dict.
     * @return an {@link A2AJob} carrying the upstream task ID + initial
     *         envelope so callers can short-circuit when the producer
     *         already returned a terminal state on submit.
     * @throws A2AException on JSON-RPC error envelope, transport
     *                      failure, or malformed response.
     */
    public A2AJob submit(Map<String, Object> message) {
        if (closed) {
            throw new A2AException(
                "A2AClient(url=" + url + ") is closed; create a new instance instead.");
        }
        if (message == null) {
            throw new IllegalArgumentException("A2AClient.submit: message must be non-null");
        }
        String taskId = "c-" + UUID.randomUUID().toString().replace("-", "");
        ObjectNode params = objectMapper.createObjectNode();
        params.put("id", taskId);
        params.set("message", objectMapper.valueToTree(message));
        JsonNode result = postJsonRpc("tasks/send", params, 1, defaultTimeout);
        String state = readState(result);
        return new A2AJob(this, taskId, state, result, objectMapper);
    }

    /**
     * POST {@code tasks/sendSubscribe} and return an {@link A2AStream}
     * of parsed events.
     *
     * <p>The returned stream MUST be either iterated to completion (the
     * terminal {@code isFinal=true} frame auto-closes it) OR explicitly
     * closed via try-with-resources to release the underlying
     * connection. Failing to close leaks the JDK
     * {@link HttpClient}-pooled connection.
     *
     * @param message A2A v1.0 request message dict — same shape as
     *                {@link #send} / {@link #submit}.
     * @return an {@link A2AStream} producing {@link A2AEvent} via its
     *         {@link Iterable} surface.
     * @throws A2AException on connection failure or non-2xx HTTP status.
     */
    public A2AStream subscribe(Map<String, Object> message) {
        if (closed) {
            throw new A2AException(
                "A2AClient(url=" + url + ") is closed; create a new instance instead.");
        }
        if (message == null) {
            throw new IllegalArgumentException("A2AClient.subscribe: message must be non-null");
        }
        String taskId = "c-" + UUID.randomUUID().toString().replace("-", "");

        ObjectNode params = objectMapper.createObjectNode();
        params.put("id", taskId);
        params.set("message", objectMapper.valueToTree(message));

        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", 1);
        envelope.put("method", "tasks/sendSubscribe");
        envelope.set("params", params);

        String body;
        try {
            body = objectMapper.writeValueAsString(envelope);
        } catch (Exception e) {
            throw new A2AException("Failed to serialize JSON-RPC envelope for tasks/sendSubscribe", e);
        }

        // No request timeout on the SSE call — the stream lifetime is
        // dictated by the producer, not a per-request deadline. The
        // connectTimeout still applies to the initial TCP handshake.
        HttpRequest.Builder builder = HttpRequest.newBuilder()
            .uri(url)
            .header("Content-Type", "application/json")
            .header("Accept", "text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(body));
        if (auth != null) {
            builder.header("Authorization", auth.authorizationHeader());
        }

        HttpResponse<InputStream> response;
        try {
            response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (IOException e) {
            throw new A2AException(
                "A2A tasks/sendSubscribe " + url + " transport failure: " + e.getMessage(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new A2AException("A2A tasks/sendSubscribe " + url + " interrupted", e);
        }
        int status = response.statusCode();
        if (status >= 400) {
            // Read the body so we can include it in the error message,
            // then close it to release the connection.
            String responseBody = "";
            try (InputStream in = response.body()) {
                responseBody = new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            } catch (IOException ignored) {
                // best-effort drain
            }
            throw new A2AException(
                "A2A tasks/sendSubscribe " + url + " HTTP " + status + ": " + truncate(responseBody, 256));
        }
        return new A2AStream(response, taskId, objectMapper);
    }

    /**
     * Internal: POST {@code tasks/get} for the supplied task ID and
     * return the {@code result} envelope. Package-private so
     * {@link A2AJob} can drive its own polling without re-implementing
     * the JSON-RPC envelope or auth wiring.
     */
    JsonNode tasksGet(String taskId) {
        if (closed) {
            throw new A2AException(
                "A2AClient(url=" + url + ") is closed; create a new instance instead.");
        }
        ObjectNode params = objectMapper.createObjectNode();
        params.put("id", taskId);
        return postJsonRpc("tasks/get", params, 2, defaultTimeout);
    }

    /**
     * Internal: POST {@code tasks/cancel} for the supplied task ID.
     * Package-private so {@link A2AJob} can drive cancel propagation
     * without re-implementing the JSON-RPC envelope or auth wiring.
     */
    void tasksCancel(String taskId, String reason) {
        if (closed) {
            throw new A2AException(
                "A2AClient(url=" + url + ") is closed; create a new instance instead.");
        }
        ObjectNode params = objectMapper.createObjectNode();
        params.put("id", taskId);
        if (reason != null) {
            params.put("reason", reason);
        }
        postJsonRpc("tasks/cancel", params, 3, defaultTimeout);
    }

    /** Initial poll interval (ms) for {@link A2AJob#bridge}. */
    long pollIntervalMs() {
        return pollIntervalMs;
    }

    /** Capped poll interval (ms) for {@link A2AJob#bridge}. */
    long pollIntervalMaxMs() {
        return pollIntervalMaxMs;
    }

    @Override
    public void close() {
        // Java's HttpClient does not expose a shutdown hook prior to
        // JDK 21; the JVM reclaims pooled connections on GC. We mark
        // the client closed so subsequent send() calls raise rather
        // than reuse a torn-down instance.
        closed = true;
    }

    /**
     * Internal: POST one JSON-RPC envelope and return the {@code result}
     * node. Surfaces JSON-RPC error envelopes as {@link A2AException}.
     */
    private JsonNode postJsonRpc(String method, ObjectNode params, int rpcId, Duration timeout) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", rpcId);
        envelope.put("method", method);
        envelope.set("params", params);

        String body;
        try {
            body = objectMapper.writeValueAsString(envelope);
        } catch (Exception e) {
            throw new A2AException("Failed to serialize JSON-RPC envelope for " + method, e);
        }

        HttpRequest.Builder builder = HttpRequest.newBuilder()
            .uri(url)
            .timeout(timeout)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body));
        if (auth != null) {
            // A2ABearer.authorizationHeader resolves the env-var or
            // literal at call time so a rotated credential is honoured
            // mid-process.
            builder.header("Authorization", auth.authorizationHeader());
        }

        HttpResponse<String> response;
        try {
            response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        } catch (java.net.http.HttpTimeoutException e) {
            throw new A2ATimeoutException(
                "A2A " + method + " " + url + " timed out after " + timeout, e);
        } catch (IOException e) {
            throw new A2AException("A2A " + method + " " + url + " transport failure: " + e.getMessage(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new A2AException("A2A " + method + " " + url + " interrupted", e);
        }

        int status = response.statusCode();
        String responseBody = response.body();
        if (status >= 400) {
            // Mirror httpx.raise_for_status — surface the upstream's
            // body in the exception so operators can debug the call
            // without re-running with a packet capture.
            throw new A2AException(
                "A2A " + method + " " + url + " HTTP " + status + ": " + truncate(responseBody, 256));
        }

        JsonNode parsed;
        try {
            parsed = objectMapper.readTree(responseBody);
        } catch (Exception e) {
            throw new A2AException(
                "A2A " + method + " " + url + " returned malformed JSON: " + truncate(responseBody, 256), e);
        }
        if (parsed == null || parsed.isMissingNode() || parsed.isNull()) {
            throw new A2AException(
                "A2A " + method + " " + url + " returned empty body");
        }
        if (parsed.has("error") && !parsed.get("error").isNull()) {
            JsonNode err = parsed.get("error");
            String code = err.has("code") ? err.get("code").asString() : "?";
            String message = err.has("message") ? err.get("message").asString() : "<no message>";
            throw new A2AException("A2A error from " + url + ": " + code + " " + message);
        }

        JsonNode result = parsed.get("result");
        if (result == null || result.isMissingNode() || result.isNull()) {
            // A producer that returns {"jsonrpc":"2.0","id":1} (no result
            // and no error) is malformed JSON-RPC. Coercing this to an
            // empty object would make readState() return "unknown" and
            // the polling loop spin until the user-supplied deadline.
            // Fail fast with a clear message instead.
            throw new A2AException(
                "A2A " + method + " " + url
                    + " response has neither 'result' nor 'error' field — malformed JSON-RPC envelope: "
                    + truncate(responseBody, 256));
        }
        return result;
    }

    /** Pull the task lifecycle state from {@code result.status.state}. */
    private static String readState(JsonNode result) {
        if (result == null) {
            return "unknown";
        }
        JsonNode status = result.get("status");
        if (status == null || status.isMissingNode() || status.isNull()) {
            return "unknown";
        }
        JsonNode state = status.get("state");
        if (state == null || state.isMissingNode() || state.isNull()) {
            return "unknown";
        }
        return state.asString();
    }

    /**
     * Accept both A2A v1.0's US "canceled" and the mesh JobController's
     * UK "cancelled" so a heterogeneous deployment doesn't get stuck
     * polling on a mismatched terminal state.
     */
    private static boolean isTerminal(String state) {
        if (state == null) {
            return false;
        }
        String s = state.toLowerCase(Locale.ROOT);
        return s.equals("completed") || s.equals("failed") || s.equals("canceled") || s.equals("cancelled");
    }

    private A2AResponse buildResponse(String taskId, JsonNode result) {
        String artifactText = "";
        JsonNode artifacts = result.get("artifacts");
        if (artifacts instanceof ArrayNode array && !array.isEmpty()) {
            JsonNode first = array.get(0);
            if (first != null && first.isObject()) {
                JsonNode parts = first.get("parts");
                if (parts instanceof ArrayNode partsArr && !partsArr.isEmpty()) {
                    JsonNode firstPart = partsArr.get(0);
                    if (firstPart != null && firstPart.isObject()) {
                        JsonNode text = firstPart.get("text");
                        if (text != null && !text.isNull()) {
                            artifactText = text.asString();
                        }
                    }
                }
            }
        }
        return new A2AResponse(artifactText, readState(result), taskId, result);
    }

    /**
     * Remaining budget clamped to a 1ms minimum so the very first
     * tasks/send call (issued before the polling loop) always has a
     * positive timeout — even when the user-supplied deadline has
     * already elapsed by the time we get here. The polling loop checks
     * the deadline directly (without the 1ms floor) so it surfaces a
     * polling-level A2ATimeoutException instead of a per-call HTTP one.
     */
    private static Duration remainingOrMin(long deadlineNanos) {
        long remainingNs = deadlineNanos - System.nanoTime();
        if (remainingNs <= 0) {
            return Duration.ofMillis(1);
        }
        return Duration.ofNanos(remainingNs);
    }

    private static void sleepInterruptibly(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new A2AException("A2AClient poll loop interrupted", e);
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
