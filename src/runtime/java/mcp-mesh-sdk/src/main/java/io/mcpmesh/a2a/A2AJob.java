package io.mcpmesh.a2a;

import io.mcpmesh.JobController;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;

import java.time.Duration;
import java.util.Locale;

/**
 * Handle to a long-running A2A task — returned by
 * {@link A2AClient#submit}.
 *
 * <p>Provides direct task lifecycle methods ({@link #status},
 * {@link #waitUntilTerminal}, {@link #cancel}) AND a convenience
 * {@link #bridge(JobController)} that mirrors A2A polling state into a
 * mesh {@link JobController} for the typical {@code task=true}
 * consumer pattern.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2AJob} from the Python runtime
 * (issue #910 Phase 3). The Java surface is sync: callers wrap in
 * {@link java.util.concurrent.CompletableFuture#supplyAsync} when they
 * need async composition. This matches the Phase 1
 * {@link A2AClient#send} style — long-running A2A bridges live INSIDE
 * a {@code @MeshTool(task=true)} handler whose surrounding wrapper
 * already runs on a worker thread.
 *
 * <h2>Cancel-propagation note (JDK-17 limitation)</h2>
 *
 * Cancel detection uses {@link JobController#isCancelled()} polled
 * between A2A poll iterations inside {@link #bridge}. Cancel signals
 * arriving DURING a single in-flight HTTP poll wait for that call to
 * return (HTTP timeout cap = 30s default). A future enhancement could
 * race the controller's cancel token against the HTTP send; the v1
 * trade-off matches Python's behavior under most workloads.
 */
public final class A2AJob {

    private static final Logger log = LoggerFactory.getLogger(A2AJob.class);

    private final A2AClient client;
    private final String taskId;
    private final String initialState;
    private final JsonNode initialResult;
    private final ObjectMapper objectMapper;

    A2AJob(A2AClient client, String taskId, String initialState, JsonNode initialResult,
           ObjectMapper objectMapper) {
        this.client = client;
        this.taskId = taskId;
        this.initialState = initialState;
        this.initialResult = initialResult;
        this.objectMapper = objectMapper;
    }

    /** The consumer-generated task ID echoed back by the producer. */
    public String taskId() {
        return taskId;
    }

    /** The state observed in the {@code tasks/send} reply, before any polling. */
    public String initialState() {
        return initialState;
    }

    /**
     * POST {@code tasks/get} once and return the raw {@code result}
     * envelope from the upstream producer.
     *
     * @return the live parse tree of the producer's Task envelope —
     *         shared with the underlying {@link A2AClient}; treat as
     *         read-only (deep-copy via {@code result.deepCopy()} for
     *         safe mutation).
     * @throws A2AException on JSON-RPC error envelope, transport
     *                      failure, or malformed response.
     */
    public JsonNode status() {
        return client.tasksGet(taskId);
    }

    /**
     * POST {@code tasks/cancel}. Idempotent — already-terminal tasks
     * should return cleanly per A2A v1.0; transport-level errors are
     * logged and swallowed so callers can still raise
     * {@link A2AJobCanceledException} or similar.
     *
     * @param reason short human-readable reason (may be {@code null}).
     */
    public void cancel(String reason) {
        try {
            client.tasksCancel(taskId, reason);
        } catch (Exception exc) {
            // Mirror Python runtime: best-effort cancel — the remote may
            // have already terminated the task. Log and move on so callers
            // can still raise A2AJobCanceledException or similar.
            log.info("A2A tasks/cancel: remote raised for task {} on {} (may already be terminal): {}",
                taskId, client.url(), exc.getMessage());
        }
    }

