package io.mcpmesh.a2a;

import io.mcpmesh.JobController;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.NoSuchElementException;

/**
 * Iterator over parsed A2A SSE events — returned by
 * {@link A2AClient#subscribe}.
 *
 * <p>Implements {@link Iterable} so callers can write
 * {@code for (A2AEvent event : stream)} idiomatically. Implements
 * {@link AutoCloseable} so callers MUST either iterate to completion
 * (which auto-closes once the {@code isFinal=true} frame is consumed)
 * OR use try-with-resources to release the underlying connection
 * cleanly.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2AStream} from the Python
 * runtime (issue #910 Phase 3) — uses plain JDK
 * {@link BufferedReader} instead of okio (no new Maven dependency).
 *
 * <h2>SSE parsing</h2>
 * Each event is preceded by zero or more {@code data:} lines and
 * terminated by an empty line. Lines starting with {@code :} (SSE
 * comment / keepalive) and any other field lines ({@code event:},
 * {@code id:}, {@code retry:}) are ignored. {@code data:} payloads
 * are concatenated with newlines per the SSE spec; the consumer
 * parses the joined buffer as JSON-RPC and translates known shapes
 * (status / artifact) into {@link A2AEvent}.
 *
 * <h2>Cancel propagation</h2>
 * Per A2A v1.0, client disconnect is a transient signal and does NOT
 * imply cancel — the producer continues running unless explicitly
 * canceled via {@code tasks/cancel}. {@link #bridge} therefore does
 * NOT POST {@code tasks/cancel} upstream on disconnect. Users who need
 * cancel propagation should use
 * {@link A2AClient#submit} + {@link A2AJob#bridge} instead, which
 * polls {@link JobController#isCancelled()} between iterations and
 * propagates upstream.
 *
 * <p><b>Threading:</b> SSE line parsing happens on the caller's thread.
 * Iteration via {@code for (A2AEvent event : stream)} blocks the calling
 * thread on each {@code next()} call while the next SSE frame is being
 * read from the network. {@link #bridge(JobController)} likewise runs
 * synchronously on the caller's thread until the stream terminates.
 */
