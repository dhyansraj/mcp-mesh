package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.function.ServerResponse;
import org.springframework.web.servlet.function.ServerResponse.SseBuilder;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Spring MVC SSE adapter for the framework-agnostic
 * {@link MeshA2ADispatcher.SseStreamPlan} (spec §4.6 / §4.7 / §5).
 *
 * <p>The dispatcher produces a stream-plan (a value object describing one
 * of four SSE shapes). This adapter materialises that plan as a Spring
 * {@link ServerResponse#sse(java.util.function.Consumer)} body, emitting
 * frames in the canonical {@code data: <json>\n\n} format plus
 * {@code : keepalive\n\n} comment lines every {@link #KEEPALIVE_MILLIS}
 * milliseconds of inactivity.
 *
 * <h2>Why a separate class?</h2>
 *
 * <p>Keeping the dispatcher Spring-SSE-free makes it unit-testable in plain
 * JUnit without a servlet container. The adapter contains the only
 * dependency on Spring MVC's functional SSE API. This separation mirrors
 * the {@code MeshSseEventBuilder} → {@code MeshSseController} split on the
 * {@code @MeshRoute} side.
 *
 * <h2>Threading</h2>
 *
 * <p>Spring's {@link SseBuilder} writes to the response synchronously on
 * the calling thread; we block the request thread for the duration of the
 * stream. This matches Python's {@code StreamingResponse} blocking
 * behavior — Spring MVC dispatches each request on its own worker thread,
 * so no extra async machinery is required. For long-running streams the
 * adapter uses {@link Thread#sleep(long)} between polls; the call returns
 * as soon as the underlying job reaches a terminal state OR the client
 * disconnects (detected via {@link IOException} on write).
 *
 * <h2>Client-disconnect handling</h2>
 *
 * <p>Per spec §7.3 / §5.4: a client-side SSE disconnect MUST NOT cancel
 * the underlying job — the client may rejoin via {@code tasks/resubscribe}.
 * We swallow {@link IOException} from {@link SseBuilder#data} writes, log
 * at DEBUG level, and exit the poll loop without calling
 * {@link JobProxy#cancel}. The job continues running and the next
 * {@code tasks/resubscribe} call re-attaches at the current registry view.
 */
public class MeshA2ASseDispatcher {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ASseDispatcher.class);

    /** Poll cadence for the long-running stream (spec §4.6 sequence diagram: 1s). */
    public static final long POLL_INTERVAL_MILLIS = 1000L;
    /** Keepalive interval — SSE comment frame after this much inactivity (spec §5.1: 15s). */
    public static final long KEEPALIVE_MILLIS = 15_000L;
    /** Maximum total stream duration as a defensive cap (1 hour). */
    public static final long MAX_STREAM_MILLIS = 60L * 60_000L;
    /**
     * Consecutive {@code proxy.status()} failures to tolerate during the SSE
     * poll loop before giving up on the stream. Spec §4.4 conformance:
     * transient unreachability is NOT authoritative evidence the job is dead,
     * so we keep emitting {@code state=working} status frames and continue
     * polling. Once this counter is reached we close the SSE stream without
     * marking the task store record terminal — subsequent {@code tasks/get}
     * resumes polling normally.
     */
    public static final int MAX_CONSECUTIVE_STATUS_FAILURES = 5;

    private final MeshA2ADispatcher dispatcher;

    public MeshA2ASseDispatcher(MeshA2ADispatcher dispatcher) {
        this.dispatcher = dispatcher;
    }

    /**
     * Materialise an SSE stream-plan as a Spring {@link ServerResponse}.
     *
     * <p>Headers per spec §4.6 / §5.1:
     * <ul>
     *   <li>{@code Content-Type: text/event-stream}</li>
     *   <li>{@code Cache-Control: no-cache}</li>
     *   <li>{@code X-Accel-Buffering: no}</li>
     *   <li>{@code Connection: keep-alive}</li>
     * </ul>
     */
    public ServerResponse render(MeshA2ADispatcher.SseStreamPlan plan) {
        switch (plan.kind) {
            case ERROR -> {
                HttpStatus status = plan.errorStatus != null ? plan.errorStatus : HttpStatus.OK;
                return ServerResponse
                    .status(status)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(plan.errorBody == null ? "" : plan.errorBody);
            }
            case SINGLE_FRAME -> {
                return sseResponse(builder -> {
                    writeFrame(builder, plan.firstFrame);
                });
            }
            case SYNC_COMPLETED -> {
                return sseResponse(builder -> {
                    writeFrame(builder, plan.firstFrame);
                    writeFrame(builder, plan.secondFrame);
                });
            }
            case LONG_RUNNING -> {
                return sseResponse(builder -> {
                    runLongRunningStream(builder, plan.reqId, plan.taskId, plan.proxy);
                });
            }
            default -> throw new IllegalStateException("Unknown SSE plan kind: " + plan.kind);
        }
    }

    private ServerResponse sseResponse(SseEmitter emitter) {
        // Spec §4.6 / §5.1 mandates Content-Type: text/event-stream which
        // {@code ServerResponse.sse(...)} sets automatically. The
        // additional buffering hints (Cache-Control: no-cache,
        // X-Accel-Buffering: no, Connection: keep-alive) are not
        // expressible through the functional SSE builder once it's been
        // promoted — Spring's BodyBuilder.headers(...) chain does not
        // re-apply to an in-flight SSE body. The hints are added at the
        // request level via {@link MeshA2ASseHeaderFilter} so they cover
        // every SSE response uniformly.
        return ServerResponse.sse(builder -> {
            try {
                emitter.emit(builder);
            } catch (Exception e) {
                log.debug("SSE stream terminated: {}", e.getMessage());
            } finally {
                try {
                    builder.complete();
                } catch (Exception ignored) {
                    // Already closed — best-effort cleanup.
                }
            }
        }, java.time.Duration.ofMillis(MAX_STREAM_MILLIS));
    }

    /**
     * Run the long-running poll loop (spec §5.3 long-running case):
     * <ol>
     *   <li>Emit an initial {@code state=working, final=false} frame so
     *       the client confirms subscription liveness.</li>
     *   <li>Poll {@link JobProxy#status} every
     *       {@link #POLL_INTERVAL_MILLIS} milliseconds.</li>
     *   <li>Emit a {@code state=working} frame only when {@code progress}
     *       or {@code progress_message} changed — suppress redundant
     *       updates (Python a2a.py:1057-1070).</li>
     *   <li>Emit a {@code : keepalive\n\n} SSE comment after
     *       {@link #KEEPALIVE_MILLIS} ms of inactivity.</li>
     *   <li>On terminal mesh state: attempt
     *       {@link JobProxy#await(double)} with a 1-second timeout for
     *       the completed branch, emit the artifact frame, emit the
     *       terminal status frame ({@code final=true}), mark the task
     *       store record terminal, return.</li>
     * </ol>
     */
    private void runLongRunningStream(SseBuilder builder, Object reqId, String taskId, JobProxy proxy) {
        long started = System.currentTimeMillis();

        // 1. Initial state=working frame.
        Map<String, Object> initial = dispatcher.buildStatusUpdateFrame(
            reqId, taskId, MeshA2AStateTranslator.A2A_WORKING, null, false, null);
        if (!writeFrame(builder, initial)) {
            return; // Client gone.
        }

        Object lastProgress = null;
        Object lastMessage = null;
        long lastEventTime = System.currentTimeMillis();
        int consecutiveStatusFailures = 0;

        while (true) {
            // Stream-level cap — preserves task state in the store so callers
            // can resume via tasks/resubscribe or check status via tasks/get.
            // The cap protects the worker thread from a stuck job; it is NOT
            // a job-death signal, so we emit a non-terminal status frame and
            // do NOT call markTaskTerminal (spec §4.4: producer-side resource
            // limits must not poison the task store).
            if (System.currentTimeMillis() - started > MAX_STREAM_MILLIS) {
                log.warn("SSE long-running stream for task {} exceeded {}ms cap; closing "
                    + "(task state preserved — clients may resubscribe)",
                    taskId, MAX_STREAM_MILLIS);
                writeFrame(builder, dispatcher.buildStatusUpdateFrame(
                    reqId, taskId, MeshA2AStateTranslator.A2A_WORKING,
                    "stream closed: producer-side cap exceeded "
                        + "(task still running; reconnect via tasks/resubscribe)",
                    true, null));
                return;
            }

            Map<String, Object> status;
            try {
                status = proxy.status();
                consecutiveStatusFailures = 0;
            } catch (Exception e) {
                consecutiveStatusFailures++;
                log.warn("A2A SSE poll: proxy.status() raised for task {} (failure {}/{}): {}",
                    taskId, consecutiveStatusFailures, MAX_CONSECUTIVE_STATUS_FAILURES, e.getMessage());
                // Spec §4.4 conformance: transient unreachability is NOT
                // authoritative evidence the job is dead. Emit a state=working
                // status frame carrying the error in status.message and
                // CONTINUE polling. Do NOT mark the task store terminal —
                // subsequent tasks/get must keep re-polling the proxy.
                if (!writeFrame(builder, dispatcher.buildStatusUpdateFrame(
                        reqId, taskId, MeshA2AStateTranslator.A2A_WORKING,
                        "status unavailable: " + e.getMessage(), false, null))) {
                    return; // Client gone.
                }
                if (consecutiveStatusFailures >= MAX_CONSECUTIVE_STATUS_FAILURES) {
                    log.warn("A2A SSE poll: giving up on task {} after {} consecutive status() "
                        + "failures (task state preserved — clients may retry via tasks/get)",
                        taskId, consecutiveStatusFailures);
                    return;
                }
                try {
                    Thread.sleep(POLL_INTERVAL_MILLIS);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    log.debug("SSE long-running stream for task {} interrupted; exiting", taskId);
                    return;
                }
                continue;
            }
            if (status == null) {
                status = new LinkedHashMap<>();
            }
            String meshState = MeshA2AStateTranslator.meshStatusOf(status);

            if (MeshA2AStateTranslator.isMeshTerminal(meshState)) {
                String a2aState = MeshA2AStateTranslator.fromMesh(meshState);
                Object finalResult = null;
                boolean hasFinalResult = false;

                if (MeshA2AStateTranslator.A2A_COMPLETED.equals(a2aState)) {
                    try {
                        finalResult = proxy.await(1.0);
                        hasFinalResult = true;
                        // Emit artifact frame BEFORE the terminal status —
                        // spec §5.3 ordering.
                        if (!writeFrame(builder, dispatcher.buildArtifactUpdateFrame(
                                reqId, taskId, finalResult))) {
                            return;
                        }
                    } catch (Exception e) {
                        log.debug("A2A SSE poll: proxy.await() raised on completed task {}: {}",
                            taskId, e.getMessage());
                    }
                }

                String finalMessage = null;
                if (MeshA2AStateTranslator.A2A_FAILED.equals(a2aState)) {
                    Object err = status.get("error");
                    if (err == null) err = status.get("progress_message");
                    if (err != null) finalMessage = err.toString();
                } else if (MeshA2AStateTranslator.A2A_CANCELED.equals(a2aState)) {
                    Object pm = status.get("progress_message");
                    if (pm != null) finalMessage = pm.toString();
                }

                writeFrame(builder, dispatcher.buildStatusUpdateFrame(
                    reqId, taskId, a2aState, finalMessage, true, null));

                // Cache the terminal envelope so the task store reflects
                // the same view tasks/get would return.
                Map<String, Object> terminalEnvelope = dispatcher.buildTaskFromStatus(
                    taskId, taskId, null, a2aState, status, finalResult, hasFinalResult);
                dispatcher.markTaskTerminal(taskId, terminalEnvelope);
                return;
            }

            Object progress = status.get("progress");
            Object progressMessage = status.get("progress_message");
            long now = System.currentTimeMillis();

            boolean progressChanged = !java.util.Objects.equals(progress, lastProgress);
            boolean messageChanged = !java.util.Objects.equals(progressMessage, lastMessage);

            if (progressChanged || messageChanged) {
                String msgText = progressMessage == null ? null : progressMessage.toString();
                if (!writeFrame(builder, dispatcher.buildStatusUpdateFrame(
                        reqId, taskId, MeshA2AStateTranslator.A2A_WORKING,
                        msgText, false, progress))) {
                    return;
                }
                lastProgress = progress;
                lastMessage = progressMessage;
                lastEventTime = now;
            } else if (now - lastEventTime > KEEPALIVE_MILLIS) {
                // Spec §5.1: SSE comment line, ignored by parsers but
                // resets proxy idle timers.
                if (!writeComment(builder, "keepalive")) {
                    return;
                }
                lastEventTime = now;
            }

            try {
                Thread.sleep(POLL_INTERVAL_MILLIS);
            } catch (InterruptedException e) {
                // Server shutdown — re-interrupt and exit cleanly.
                Thread.currentThread().interrupt();
                log.debug("SSE long-running stream for task {} interrupted; exiting", taskId);
                return;
            }
        }
    }

    /**
     * Write one JSON-RPC envelope as an SSE {@code data:} frame. Returns
     * {@code false} when the client has disconnected; caller MUST exit the
     * loop without calling {@code JobProxy.cancel()} per spec §7.3.
     */
    private boolean writeFrame(SseBuilder builder, Map<String, Object> envelope) {
        if (envelope == null) {
            return true;
        }
        try {
            // Spring's data() method handles JSON serialization via the
            // configured ObjectMapper — but we've already serialized the
            // envelope shape ourselves to keep determinism with the
            // Python frame builder. Pass the pre-serialized string.
            String json = dispatcher.toJsonString(envelope);
            builder.data(json);
            return true;
        } catch (IOException ioe) {
            log.debug("SSE write failed (client disconnected?): {}", ioe.getMessage());
            return false;
        } catch (Exception e) {
            log.warn("SSE write failed unexpectedly: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Write a raw SSE comment line ({@code : <text>\n\n}). Spec §5.1
     * keepalive contract. Returns {@code false} on client disconnect.
     *
     * <p>{@code SseBuilder.comment(...)} only buffers the comment line; we
     * must follow with {@link SseBuilder#send()} to flush the framing to
     * the wire (Spring 6.1.4+ split the API this way).
     */
    private boolean writeComment(SseBuilder builder, String text) {
        try {
            builder.comment(text).send();
            return true;
        } catch (IOException ioe) {
            log.debug("SSE keepalive write failed (client disconnected?): {}", ioe.getMessage());
            return false;
        } catch (Exception e) {
            log.warn("SSE keepalive write failed unexpectedly: {}", e.getMessage());
            return false;
        }
    }

    /** Functional interface mirroring Spring's lambda parameter for clarity. */
    @FunctionalInterface
    private interface SseEmitter {
        void emit(SseBuilder builder) throws Exception;
    }
}