    /**
     * Poll {@code tasks/get} until terminal; return an
     * {@link A2AResponse} on {@code state=completed}; throw
     * {@link A2AJobFailedException} on {@code state=failed};
     * {@link A2AJobCanceledException} on {@code state=canceled};
     * {@link A2ATimeoutException} if the deadline elapses.
     *
     * @param timeout per-call deadline (must be > 0).
     */
    public A2AResponse waitUntilTerminal(Duration timeout) {
        if (timeout == null || timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("A2AJob.waitUntilTerminal: timeout must be > 0");
        }

        if (isTerminal(initialState) && initialResult != null) {
            return terminalToResponseOrThrow(initialResult);
        }

        long deadlineNanos = System.nanoTime() + timeout.toNanos();
        long intervalMs = client.pollIntervalMs();
        long maxIntervalMs = client.pollIntervalMaxMs();

        while (System.nanoTime() < deadlineNanos) {
            sleepInterruptibly(intervalMs);
            if (System.nanoTime() >= deadlineNanos) {
                break;
            }
            JsonNode result = status();
            String state = readState(result);
            if (isTerminal(state)) {
                return terminalToResponseOrThrow(result);
            }
            intervalMs = Math.min(maxIntervalMs, (long) (intervalMs * A2AClient.POLL_BACKOFF_FACTOR));
        }

        throw new A2ATimeoutException(
            "A2A task '" + taskId + "' on " + client.url()
                + " did not reach terminal state within " + timeout);
    }

    /**
     * Mirror A2A polling into the supplied {@link JobController} until
     * terminal. Returns the final artifact value: a parsed
     * {@code Map<String,Object>} (via Jackson) when the artifact text is
     * valid JSON, otherwise the raw artifact text as a {@code String}.
     *
     * <p>Polls {@link JobController#isCancelled()} between iterations:
     * on cancel detection, POSTs {@code tasks/cancel} upstream and
     * throws {@link A2AJobCanceledException} so the framework's
     * {@code task=true} wrapper records a canceled outcome.
     *
     * <p>The framework's {@code task=true} wrapper takes the return
     * and calls {@code controller.complete(...)} itself — this method
     * only mirrors progress + propagates terminal state.
     *
     * @param controller the framework-injected {@link JobController}
     *                   for the surrounding mesh job; must be non-null.
     * @return the final artifact value: parsed JSON
     *         ({@code Map<String,Object>} or {@code List<Object>}) when
     *         the producer's artifact text is valid JSON, otherwise the
     *         raw text {@code String}. Empty artifacts return an empty
     *         {@code String}.
     * @throws A2AJobFailedException   on terminal {@code state=failed}
     *                                 OR a polling-loop transport
     *                                 failure (with best-effort
     *                                 upstream cancel).
     * @throws A2AJobCanceledException on terminal {@code state=canceled}
     *                                 OR mesh-side cancel
     *                                 ({@link JobController#isCancelled()})
     *                                 propagated upstream.
     */
    public Object bridge(JobController controller) {
        if (controller == null) {
            throw new IllegalArgumentException("A2AJob.bridge: controller must be non-null");
        }
        return bridgeInternal(JobControllerAdapter.wrap(controller));
    }

    /**
     * Package-private bridge entry point that takes the test seam
     * adapter directly. Only {@link #bridge(JobController)} (production
     * callers) and the unit test in {@code A2AJobTest} should use this.
     */
    Object bridgeInternal(JobControllerAdapter controller) {
        ProgressMirrorState mirrorState = new ProgressMirrorState();
        if (initialResult != null) {
            mirrorProgress(controller, initialResult, mirrorState);
        }

        if (isTerminal(initialState) && initialResult != null) {
            return terminalToArtifactOrThrow(initialResult);
        }

        long intervalMs = client.pollIntervalMs();
        long maxIntervalMs = client.pollIntervalMaxMs();

        while (true) {
            if (wasCancelled(controller)) {
                propagateCancelUpstream("mesh-side cancel");
                throw new A2AJobCanceledException(
                    "A2A task " + taskId + " canceled by mesh-side request");
            }

            JsonNode result;
            try {
                result = status();
            } catch (RuntimeException exc) {
                // tasks/get itself failed (network error, HTTP 5xx,
                // malformed envelope, ...). The upstream producer is
                // almost certainly still running — best-effort POST
                // tasks/cancel so it stops billing for work whose
                // result we'll never observe.
                propagateCancelUpstream("consumer poll failed");
                throw new A2AJobFailedException(
                    "A2A status poll failed for task " + taskId + ": " + exc.getMessage(), exc);
            }

            String state = readState(result);
            mirrorProgress(controller, result, mirrorState);
            if (isTerminal(state)) {
                return terminalToArtifactOrThrow(result);
            }

            try {
                sleepInterruptibly(intervalMs);
            } catch (A2AJobFailedException e) {
                // Local thread interrupt during the bridge sleep. Mirror Python's
                // CancelledError handling — the user intent was "stop this work",
                // which means the upstream A2A task should be canceled too.
                // Clear the interrupt flag for the duration of the upstream
                // cancel POST — Java's HttpClient.send() refuses to run on an
                // interrupted thread (throws InterruptedException immediately),
                // and we need this best-effort cancel to actually reach the
                // upstream producer. Restore the flag before throwing so the
                // caller still observes the interrupted state.
                boolean wasInterrupted = Thread.interrupted();
                try {
                    propagateCancelUpstream("local interrupt");
                } finally {
                    if (wasInterrupted) {
                        Thread.currentThread().interrupt();
                    }
                }
                throw new A2AJobCanceledException(
                    "A2A task " + taskId + " interrupted by local thread cancel",
                    e.getCause());
            }
            // Re-check cancel right after the sleep — a long sleep
            // could let the controller flip to cancelled while we
            // were waiting. Without this, the loop would issue one
            // more wasted tasks/get before checking again.
            if (wasCancelled(controller)) {
                propagateCancelUpstream("mesh-side cancel");
                throw new A2AJobCanceledException(
                    "A2A task " + taskId + " canceled by mesh-side request");
            }
            intervalMs = Math.min(maxIntervalMs, (long) (intervalMs * A2AClient.POLL_BACKOFF_FACTOR));
        }
    }