public final class A2AStream implements Iterable<A2AEvent>, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(A2AStream.class);

    private final HttpResponse<InputStream> response;
    private final BufferedReader reader;
    private final ObjectMapper objectMapper;
    private final String taskId;
    private volatile boolean closed;

    A2AStream(HttpResponse<InputStream> response, String taskId, ObjectMapper objectMapper) {
        this.response = response;
        this.objectMapper = objectMapper;
        this.taskId = taskId;
        // BufferedReader.readLine handles both \n and \r\n line
        // terminators, matches the SSE spec.
        this.reader = new BufferedReader(
            new InputStreamReader(response.body(), StandardCharsets.UTF_8));
    }

    /** The consumer-generated task ID echoed back by the producer. */
    public String taskId() {
        return taskId;
    }

    @Override
    public Iterator<A2AEvent> iterator() {
        return new SseIterator();
    }

    /**
     * Iterate events; mirror progress to the supplied
     * {@link JobController}; return the final artifact value when
     * the terminal frame arrives.
     *
     * <p>Returns the final artifact value: parsed JSON
     * ({@code Map<String,Object>} or {@code List<Object>}) when the
     * artifact text is valid JSON, otherwise the raw text
     * {@code String}. Empty artifacts return an empty {@code String}.
     *
     * <p>The framework's {@code task=true} wrapper handles
     * {@code controller.complete(...)} from the return; this method
     * only mirrors progress + propagates terminal state.
     *
     * @throws A2AJobFailedException   on terminal {@code state=failed}
     *                                 OR stream end without artifact.
     * @throws A2AJobCanceledException on terminal {@code state=canceled}.
     */
    public Object bridge(JobController controller) {
        if (controller == null) {
            throw new IllegalArgumentException("A2AStream.bridge: controller must be non-null");
        }
        return bridgeInternal(JobControllerAdapter.wrap(controller));
    }

    /**
     * Package-private bridge entry point that takes the test seam
     * adapter directly. Only {@link #bridge(JobController)} (production
     * callers) and the unit test in {@code A2AStreamTest} should use
     * this.
     */
    Object bridgeInternal(JobControllerAdapter controller) {
        Double lastProgress = null;
        String lastMessage = null;
        Object artifactValue = null;
        boolean sawArtifact = false;
        String terminalState = null;
        String terminalMessage = null;

        try {
            for (A2AEvent event : this) {
                if (event.kind() == A2AEvent.Kind.ARTIFACT) {
                    artifactValue = parseArtifactValue(event.artifactText());
                    sawArtifact = true;
                    continue;
                }
                // STATUS event
                if (event.progress() != null || event.message() != null) {
                    boolean changed = !sameOrNull(event.progress(), lastProgress)
                        || !equalsNullable(event.message(), lastMessage);
                    if (changed) {
                        double rawP = event.progress() != null
                            ? event.progress()
                            : (lastProgress != null ? lastProgress : 0.0d);
                        double clamped = Math.min(1.0d, Math.max(0.0d, rawP));
                        try {
                            controller.updateProgress(clamped, event.message());
                            if (event.progress() != null) {
                                lastProgress = event.progress();
                            }
                            lastMessage = event.message();
                        } catch (RuntimeException exc) {
                            // Do NOT advance lastProgress / lastMessage —
                            // the next event with the same delta still
                            // passes the equality check below and retries.
                            log.warn("A2AStream.bridge: controller.updateProgress failed (task={}, progress={}, msg={}) — will retry on next event",
                                taskId, event.progress(), event.message(), exc);
                        }
                    }
                }
                if (event.isFinal()) {
                    terminalState = event.state();
                    terminalMessage = event.message();
                    break;
                }
            }
        } finally {
            close();
        }

        if (terminalState != null) {
            String lower = terminalState.toLowerCase(java.util.Locale.ROOT);
            if (lower.equals("canceled") || lower.equals("cancelled")) {
                throw new A2AJobCanceledException(
                    terminalMessage != null ? terminalMessage : "A2A task " + taskId + " canceled");
            }
            if (lower.equals("failed")) {
                throw new A2AJobFailedException(
                    terminalMessage != null ? terminalMessage : "A2A task " + taskId + " failed");
            }
        }
        if (!sawArtifact) {
            // Stream closed without an artifact event AND without a
            // terminal failure — surface as failed so the user function
            // raises rather than silently returning null.
            throw new A2AJobFailedException(
                "A2A subscribe stream " + taskId + " ended without artifact");
        }
        return artifactValue;
    }

    @Override
    public void close() {
        if (closed) {
            return;
        }
        closed = true;
        try {
            // BufferedReader.close cascades to the underlying
            // InputStream which closes the HttpResponse body — releases
            // the JDK HttpClient connection back to its pool.
            reader.close();
        } catch (IOException exc) {
            log.debug("A2AStream.close: reader close raised (task={}): {}", taskId, exc.getMessage());
        }
    }

    private Object parseArtifactValue(String text) {
        if (text == null || text.isEmpty()) {
            return text == null ? "" : text;
        }
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

    /**
     * Pull-style SSE event iterator. Caches the next event so
     * {@link #hasNext} can do the I/O work needed to know if another
     * event is available without losing it for {@link #next}.
     */
    private final class SseIterator implements Iterator<A2AEvent> {

        private A2AEvent next;
        /** True once the terminal {@code isFinal=true} frame has been consumed. */
        private boolean terminated;

        @Override
        public boolean hasNext() {
            if (terminated) {
                return false;
            }
            if (next != null) {
                return true;
            }
            next = readNext();
            return next != null;
        }

        @Override
        public A2AEvent next() {
            if (!hasNext()) {
                throw new NoSuchElementException("A2AStream exhausted (task=" + taskId + ")");
            }
            A2AEvent ev = next;
            next = null;
            if (ev.isFinal()) {
                terminated = true;
                // Auto-close on the terminal frame so the connection
                // returns to the pool promptly without waiting on the
                // GC. close() is idempotent.
                close();
            }
            return ev;
        }

        /**
         * Read SSE lines until a complete event is parsed (returns
         * non-null) or the stream is exhausted (returns null). Skips
         * comment lines, keepalives, and unknown JSON-RPC envelope
         * shapes.
         */
        private A2AEvent readNext() {
            if (closed) {
                return null;
            }
            StringBuilder dataBuf = new StringBuilder();
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isEmpty()) {
                        // Blank line — event boundary.
                        if (dataBuf.length() == 0) {
                            continue;
                        }
                        A2AEvent parsed = tryParse(dataBuf.toString());
                        dataBuf.setLength(0);
                        if (parsed != null) {
                            return parsed;
                        }
                        // Unknown envelope shape — skip and keep reading.
                        continue;
                    }
                    if (line.startsWith(":")) {
                        // SSE comment (keepalive) — ignore.
                        continue;
                    }
                    if (line.startsWith("data:")) {
                        // Strip "data:" prefix and one optional space; per
                        // SSE spec, multiple data: lines for the same event
                        // are joined with \n.
                        String payload = line.substring(5);
                        if (payload.startsWith(" ")) {
                            payload = payload.substring(1);
                        }
                        if (dataBuf.length() > 0) {
                            dataBuf.append('\n');
                        }
                        dataBuf.append(payload);
                        continue;
                    }
                    // event:/id:/retry:/unknown — ignore for v1.0.
                }

                // Stream ended. Flush any pending frame, then stop.
                if (dataBuf.length() > 0) {
                    return tryParse(dataBuf.toString());
                }
                return null;
            } catch (IOException exc) {
                // Transport error — close the stream so we don't leak
                // the connection, then surface as failed via the
                // bridging contract.
                close();
                throw new A2AException(
                    "A2AStream read failed for task " + taskId + ": " + exc.getMessage(), exc);
            }
        }

        private A2AEvent tryParse(String payload) {
            JsonNode envelope;
            try {
                envelope = objectMapper.readTree(payload);
            } catch (Exception exc) {
                log.debug("A2AStream: skipping non-JSON SSE frame (task={}): payload={}", taskId, payload);
                return null;
            }
            if (envelope == null || !envelope.isObject()) {
                return null;
            }
            JsonNode result = envelope.get("result");
            if (result == null || !result.isObject()) {
                return null;
            }

            // ARTIFACT events have the "artifact" key.
            JsonNode artifact = result.get("artifact");
            if (artifact != null && artifact.isObject()) {
                String text = extractFirstTextPart(artifact);
                if (text == null) {
                    text = "";
                }
                return new A2AEvent(A2AEvent.Kind.ARTIFACT, null, null, null, text, false, envelope);
            }

            // STATUS events have the "status" key.
            JsonNode status = result.get("status");
            if (status != null && status.isObject()) {
                String state = null;
                JsonNode stateNode = status.get("state");
                if (stateNode != null && !stateNode.isNull()) {
                    state = stateNode.asString();
                }
                String message = null;
                JsonNode msgObj = status.get("message");
                if (msgObj != null && msgObj.isObject()) {
                    message = extractFirstTextPart(msgObj);
                }
                Double progress = null;
                JsonNode metadata = result.get("metadata");
                if (metadata != null && metadata.isObject()) {
                    JsonNode pNode = metadata.get("progress");
                    if (pNode != null && !pNode.isNull()) {
                        if (pNode.isNumber()) {
                            progress = pNode.asDouble();
                        } else {
                            try {
                                progress = Double.parseDouble(pNode.asString());
                            } catch (Exception ignored) {
                                progress = null;
                            }
                        }
                    }
                }
                boolean isFinal = false;
                JsonNode finalNode = result.get("final");
                if (finalNode != null && !finalNode.isNull()) {
                    isFinal = finalNode.asBoolean(false);
                }
                return new A2AEvent(
                    A2AEvent.Kind.STATUS, state, progress, message, null, isFinal, envelope);
            }

            return null;
        }

        private String extractFirstTextPart(JsonNode container) {
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
    }
}
