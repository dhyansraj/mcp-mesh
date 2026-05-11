package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.types.McpMeshTool;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.type.TypeReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * JSON-RPC 2.0 dispatcher for {@code @MeshA2A} producer surfaces (spec §4).
 *
 * <p>Chunk 1B coverage:
 * <ul>
 *   <li>{@code tasks/send} — sync handler return → {@code state=completed};
 *       {@link JobProxy} return → {@code state=working} envelope with the
 *       task parked in the {@link MeshA2ATaskStore} (spec §4.3 long-running
 *       branch); handler exception → {@code state=failed} (spec §4.3).</li>
 *   <li>{@code tasks/get} — looks up the cached terminal envelope OR pulls
 *       live status from the parked {@link JobProxy} and translates the
 *       mesh state to A2A via {@link MeshA2AStateTranslator} (spec §4.4 /
 *       §7.2).</li>
 *   <li>{@code tasks/cancel} — calls {@link JobProxy#cancel(String)} on the
 *       parked task, then re-reads status; idempotent ack for already-terminal
 *       tasks (spec §4.5).</li>
 *   <li>{@code tasks/sendSubscribe} / {@code tasks/resubscribe} — exposed
 *       indirectly through {@link #buildSendSubscribeStream} /
 *       {@link #buildResubscribeStream} which return a framework-agnostic
 *       sequence of {@link SseFrame}s. The SSE adapter
 *       ({@link MeshA2ASseDispatcher}) maps each frame to a Spring
 *       {@code text/event-stream} body. The dispatcher itself never imports
 *       Spring SSE classes so it stays unit-testable with no servlet
 *       container (spec §4.6 / §4.7 / §5).</li>
 * </ul>
 *
 * <p>The dispatcher itself is path-agnostic — it consults
 * {@link MeshA2ARegistry} for every request to locate the right handler. Path
 * routing is handled by {@link MeshA2ADispatcherController}, which mounts the
 * dispatcher at {@code POST /**} and delegates here after path-to-surface
 * resolution.
 */
public class MeshA2ADispatcher {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ADispatcher.class);

    /** JSON-RPC: Parse error (request body is not valid JSON). Spec §4.1. */
    public static final int JSONRPC_PARSE_ERROR = -32700;
    /** JSON-RPC: Invalid Request (well-formed JSON but not a valid JSON-RPC
     *  request object — e.g. missing {@code method} field). Spec §4.1. */
    public static final int JSONRPC_INVALID_REQUEST = -32600;
    /** JSON-RPC: Method not found (unknown {@code tasks/*} verb). Spec §4.1. */
    public static final int JSONRPC_METHOD_NOT_FOUND = -32601;
    /** JSON-RPC: Invalid params (missing or unknown task id). Spec §4.4. */
    public static final int JSONRPC_INVALID_PARAMS = -32602;

    private final MeshA2ARegistry registry;
    private final MeshA2ATaskStore taskStore;
    private final ObjectMapper objectMapper;
    private final ObjectProvider<MeshDependencyInjector> injectorProvider;

    public MeshA2ADispatcher(
            MeshA2ARegistry registry,
            MeshA2ATaskStore taskStore,
            ObjectMapper objectMapper,
            ObjectProvider<MeshDependencyInjector> injectorProvider) {
        this.registry = registry;
        this.taskStore = taskStore;
        this.objectMapper = objectMapper;
        this.injectorProvider = injectorProvider;
    }

    /**
     * Dispatch a POST request to the {@code @MeshA2A} surface at
     * {@code path}.
     *
     * <p>Only handles JSON-RPC methods that respond with a single envelope
     * ({@code tasks/send}, {@code tasks/get}, {@code tasks/cancel}). SSE
     * methods are routed to the {@link MeshA2ASseDispatcher} adapter by the
     * controller; the dispatcher exposes them through
     * {@link #buildSendSubscribeStream} / {@link #buildResubscribeStream}.
     *
     * @param path        normalized request path (no trailing slash)
     * @param requestBody raw request body bytes (UTF-8 JSON)
     * @return a Spring {@link ResponseEntity} with the JSON-RPC response
     */
    public ResponseEntity<String> dispatch(String path, String requestBody) {
        MeshA2ARegistry.SurfaceMetadata surface = registry.getByPath(path);
        if (surface == null) {
            // Should not happen if MeshA2ADispatcherController only routes
            // registered paths here, but defensive 404 protects against
            // mis-wiring during tests.
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .contentType(MediaType.APPLICATION_JSON)
                .body(jsonRpcError(null, JSONRPC_METHOD_NOT_FOUND,
                    "No @MeshA2A surface registered at path: " + path));
        }

        // Parse the JSON-RPC request body. Spec §4.1: malformed body → HTTP
        // 400 + JSON-RPC error -32700.
        if (requestBody == null || requestBody.isEmpty()) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .contentType(MediaType.APPLICATION_JSON)
                .body(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                    "Parse error: request body is empty"));
        }
        JsonNode bodyNode;
        try {
            bodyNode = objectMapper.readTree(requestBody);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .contentType(MediaType.APPLICATION_JSON)
                .body(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                    "Parse error: request body is not valid JSON"));
        }
        // Jackson 3's readTree(...) returns a MissingNode rather than throwing
        // for inputs like a stray whitespace-only body — treat that as a parse
        // error too so we never fall through to the method-resolution branch
        // with a JsonNode that can't be inspected.
        if (bodyNode == null || bodyNode.isMissingNode()) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .contentType(MediaType.APPLICATION_JSON)
                .body(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                    "Parse error: request body did not contain a JSON value"));
        }

        Object reqId = extractId(bodyNode);
        String method = bodyNode.has("method") && bodyNode.get("method").isTextual()
            ? bodyNode.get("method").asText() : null;
        // Spec §4.1: well-formed JSON missing the required `method` member is
        // an Invalid Request (-32600), NOT Method not found (-32601). Without
        // this guard the default branch below would emit a misleading
        // "Method not implemented: 'null'" — the bug surfaced in issue #932
        // when the body-read path silently dropped the parsed body.
        if (method == null) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_REQUEST,
                "Invalid Request: 'method' field is required and must be a string");
        }
        JsonNode paramsNode = bodyNode.get("params");
        Map<String, Object> params = readParams(paramsNode);

        return switch (method) {
            case "tasks/send" -> handleTasksSend(surface, reqId, params);
            case "tasks/get" -> handleTasksGet(reqId, params);
            case "tasks/cancel" -> handleTasksCancel(reqId, params);
            // SSE verbs are routed via the controller's SSE branch — if we
            // see them here it means the controller fell through to the POST
            // path without setting the SSE accept header. Surface a clear
            // error rather than 500.
            case "tasks/sendSubscribe", "tasks/resubscribe" ->
                jsonRpcErrorResponse(reqId, JSONRPC_METHOD_NOT_FOUND,
                    "Method '" + method + "' requires an SSE-capable client. "
                        + "Set 'Accept: text/event-stream' or use a streaming HTTP client.");
            default -> jsonRpcErrorResponse(reqId, JSONRPC_METHOD_NOT_FOUND,
                "Method not implemented: '" + method + "'. "
                    + "Supported A2A v1.0 methods: tasks/send, tasks/get, "
                    + "tasks/cancel, tasks/sendSubscribe, tasks/resubscribe.");
        };
    }

    // ─────────────────────────────────────────────────────────────────
    // tasks/send
    // ─────────────────────────────────────────────────────────────────

    private ResponseEntity<String> handleTasksSend(
            MeshA2ARegistry.SurfaceMetadata surface, Object reqId, Map<String, Object> params) {
        // Spec §4.2: extract (task_id, session_id, message).
        String taskId = stringFromParams(params, "id");
        if (taskId == null) {
            taskId = UUID.randomUUID().toString();
        }
        String sessionId = stringFromParams(params, "sessionId");
        if (sessionId == null) {
            sessionId = taskId;
        }
        Map<String, Object> message = mapFromParams(params, "message");

        // Spec §4.3: duplicate in-flight task_id → -32602 already in use.
        // Terminal entries within the eviction window are also rejected
        // (matches Python's `_A2A_TASK_STORE` check).
        if (taskStore.contains(taskId)) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_PARAMS,
                "A2A task id '" + taskId + "' is already in use");
        }

        Object handlerResult;
        try {
            handlerResult = invokeHandler(surface, message);
        } catch (Throwable t) {
            // Spec §4.3 "Response — handler raised": exceptions become
            // state=failed Tasks, NOT JSON-RPC errors.
            String errorText = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
            log.debug("@MeshA2A handler {} raised: {}", surface.handlerMethodId(), errorText, t);
            Map<String, Object> envelope = buildFailedTask(taskId, sessionId, message, errorText);
            cacheTerminal(taskId, sessionId, message, envelope, null);
            return jsonRpcSuccessResponse(reqId, envelope);
        }

        // Spec §4.3 long-running branch: handler returned a JobProxy →
        // park the task and respond with state=working immediately. The
        // client polls tasks/get / tasks/sendSubscribe for progress and
        // the terminal artifact.
        if (handlerResult instanceof JobProxy proxy) {
            Map<String, Object> envelope = buildWorkingTask(taskId, sessionId, message, null, null);
            parkLongRunning(taskId, sessionId, message, proxy);
            log.info("@MeshA2A tasks/send: long-running task parked (task_id={} job_id={} path={})",
                taskId, proxy.jobId(), surface.path());
            return jsonRpcSuccessResponse(reqId, envelope);
        }

        Map<String, Object> envelope = buildCompletedTask(taskId, sessionId, message, handlerResult);
        cacheTerminal(taskId, sessionId, message, envelope, null);
        return jsonRpcSuccessResponse(reqId, envelope);
    }

    // ─────────────────────────────────────────────────────────────────
    // tasks/get
    // ─────────────────────────────────────────────────────────────────

    private ResponseEntity<String> handleTasksGet(Object reqId, Map<String, Object> params) {
        String taskId = stringFromParams(params, "id");
        if (taskId == null || taskId.isEmpty()) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_PARAMS,
                "Invalid params: 'id' is required for tasks/get");
        }
        MeshA2ATaskStore.TaskRecord record = taskStore.get(taskId);
        if (record == null) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_PARAMS,
                "Unknown task id: " + taskId);
        }
        if (record.terminalEnvelope() != null) {
            return jsonRpcSuccessResponse(reqId, record.terminalEnvelope());
        }
        // Non-terminal record: pull live status from the parked JobProxy.
        // Per spec §4.4 "transient unreachability": if status() raises we
        // return state=working with the error text in status.message rather
        // than a JSON-RPC error — the registry's transient failure isn't
        // authoritative evidence the job is dead.
        Map<String, Object> envelope = buildTaskFromLiveStatus(taskId, record);
        return jsonRpcSuccessResponse(reqId, envelope);
    }

    // ─────────────────────────────────────────────────────────────────
    // tasks/cancel
    // ─────────────────────────────────────────────────────────────────

    private ResponseEntity<String> handleTasksCancel(Object reqId, Map<String, Object> params) {
        String taskId = stringFromParams(params, "id");
        if (taskId == null || taskId.isEmpty()) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_PARAMS,
                "Invalid params: 'id' is required for tasks/cancel");
        }
        MeshA2ATaskStore.TaskRecord record = taskStore.get(taskId);
        if (record == null) {
            return jsonRpcErrorResponse(reqId, JSONRPC_INVALID_PARAMS,
                "Unknown task id: " + taskId);
        }

        // Idempotent ack: already-terminal task → echo the cached envelope.
        // Spec §4.5 "Idempotent; best-effort".
        if (record.terminalEnvelope() != null) {
            return jsonRpcSuccessResponse(reqId, record.terminalEnvelope());
        }

        String reason = stringFromParams(params, "reason");
        JobProxy proxy = record.jobProxy();
        if (proxy != null) {
            try {
                proxy.cancel(reason);
            } catch (Exception e) {
                // Spec §4.5: cancel exceptions are logged and swallowed —
                // the underlying job may already be terminal.
                log.info("A2A tasks/cancel: proxy.cancel() raised for task {} (may already be terminal): {}",
                    taskId, e.getMessage());
            }
        }

        // Re-read status post-cancel so the response reflects the latest
        // state. If status() also fails we synthesize a state=canceled
        // envelope (Python's a2a.py:817-826 fallback).
        Map<String, Object> envelope = buildTaskFromLiveStatus(taskId, record);
        // If the post-cancel state is terminal, mark the record so future
        // tasks/get calls hit the cached envelope and don't re-poll a
        // closed JobProxy.
        Object statusObj = envelope.get("status");
        if (statusObj instanceof Map<?, ?> statusMap) {
            Object stateObj = statusMap.get("state");
            if (stateObj instanceof String state && MeshA2AStateTranslator.isTerminal(state)) {
                taskStore.markTerminal(taskId, envelope);
            } else {
                // Status didn't show terminal yet but cancel was requested —
                // synthesize a canceled envelope so the client gets a clean
                // terminal response. Matches Python's fallback in
                // a2a.py:817-826 when post-cancel status() raises.
                Map<String, Object> synth = buildCanceledTask(
                    taskId,
                    record.sessionId() != null ? record.sessionId() : taskId,
                    record.requestMessage(),
                    reason);
                taskStore.markTerminal(taskId, synth);
                envelope = synth;
            }
        }
        return jsonRpcSuccessResponse(reqId, envelope);
    }

    // ─────────────────────────────────────────────────────────────────
    // tasks/sendSubscribe + tasks/resubscribe (SSE)
    // ─────────────────────────────────────────────────────────────────

    /**
     * Build the SSE event stream for a {@code tasks/sendSubscribe} request.
     * Returns an {@link SseStreamPlan} that the SSE adapter materialises
     * into a Spring {@code text/event-stream} body.
     *
     * <p>This method invokes the user handler eagerly (before the stream
     * opens) so handler exceptions become a single SSE failed frame, not
     * an opaque HTTP error mid-stream (spec §4.6: "The producer invokes
     * the user handler before the SSE stream opens").
     */
    public SseStreamPlan buildSendSubscribeStream(String path, String requestBody) {
        MeshA2ARegistry.SurfaceMetadata surface = registry.getByPath(path);
        if (surface == null) {
            return SseStreamPlan.error(jsonRpcError(null, JSONRPC_METHOD_NOT_FOUND,
                "No @MeshA2A surface registered at path: " + path), HttpStatus.NOT_FOUND);
        }
        JsonNode bodyNode;
        try {
            bodyNode = objectMapper.readTree(requestBody);
        } catch (Exception e) {
            return SseStreamPlan.error(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                "Parse error: request body is not valid JSON"), HttpStatus.BAD_REQUEST);
        }
        // Mirror the dispatch() guard: Jackson 3's readTree(...) returns a
        // MissingNode rather than throwing for whitespace-only bodies — treat
        // that as a parse error too so we never fall through with a JsonNode
        // that can't be inspected.
        if (bodyNode == null || bodyNode.isMissingNode()) {
            return SseStreamPlan.error(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                "Parse error: request body is not valid JSON"), HttpStatus.BAD_REQUEST);
        }
        Object reqId = extractId(bodyNode);
        Map<String, Object> params = readParams(bodyNode.get("params"));

        String taskId = stringFromParams(params, "id");
        if (taskId == null) {
            taskId = UUID.randomUUID().toString();
        }
        String sessionId = stringFromParams(params, "sessionId");
        if (sessionId == null) {
            sessionId = taskId;
        }
        Map<String, Object> message = mapFromParams(params, "message");

        if (taskStore.contains(taskId)) {
            // Duplicate in-flight task_id — surface as a single SSE failed
            // event so the SSE client sees a structured A2A failure rather
            // than an opaque HTTP error (Python a2a.py:1143-1149).
            return SseStreamPlan.singleFrame(buildStatusUpdateFrame(
                reqId, taskId, MeshA2AStateTranslator.A2A_FAILED,
                "A2A task id '" + taskId + "' is already in use", true, null));
        }

        Object handlerResult;
        try {
            handlerResult = invokeHandler(surface, message);
        } catch (Throwable t) {
            String errorText = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
            log.debug("@MeshA2A tasks/sendSubscribe handler {} raised: {}",
                surface.handlerMethodId(), errorText, t);
            // Even on failure, cache the terminal envelope so a subsequent
            // tasks/get returns it consistently.
            Map<String, Object> failed = buildFailedTask(taskId, sessionId, message, errorText);
            cacheTerminal(taskId, sessionId, message, failed, null);
            return SseStreamPlan.singleFrame(buildStatusUpdateFrame(
                reqId, taskId, MeshA2AStateTranslator.A2A_FAILED, errorText, true, null));
        }

        if (handlerResult instanceof JobProxy proxy) {
            parkLongRunning(taskId, sessionId, message, proxy);
            log.info("@MeshA2A tasks/sendSubscribe: long-running stream started (task_id={} job_id={} path={})",
                taskId, proxy.jobId(), surface.path());
            return SseStreamPlan.longRunning(reqId, taskId, proxy);
        }

        // Sync handler over tasks/sendSubscribe: per spec §5.3, emit one
        // artifact event then one final status event (state=completed).
        Map<String, Object> artifactFrame = buildArtifactUpdateFrame(reqId, taskId, handlerResult);
        Map<String, Object> terminalFrame = buildStatusUpdateFrame(
            reqId, taskId, MeshA2AStateTranslator.A2A_COMPLETED, null, true, null);
        // Cache the resulting envelope so a follow-up tasks/get returns
        // the same payload deterministically (the SSE branch is otherwise
        // ephemeral — no terminal envelope would be stored).
        Map<String, Object> envelope = buildCompletedTask(taskId, sessionId, message, handlerResult);
        cacheTerminal(taskId, sessionId, message, envelope, null);
        return SseStreamPlan.syncCompleted(reqId, taskId, artifactFrame, terminalFrame);
    }

    /**
     * Build the SSE event stream for a {@code tasks/resubscribe} request.
     * Spec §4.7: looks up the parked task, emits an initial state=working
     * event, then resumes polling from the registry's current view (no
     * replay of past events).
     */
    public SseStreamPlan buildResubscribeStream(String requestBody) {
        JsonNode bodyNode;
        try {
            bodyNode = objectMapper.readTree(requestBody);
        } catch (Exception e) {
            return SseStreamPlan.error(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                "Parse error: request body is not valid JSON"), HttpStatus.BAD_REQUEST);
        }
        if (bodyNode == null || bodyNode.isMissingNode()) {
            return SseStreamPlan.error(jsonRpcError(null, JSONRPC_PARSE_ERROR,
                "Parse error: request body is not valid JSON"), HttpStatus.BAD_REQUEST);
        }
        Object reqId = extractId(bodyNode);
        Map<String, Object> params = readParams(bodyNode.get("params"));

        String taskId = stringFromParams(params, "id");
        if (taskId == null || taskId.isEmpty()) {
            // Spec §4.7 errors: return standard JSON-RPC, not SSE, because
            // the response has not been promoted to text/event-stream yet.
            return SseStreamPlan.error(jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
                "Invalid params: 'id' is required for tasks/resubscribe"), HttpStatus.OK);
        }
        MeshA2ATaskStore.TaskRecord record = taskStore.get(taskId);
        if (record == null) {
            return SseStreamPlan.error(jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
                "Unknown task id: " + taskId), HttpStatus.OK);
        }
        if (record.terminalEnvelope() != null) {
            // Already terminal — emit ONE terminal status event and close.
            // No replay per Python's a2a.py:1175-1178.
            Map<String, Object> env = record.terminalEnvelope();
            Object statusObj = env.get("status");
            String state = MeshA2AStateTranslator.A2A_COMPLETED;
            String msgText = null;
            if (statusObj instanceof Map<?, ?> statusMap) {
                Object st = statusMap.get("state");
                if (st instanceof String s) state = s;
                Object msg = statusMap.get("message");
                if (msg instanceof Map<?, ?> msgMap) {
                    Object parts = msgMap.get("parts");
                    if (parts instanceof List<?> partsList && !partsList.isEmpty()
                        && partsList.get(0) instanceof Map<?, ?> firstPart) {
                        Object text = firstPart.get("text");
                        if (text != null) msgText = text.toString();
                    }
                }
            }
            return SseStreamPlan.singleFrame(buildStatusUpdateFrame(
                reqId, taskId, state, msgText, true, null));
        }
        JobProxy proxy = record.jobProxy();
        if (proxy == null) {
            // Non-terminal record without a JobProxy is an inconsistent
            // state. Surface as a failed terminal event so the client
            // doesn't hang.
            log.warn("tasks/resubscribe: task {} has neither terminal envelope nor JobProxy; "
                + "synthesizing failed terminal event", taskId);
            return SseStreamPlan.singleFrame(buildStatusUpdateFrame(
                reqId, taskId, MeshA2AStateTranslator.A2A_FAILED,
                "Task state inconsistent: no live JobProxy and no terminal envelope", true, null));
        }
        return SseStreamPlan.longRunning(reqId, taskId, proxy);
    }

    // ─────────────────────────────────────────────────────────────────
    // Live-status poll (shared by tasks/get, tasks/cancel, SSE poll loop)
    // ─────────────────────────────────────────────────────────────────

    /**
     * Pull the latest status from a parked task's {@link JobProxy} and
     * project it into an A2A v1.0 Task envelope. Handles the "transient
     * unreachability" branch per spec §4.4 by returning {@code state=working}
     * with the error text in {@code status.message} rather than throwing —
     * matches Python's a2a.py:718-735 behavior.
     */
    private Map<String, Object> buildTaskFromLiveStatus(String taskId, MeshA2ATaskStore.TaskRecord record) {
        String sessionId = record.sessionId() != null ? record.sessionId() : taskId;
        JobProxy proxy = record.jobProxy();
        if (proxy == null) {
            return buildWorkingTask(taskId, sessionId, record.requestMessage(), null, null);
        }
        Map<String, Object> status;
        try {
            status = proxy.status();
        } catch (Exception e) {
            log.warn("A2A tasks/get: proxy.status() raised for task {}: {}", taskId, e.getMessage());
            return buildWorkingTask(taskId, sessionId, record.requestMessage(),
                "status unavailable: " + e.getMessage(), null);
        }
        if (status == null) {
            status = new LinkedHashMap<>();
        }
        String meshState = MeshA2AStateTranslator.meshStatusOf(status);
        String a2aState = MeshA2AStateTranslator.fromMesh(meshState);

        // On completed, attempt proxy.await(timeoutSecs=1) to fetch the
        // final artifact synchronously. Tight timeout per spec §4.4 so we
        // don't block on a transiently-unreachable payload — fall back to
        // no artifact in that case.
        Object finalResult = null;
        boolean hasFinalResult = false;
        if (MeshA2AStateTranslator.A2A_COMPLETED.equals(a2aState)) {
            try {
                finalResult = proxy.await(1.0);
                hasFinalResult = true;
            } catch (Exception e) {
                log.debug("A2A tasks/get: proxy.await() failed for completed task {}: {}",
                    taskId, e.getMessage());
            }
        }

        return buildTaskFromStatus(taskId, sessionId, record.requestMessage(),
            a2aState, status, finalResult, hasFinalResult);
    }

    // ─────────────────────────────────────────────────────────────────
    // Handler invocation
    // ─────────────────────────────────────────────────────────────────

    /**
     * Reflectively invoke the user's {@code @MeshA2A} handler with:
     * <ul>
     *   <li>the A2A {@code message} at the first {@link Map} parameter slot,
     *       OR at index 0 when none of the params is a {@code Map};</li>
     *   <li>{@link McpMeshTool} proxies at any parameter annotated
     *       {@link MeshInject} (or whose type is {@link McpMeshTool}),
     *       resolved through {@link MeshDependencyInjector} — same DDDI
     *       wiring used by {@code @MeshRoute} and {@code @A2AConsumer}.</li>
     * </ul>
     */
    @SuppressWarnings("unchecked")
    private Object invokeHandler(MeshA2ARegistry.SurfaceMetadata surface, Map<String, Object> message)
            throws Throwable {
        Method method = surface.method();
        Parameter[] params = method.getParameters();
        Object[] args = new Object[params.length];

        boolean messageAssigned = false;
        for (int i = 0; i < params.length; i++) {
            Parameter p = params[i];
            MeshInject inj = p.getAnnotation(MeshInject.class);
            if (inj != null || McpMeshTool.class.isAssignableFrom(p.getType())) {
                args[i] = resolveDependency(surface, p, inj);
            } else if (Map.class.isAssignableFrom(p.getType()) && !messageAssigned) {
                args[i] = message;
                messageAssigned = true;
            } else if (!messageAssigned && i == 0) {
                // First non-DI parameter takes the message even if it's
                // not a Map (e.g., user wants a custom POJO — out of scope
                // for Chunk 1A, but we don't crash).
                args[i] = message;
                messageAssigned = true;
            } else {
                args[i] = null;
            }
        }

        try {
            if (!method.canAccess(surface.bean())) {
                method.setAccessible(true);
            }
            return method.invoke(surface.bean(), args);
        } catch (InvocationTargetException ite) {
            throw ite.getCause() != null ? ite.getCause() : ite;
        }
    }

    private McpMeshTool resolveDependency(
            MeshA2ARegistry.SurfaceMetadata surface, Parameter param, MeshInject inj) {
        MeshDependencyInjector injector = injectorProvider.getIfAvailable();
        if (injector == null) {
            log.warn("@MeshA2A {}: MeshDependencyInjector unavailable; injecting null McpMeshTool",
                surface.handlerMethodId());
            return null;
        }
        String requestedCapability = (inj != null && !inj.value().isEmpty())
            ? inj.value() : param.getName();
        // Match against the declared dependencies — the @MeshInject value
        // (or parameter name) must align with one of @MeshA2A's
        // @MeshDependency entries. We resolve through the injector so the
        // proxy lifecycle matches the @MeshRoute path.
        for (MeshRouteRegistry.DependencySpec dep : surface.dependencies()) {
            if (dep.getCapability().equals(requestedCapability)
                || requestedCapability.equals(dep.getParameterName())) {
                return injector.getToolProxy(dep.getCapability());
            }
        }
        log.debug("@MeshA2A {}: no @MeshDependency matches parameter '{}'",
            surface.handlerMethodId(), requestedCapability);
        return null;
    }

    // ─────────────────────────────────────────────────────────────────
    // Task envelope builders (spec §4.3)
    // ─────────────────────────────────────────────────────────────────

    private Map<String, Object> buildCompletedTask(
            String taskId, String sessionId, Map<String, Object> requestMessage, Object result) {
        String text = stringifyResult(result);
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", MeshA2AStateTranslator.A2A_COMPLETED);
        status.put("timestamp", utcIso8601());

        Map<String, Object> artifact = new LinkedHashMap<>();
        artifact.put("name", "result");
        // Appendix A: parts[0].type MUST be emitted as "text" for forward
        // compatibility even though consumers ignore it.
        artifact.put("parts", List.of(textPart(text)));
        artifact.put("index", 0);

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("id", taskId);
        envelope.put("sessionId", sessionId);
        envelope.put("status", status);
        envelope.put("artifacts", List.of(artifact));
        envelope.put("history", historyOf(requestMessage));
        return envelope;
    }

    private Map<String, Object> buildFailedTask(
            String taskId, String sessionId, Map<String, Object> requestMessage, String errorMsg) {
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("role", "agent");
        message.put("parts", List.of(textPart(errorMsg)));

        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", MeshA2AStateTranslator.A2A_FAILED);
        status.put("timestamp", utcIso8601());
        status.put("message", message);

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("id", taskId);
        envelope.put("sessionId", sessionId);
        envelope.put("status", status);
        envelope.put("artifacts", List.of());
        envelope.put("history", historyOf(requestMessage));
        return envelope;
    }

    private Map<String, Object> buildCanceledTask(
            String taskId, String sessionId, Map<String, Object> requestMessage, String reason) {
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", MeshA2AStateTranslator.A2A_CANCELED);
        status.put("timestamp", utcIso8601());
        if (reason != null && !reason.isEmpty()) {
            Map<String, Object> message = new LinkedHashMap<>();
            message.put("role", "agent");
            message.put("parts", List.of(textPart(reason)));
            status.put("message", message);
        }
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("id", taskId);
        envelope.put("sessionId", sessionId);
        envelope.put("status", status);
        envelope.put("artifacts", List.of());
        envelope.put("history", historyOf(requestMessage));
        return envelope;
    }

    /**
     * Build a {@code state=working} task envelope (spec §4.3 long-running
     * branch / spec §4.4 transient unreachability fallback).
     */
    Map<String, Object> buildWorkingTask(
            String taskId, String sessionId, Map<String, Object> requestMessage,
            String progressMessage, Object progress) {
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", MeshA2AStateTranslator.A2A_WORKING);
        status.put("timestamp", utcIso8601());
        if (progressMessage != null && !progressMessage.isEmpty()) {
            Map<String, Object> message = new LinkedHashMap<>();
            message.put("role", "agent");
            message.put("parts", List.of(textPart(progressMessage)));
            status.put("message", message);
        }

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("id", taskId);
        envelope.put("sessionId", sessionId);
        envelope.put("status", status);
        envelope.put("artifacts", List.of());
        envelope.put("history", historyOf(requestMessage));
        if (progress != null) {
            envelope.put("metadata", Map.of("progress", progress));
        }
        return envelope;
    }

    /**
     * Build a Task envelope from a {@code JobProxy.status()} result dict.
     * Mirrors Python's {@code _build_task_from_status} (a2a.py:485-549) —
     * folds {@code error} / {@code progress_message} into A2A
     * {@code status.message}, materialises an artifact for completed
     * tasks when the final result is available, and lifts
     * {@code progress} to {@code metadata.progress}.
     */
    Map<String, Object> buildTaskFromStatus(
            String taskId, String sessionId, Map<String, Object> requestMessage,
            String a2aState, Map<String, Object> meshStatus,
            Object finalResult, boolean hasFinalResult) {
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", a2aState);
        status.put("timestamp", utcIso8601());

        Object msgText = null;
        if (MeshA2AStateTranslator.A2A_FAILED.equals(a2aState)) {
            msgText = meshStatus.get("error");
            if (msgText == null) msgText = meshStatus.get("progress_message");
        } else {
            msgText = meshStatus.get("progress_message");
        }
        if (msgText != null && !msgText.toString().isEmpty()) {
            Map<String, Object> message = new LinkedHashMap<>();
            message.put("role", "agent");
            message.put("parts", List.of(textPart(msgText.toString())));
            status.put("message", message);
        }

        List<Map<String, Object>> artifacts = new ArrayList<>();
        if (hasFinalResult && MeshA2AStateTranslator.A2A_COMPLETED.equals(a2aState)) {
            Map<String, Object> artifact = new LinkedHashMap<>();
            artifact.put("name", "result");
            artifact.put("parts", List.of(textPart(stringifyResult(finalResult))));
            artifact.put("index", 0);
            artifacts.add(artifact);
        }

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("id", taskId);
        envelope.put("sessionId", sessionId);
        envelope.put("status", status);
        envelope.put("artifacts", artifacts);
        envelope.put("history", historyOf(requestMessage));
        Object progress = meshStatus.get("progress");
        if (progress != null) {
            envelope.put("metadata", Map.of("progress", progress));
        }
        return envelope;
    }

    private Map<String, Object> textPart(String text) {
        Map<String, Object> part = new LinkedHashMap<>();
        part.put("type", "text");
        part.put("text", text != null ? text : "");
        return part;
    }

    private List<Map<String, Object>> historyOf(Map<String, Object> requestMessage) {
        if (requestMessage == null || requestMessage.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(1);
        out.add(new LinkedHashMap<>(requestMessage));
        return out;
    }

    /**
     * Stringify a handler return value as the text body of the
     * {@code result} artifact. {@link String} returns pass through verbatim;
     * everything else is JSON-stringified via the bound {@link ObjectMapper}.
     * Non-serializable returns fall back to {@link Object#toString()} so the
     * artifact is always well-formed (mirrors Python's {@code default=str}
     * coercion in {@code a2a.py:403}).
     */
    String stringifyResult(Object result) {
        if (result == null) {
            return "";
        }
        if (result instanceof String s) {
            return s;
        }
        try {
            return objectMapper.writeValueAsString(result);
        } catch (Exception e) {
            log.debug("Failed to JSON-serialize handler return ({}); falling back to toString()",
                e.getMessage());
            return result.toString();
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // SSE event builders (spec §5)
    // ─────────────────────────────────────────────────────────────────

    /**
     * Build a JSON-RPC envelope carrying an A2A v1.0
     * {@code TaskStatusUpdateEvent} (spec §5.2). Used by the SSE adapter
     * to serialize one frame.
     *
     * @param reqId       JSON-RPC request id to echo
     * @param taskId      A2A task id
     * @param a2aState    one of the four enumerated states
     * @param messageText optional text for {@code status.message.parts[0].text}
     * @param finalFlag   {@code true} only on the terminal frame — Appendix A
     *                    requires a real boolean here
     * @param progress    optional numeric progress; Appendix A requires a
     *                    number (not stringified)
     */
    public Map<String, Object> buildStatusUpdateFrame(
            Object reqId, String taskId, String a2aState, String messageText,
            boolean finalFlag, Object progress) {
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("state", a2aState);
        status.put("timestamp", utcIso8601());
        if (messageText != null && !messageText.isEmpty()) {
            Map<String, Object> message = new LinkedHashMap<>();
            message.put("role", "agent");
            message.put("parts", List.of(textPart(messageText)));
            status.put("message", message);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", taskId);
        result.put("status", status);
        // Appendix A: real boolean, not a string.
        result.put("final", finalFlag);
        if (progress != null) {
            result.put("metadata", Map.of("progress", progress));
        }

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", reqId);
        envelope.put("result", result);
        return envelope;
    }

    /**
     * Build a JSON-RPC envelope carrying an A2A v1.0
     * {@code TaskArtifactUpdateEvent} (spec §5.2). The handler result is
     * stringified per the {@code stringifyResult} contract.
     */
    public Map<String, Object> buildArtifactUpdateFrame(Object reqId, String taskId, Object value) {
        Map<String, Object> artifact = new LinkedHashMap<>();
        artifact.put("name", "result");
        artifact.put("parts", List.of(textPart(stringifyResult(value))));
        artifact.put("index", 0);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", taskId);
        result.put("artifact", artifact);

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", reqId);
        envelope.put("result", result);
        return envelope;
    }

    /** Serialize a JSON-RPC envelope as the {@code data:} payload of one SSE frame. */
    public String toJsonString(Map<String, Object> envelope) {
        return toJson(envelope);
    }

    /**
     * Peek at the {@code method} field of a JSON-RPC request body without
     * committing to a full parse. Returns {@code null} when the body is
     * empty, unparseable, or has no textual {@code method} field — callers
     * fall through to the JSON-RPC dispatcher which produces the canonical
     * parse-error response.
     *
     * <p>Reuses the dispatcher's injected {@link ObjectMapper} so the SSE
     * controller does not have to construct a fresh mapper on every POST.
     */
    public String peekJsonRpcMethod(String body) {
        if (body == null || body.isEmpty()) return null;
        try {
            tools.jackson.databind.JsonNode node = objectMapper.readTree(body);
            tools.jackson.databind.JsonNode m = node.get("method");
            return m != null && m.isTextual() ? m.asText() : null;
        } catch (Exception e) {
            return null;
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Task store interaction
    // ─────────────────────────────────────────────────────────────────

    private void cacheTerminal(String taskId, String sessionId, Map<String, Object> requestMessage,
                               Map<String, Object> envelope, JobProxy proxy) {
        taskStore.put(taskId, new MeshA2ATaskStore.TaskRecord(
            sessionId, requestMessage, envelope, System.currentTimeMillis(), proxy));
    }

    private void parkLongRunning(String taskId, String sessionId, Map<String, Object> requestMessage,
                                 JobProxy proxy) {
        // Non-terminal record: terminalEnvelope=null, terminalAt=null, jobProxy set.
        taskStore.put(taskId, new MeshA2ATaskStore.TaskRecord(
            sessionId, requestMessage, null, null, proxy));
    }

    /**
     * Mark a parked task terminal with the supplied envelope. Used by the
     * SSE long-running stream emitter to flip the record to "cached
     * terminal" so subsequent tasks/get calls return the same envelope
     * without re-polling the JobProxy.
     */
    public void markTaskTerminal(String taskId, Map<String, Object> terminalEnvelope) {
        taskStore.markTerminal(taskId, terminalEnvelope);
    }

    /**
     * Project the live status of a parked task into an A2A v1.0 Task
     * envelope. Exposed for the SSE long-running stream emitter
     * ({@link MeshA2ASseDispatcher}) so it can render terminal frames
     * consistently with {@code tasks/get}.
     */
    public Map<String, Object> projectLiveStatus(String taskId) {
        MeshA2ATaskStore.TaskRecord record = taskStore.get(taskId);
        if (record == null) return null;
        if (record.terminalEnvelope() != null) return record.terminalEnvelope();
        return buildTaskFromLiveStatus(taskId, record);
    }

    // ─────────────────────────────────────────────────────────────────
    // JSON-RPC helpers
    // ─────────────────────────────────────────────────────────────────

    private ResponseEntity<String> jsonRpcSuccessResponse(Object reqId, Object resultObj) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("jsonrpc", "2.0");
        body.put("id", reqId);
        body.put("result", resultObj);
        return ResponseEntity.ok()
            .contentType(MediaType.APPLICATION_JSON)
            .body(toJson(body));
    }

    private ResponseEntity<String> jsonRpcErrorResponse(Object reqId, int code, String message) {
        return ResponseEntity.ok()
            .contentType(MediaType.APPLICATION_JSON)
            .body(jsonRpcError(reqId, code, message));
    }

    private String jsonRpcError(Object reqId, int code, String message) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", code);
        error.put("message", message);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("jsonrpc", "2.0");
        body.put("error", error);
        body.put("id", reqId);
        return toJson(body);
    }

    private String toJson(Map<String, Object> body) {
        try {
            return objectMapper.writeValueAsString(body);
        } catch (Exception e) {
            // Truly unreachable for plain maps, but keep a defensive
            // fallback so the dispatcher never returns an empty body.
            return "{\"jsonrpc\":\"2.0\",\"error\":{\"code\":-32603,\"message\":\"Internal serialization error\"},\"id\":null}";
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Body / params parsing
    // ─────────────────────────────────────────────────────────────────

    private Object extractId(JsonNode bodyNode) {
        JsonNode idNode = bodyNode.get("id");
        if (idNode == null || idNode.isNull()) {
            return null;
        }
        if (idNode.isTextual()) return idNode.asText();
        if (idNode.isInt()) return idNode.asInt();
        if (idNode.isLong()) return idNode.asLong();
        if (idNode.isFloatingPointNumber()) return idNode.asDouble();
        if (idNode.isBoolean()) return idNode.asBoolean();
        // Spec §4.1: "id" MAY be any JSON value. Convert anything else
        // through the ObjectMapper.
        try {
            return objectMapper.convertValue(idNode, Object.class);
        } catch (Exception e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readParams(JsonNode paramsNode) {
        if (paramsNode == null || paramsNode.isNull() || !paramsNode.isObject()) {
            return new LinkedHashMap<>();
        }
        try {
            Object converted = objectMapper.convertValue(paramsNode,
                new TypeReference<Map<String, Object>>() {});
            return converted instanceof Map ? (Map<String, Object>) converted : new LinkedHashMap<>();
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    private static String stringFromParams(Map<String, Object> params, String key) {
        Object v = params.get(key);
        if (v == null) return null;
        if (v instanceof String s) return s.isEmpty() ? null : s;
        return v.toString();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mapFromParams(Map<String, Object> params, String key) {
        Object v = params.get(key);
        if (v instanceof Map<?, ?> m) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (Map.Entry<?, ?> e : m.entrySet()) {
                out.put(String.valueOf(e.getKey()), e.getValue());
            }
            return out;
        }
        return new LinkedHashMap<>();
    }

    // ─────────────────────────────────────────────────────────────────
    // Time
    // ─────────────────────────────────────────────────────────────────

    /**
     * UTC ISO-8601 with the {@code Z} suffix (NOT {@code +00:00}) per spec
     * §5.2 / Appendix A. {@link Instant#toString()} already emits the
     * right form ({@code 2026-05-11T12:34:56.789Z}).
     */
    private static String utcIso8601() {
        return Instant.now().toString();
    }

    // ─────────────────────────────────────────────────────────────────
    // Diagnostics for tests
    // ─────────────────────────────────────────────────────────────────

    /** Read-only view for tests. */
    public MeshA2ATaskStore taskStore() {
        return taskStore;
    }

    /** Read-only view for tests. */
    public MeshA2ARegistry registry() {
        return registry;
    }

    // ─────────────────────────────────────────────────────────────────
    // SSE stream-plan value classes (consumed by MeshA2ASseDispatcher)
    // ─────────────────────────────────────────────────────────────────

    /**
     * Framework-agnostic description of an SSE stream for a single
     * {@code tasks/sendSubscribe} / {@code tasks/resubscribe} call. The
     * SSE adapter ({@link MeshA2ASseDispatcher}) maps this into Spring's
     * {@code ServerResponse.sse(...)} body.
     *
     * <p>Three shapes:
     * <ul>
     *   <li>{@link Kind#ERROR} — preflight error before SSE is even started
     *       (parse error, unknown task id, missing path). Adapter emits a
     *       JSON-RPC error response, NOT an SSE stream.</li>
     *   <li>{@link Kind#SINGLE_FRAME} — one terminal SSE frame then close
     *       (sync handler completed, handler raised, already-terminal
     *       resubscribe).</li>
     *   <li>{@link Kind#SYNC_COMPLETED} — one artifact frame + one final
     *       status frame then close (sync handler called via
     *       {@code tasks/sendSubscribe}).</li>
     *   <li>{@link Kind#LONG_RUNNING} — initial working frame, then poll
     *       loop with progress frames, keepalives, and a terminal frame.</li>
     * </ul>
     */
    public static final class SseStreamPlan {
        public enum Kind { ERROR, SINGLE_FRAME, SYNC_COMPLETED, LONG_RUNNING }

        public final Kind kind;
        public final String errorBody;
        public final HttpStatus errorStatus;
        public final Map<String, Object> firstFrame;
        public final Map<String, Object> secondFrame;
        public final Object reqId;
        public final String taskId;
        public final JobProxy proxy;

        private SseStreamPlan(Kind kind, String errorBody, HttpStatus errorStatus,
                              Map<String, Object> firstFrame, Map<String, Object> secondFrame,
                              Object reqId, String taskId, JobProxy proxy) {
            this.kind = kind;
            this.errorBody = errorBody;
            this.errorStatus = errorStatus;
            this.firstFrame = firstFrame;
            this.secondFrame = secondFrame;
            this.reqId = reqId;
            this.taskId = taskId;
            this.proxy = proxy;
        }

        public static SseStreamPlan error(String body, HttpStatus status) {
            return new SseStreamPlan(Kind.ERROR, body, status, null, null, null, null, null);
        }

        public static SseStreamPlan singleFrame(Map<String, Object> frame) {
            return new SseStreamPlan(Kind.SINGLE_FRAME, null, null, frame, null, null, null, null);
        }

        /**
         * Sync-completed plan: artifact frame first, then a final status
         * frame with {@code state=completed, final=true}. Spec §5.3.
         */
        public static SseStreamPlan syncCompleted(
                Object reqId, String taskId,
                Map<String, Object> artifactFrame, Map<String, Object> terminalFrame) {
            return new SseStreamPlan(Kind.SYNC_COMPLETED, null, null,
                artifactFrame, terminalFrame, reqId, taskId, null);
        }

        public static SseStreamPlan longRunning(Object reqId, String taskId, JobProxy proxy) {
            return new SseStreamPlan(Kind.LONG_RUNNING, null, null, null, null, reqId, taskId, proxy);
        }
    }

    /**
     * One SSE frame, with the payload already serialized. The adapter
     * writes {@code data: <payload>\n\n} for data frames, or {@code <payload>\n\n}
     * directly for keepalive comments (where the payload starts with
     * {@code :} per SSE spec §5.1).
     */
    public record SseFrame(String payload, boolean isComment) {
        public static SseFrame data(String json) {
            return new SseFrame(json, false);
        }

        public static SseFrame keepalive() {
            return new SseFrame(": keepalive", true);
        }
    }
}