    private static boolean wasCancelled(JobControllerAdapter controller) {
        try {
            return controller.isCancelled();
        } catch (RuntimeException exc) {
            // Native handle invalidated, FFI failure, etc. Treat as a poll failure
            // — bridge() contract documents A2AJobFailedException for this kind
            // of unrecoverable runtime issue.
            throw new A2AJobFailedException(
                "JobController.isCancelled() failed (native handle issue?): " + exc.getMessage(), exc);
        }
    }

    private void propagateCancelUpstream(String reason) {
        try {
            client.tasksCancel(taskId, reason);
        } catch (Exception exc) {
            log.debug("A2AJob.bridge: upstream cancel after {} also failed (task={}): {}",
                reason, taskId, exc.getMessage());
        }
    }

    private A2AResponse terminalToResponseOrThrow(JsonNode result) {
        String state = readState(result);
        if ("completed".equals(state.toLowerCase(Locale.ROOT))) {
            return buildResponseFromResult(result);
        }
        String msg = terminalMessage(result);
        if (msg.isEmpty()) {
            msg = "A2A task " + taskId + " state=" + state;
        }
        if (isCanceledState(state)) {
            throw new A2AJobCanceledException(msg);
        }
        throw new A2AJobFailedException(msg);
    }

    private Object terminalToArtifactOrThrow(JsonNode result) {
        String state = readState(result);
        if ("completed".equals(state.toLowerCase(Locale.ROOT))) {
            return buildArtifactValue(result);
        }
        String msg = terminalMessage(result);
        if (msg.isEmpty()) {
            msg = "A2A task " + taskId + " state=" + state;
        }
        if (isCanceledState(state)) {
            throw new A2AJobCanceledException(msg);
        }
        throw new A2AJobFailedException(msg);
    }

    private A2AResponse buildResponseFromResult(JsonNode result) {
        String artifactText = extractArtifactText(result);
        return new A2AResponse(artifactText, readState(result), taskId, result);
    }

    private Object buildArtifactValue(JsonNode result) {
        String text = extractArtifactText(result);
        if (text.isEmpty()) {
            return text;
        }
        // Mirror the Python runtime: attempt JSON parse, fall back to raw
        // text on parse failure. Primitive-string returns survive the
        // round-trip via the catch branch.
        try {
            JsonNode parsed = objectMapper.readTree(text);
            if (parsed == null || parsed.isNull()) {
                return text;
            }
            return objectMapper.convertValue(parsed, Object.class);
        } catch (Exception parseExc) {
            return text;
        }
    }

    /**
     * Mirror the producer-side state into the controller. Tracks
     * last-emitted (progress, message) so duplicate updates between
     * poll iterations are skipped — matches the Python runtime's
     * coalescing behavior.
     */
    private void mirrorProgress(JobControllerAdapter controller, JsonNode result, ProgressMirrorState s) {
        Double progress = readProgress(result);
        String message = readStatusMessage(result);
        if (progress == null && message == null) {
            return;
        }
        if (sameOrNull(progress, s.lastProgress) && equalsNullable(message, s.lastMessage)) {
            return;
        }
        // Coerce missing progress to last-known or 0.0 — the controller
        // requires a double, but the consumer surface allows
        // message-only progress events. Clamp to [0.0, 1.0] — the
        // updateProgress contract expects a normalized fraction; raw
        // A2A producer progress values are advisory.
        double rawP = progress != null
            ? progress
            : (s.lastProgress != null ? s.lastProgress : 0.0d);
        double clamped = Math.min(1.0d, Math.max(0.0d, rawP));
        try {
            controller.updateProgress(clamped, message);
        } catch (RuntimeException exc) {
            // Do NOT advance lastProgress / lastMessage on delivery
            // failure — leaving them stale ensures the next poll's
            // equality check sees a delta and retries the update.
            log.warn("A2AJob.bridge: controller.updateProgress failed (task={}, progress={}, msg={}) — will retry on next poll",
                taskId, progress, message, exc);
            return;
        }
        if (progress != null) {
            s.lastProgress = progress;
        }
        s.lastMessage = message;
    }

    private static boolean isTerminal(String state) {
        if (state == null) {
            return false;
        }
        String s = state.toLowerCase(Locale.ROOT);
        return s.equals("completed") || s.equals("failed") || s.equals("canceled") || s.equals("cancelled");
    }

    private static boolean isCanceledState(String state) {
        if (state == null) {
            return false;
        }
        String s = state.toLowerCase(Locale.ROOT);
        return s.equals("canceled") || s.equals("cancelled");
    }

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

    private static Double readProgress(JsonNode result) {
        if (result == null) {
            return null;
        }
        JsonNode metadata = result.get("metadata");
        if (metadata == null || !metadata.isObject()) {
            return null;
        }
        JsonNode progress = metadata.get("progress");
        if (progress == null || progress.isMissingNode() || progress.isNull()) {
            return null;
        }
        if (progress.isNumber()) {
            return progress.asDouble();
        }
        // Tolerant of stringified numerics (some producers JSON-encode
        // metadata fields as strings).
        try {
            return Double.parseDouble(progress.asString());
        } catch (Exception ignored) {
            return null;
        }
    }

    private static String readStatusMessage(JsonNode result) {
        if (result == null) {
            return null;
        }
        JsonNode status = result.get("status");
        if (status == null || !status.isObject()) {
            return null;
        }
        JsonNode msg = status.get("message");
        if (msg == null || !msg.isObject()) {
            return null;
        }
        return extractFirstTextPart(msg);
    }

    private static String terminalMessage(JsonNode result) {
        String msg = readStatusMessage(result);
        return msg == null ? "" : msg;
    }

    private static String extractArtifactText(JsonNode result) {
        if (result == null) {
            return "";
        }
        JsonNode artifacts = result.get("artifacts");
        if (!(artifacts instanceof ArrayNode array) || array.isEmpty()) {
            return "";
        }
        JsonNode first = array.get(0);
        if (first == null || !first.isObject()) {
            return "";
        }
        return extractFirstTextPart(first);
    }

    private static String extractFirstTextPart(JsonNode container) {
        JsonNode parts = container.get("parts");
        if (!(parts instanceof ArrayNode array) || array.isEmpty()) {
            return null;
        }
        JsonNode first = array.get(0);
        if (first == null || !first.isObject()) {
            return null;
        }
        JsonNode text = first.get("text");
        if (text == null || text.isNull()) {
            return null;
        }
        return text.asString();
    }

    private static boolean sameOrNull(Double a, Double b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.doubleValue() == b.doubleValue();
    }

    private static boolean equalsNullable(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.equals(b);
    }

    private static void sleepInterruptibly(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new A2AJobFailedException("A2AJob bridge poll loop interrupted", e);
        }
    }

    /**
     * Mutable progress-mirror state for {@link #mirrorProgress}.
     * Kept as a class (not record) so the helper can mutate the
     * fields without rebuilding instances per poll.
     */
    private static final class ProgressMirrorState {
        Double lastProgress;
        String lastMessage;
    }
}
