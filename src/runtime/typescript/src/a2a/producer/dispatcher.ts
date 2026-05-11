/**
 * JSON-RPC 2.0 dispatcher for `mesh.a2a.mount(...)` producer surfaces
 * (spec §4).
 *
 * Chunk 1B coverage:
 * - `tasks/send` — sync handler return → `state=completed`; `JobProxy`
 *   return → `state=working` envelope with the task parked in
 *   {@link A2ATaskStore} (spec §4.3 long-running branch); handler
 *   exception → `state=failed` (spec §4.3).
 * - `tasks/get` — looks up the cached terminal envelope OR pulls live
 *   status from the parked `JobProxy` and translates the mesh state to
 *   A2A via {@link state-translator} (spec §4.4 / §7.2).
 * - `tasks/cancel` — calls `proxy.cancel()` on the parked task, then
 *   re-reads status; idempotent ack for already-terminal tasks (spec
 *   §4.5). Cancel double-failure synthesizes `state=canceled` rather
 *   than propagating exceptions.
 * - `tasks/sendSubscribe` / `tasks/resubscribe` — exposed indirectly
 *   through {@link buildSendSubscribeStream} / {@link buildResubscribeStream}
 *   which return a framework-agnostic {@link SseStreamPlan}. The Express
 *   SSE adapter ({@link sse-emitter}) materialises each plan as a
 *   `text/event-stream` response. The dispatcher itself never touches
 *   Express response streaming so it stays unit-testable without an
 *   HTTP server (spec §4.6 / §4.7 / §5).
 *
 * Error handling per spec §4.1:
 * - Empty / non-JSON body → HTTP 400 + `-32700 Parse error`
 * - Missing `method` field → `-32600 Invalid Request` (NOT `-32601`; the
 *   misleading `"Method not implemented: 'null'"` bug from issue #934
 *   must not recur)
 * - Unknown method → `-32601 Method not implemented: '<method>'`
 *
 * Handler exceptions are surfaced per spec §4.3: they become `state=failed`
 * Task envelopes, NOT JSON-RPC errors. JSON-RPC errors are reserved for
 * protocol-level issues.
 */
import type { Request, RequestHandler, Response } from "express";
import { randomUUID } from "node:crypto";

import { JobProxy } from "@mcpmesh/core";

import type { McpMeshTool } from "../../types.js";
import { RouteRegistry } from "../../route.js";
import type { A2ASurfaceMetadata } from "./registry.js";
import { A2ATaskStore, type TaskRecord } from "./task-store.js";
import {
  A2A_CANCELED,
  A2A_COMPLETED,
  A2A_FAILED,
  A2A_WORKING,
  fromMesh,
  isTerminal,
  meshStatusOf,
} from "./state-translator.js";

/** JSON-RPC: Parse error (request body is not valid JSON). Spec §4.1. */
export const JSONRPC_PARSE_ERROR = -32700;
/** JSON-RPC: Invalid Request (well-formed JSON but missing `method` field). Spec §4.1. */
export const JSONRPC_INVALID_REQUEST = -32600;
/** JSON-RPC: Method not found (unknown `tasks/*` verb). Spec §4.1. */
export const JSONRPC_METHOD_NOT_FOUND = -32601;
/** JSON-RPC: Invalid params (missing or unknown task id). Spec §4.4. */
export const JSONRPC_INVALID_PARAMS = -32602;

/**
 * Dependencies object passed to A2A handlers — keyed by capability name,
 * same shape as `mesh.route()`'s `deps` parameter. Values are `null` when
 * the underlying dependency hasn't been resolved yet (registry has not
 * reported a `dependency_available` event for it).
 */
export type A2ADependencies = Record<string, McpMeshTool | null>;

/**
 * Handler signature for `mesh.a2a.mount(...)`. Receives resolved
 * dependencies first (so destructuring is ergonomic) and the raw A2A
 * `tasks/send` `params` object second.
 *
 * Return value: any JSON-serializable value or a `JobProxy`.
 * - JSON-serializable value → framework wraps it into the A2A v1.0 `Task`
 *   envelope per spec §4.3 — `String` returns pass through verbatim;
 *   everything else is JSON-stringified.
 * - `JobProxy` → framework parks the task (`state=working`) and pulls
 *   live status on subsequent `tasks/get` / `tasks/cancel` /
 *   `tasks/sendSubscribe` / `tasks/resubscribe` calls (spec §4.3
 *   long-running branch).
 *
 * Throw an exception to surface as `state=failed` (spec §4.3 "handler
 * raised" branch).
 */
export type A2AHandler<D extends A2ADependencies = A2ADependencies> = (
  deps: D,
  payload: Record<string, unknown>
) => unknown | Promise<unknown>;

/**
 * Construction inputs for {@link A2ADispatcher}. The dispatcher itself is
 * surface-agnostic — the {@link buildDispatcherMiddleware} factory binds it
 * to a specific surface so the per-route Express middleware can dispatch
 * without consulting a path-keyed registry on every request.
 */
export interface DispatcherDeps {
  /** The registered surface this dispatcher is bound to. */
  readonly surface: A2ASurfaceMetadata;
  /** The user-supplied handler. */
  readonly handler: A2AHandler;
  /** Shared task store. */
  readonly taskStore: A2ATaskStore;
  /** Shared `RouteRegistry` for dependency resolution (DDDI). */
  readonly routeRegistry: RouteRegistry;
}

/**
 * Build an Express request handler that dispatches `POST {path}` requests
 * for a single surface.
 *
 * Routes JSON-RPC envelopes that return a single response body
 * (`tasks/send`, `tasks/get`, `tasks/cancel`). SSE verbs
 * (`tasks/sendSubscribe`, `tasks/resubscribe`) are dispatched by a
 * sibling middleware ({@link buildSseDispatcherMiddleware}) that the
 * mount wires in front of this one — when the SSE middleware sees an
 * SSE-eligible method it consumes the request; otherwise it calls
 * `next()` and execution falls through here.
 */
export function buildDispatcherMiddleware(deps: DispatcherDeps): RequestHandler {
  const { surface, handler, taskStore, routeRegistry } = deps;

  return async function a2aDispatcher(
    req: Request,
    res: Response
  ): Promise<void> {
    // Spec §4.1: malformed body → HTTP 400 + JSON-RPC -32700. Express's
    // `express.json()` middleware should have parsed the body; defensively
    // handle the case where it wasn't installed by checking for a missing
    // body object (req.body will be `undefined` then).
    const body = req.body as unknown;
    if (body === undefined || body === null) {
      writeJsonRpcParseErrorHttp400(
        res,
        "Parse error: request body is empty or not parsed (did you install express.json()?)"
      );
      return;
    }
    if (typeof body !== "object" || Array.isArray(body)) {
      writeJsonRpcParseErrorHttp400(
        res,
        "Parse error: request body must be a JSON-RPC object"
      );
      return;
    }
    const envelope = body as Record<string, unknown>;
    const reqId = extractRequestId(envelope);

    const method = envelope["method"];
    if (typeof method !== "string" || method.length === 0) {
      // Spec §4.1: well-formed JSON missing the required `method` member is
      // an Invalid Request (-32600), NOT Method not found (-32601). Without
      // this guard the default branch would emit a misleading
      // "Method not implemented: 'null'" — the bug surfaced in issue #934
      // when the Java body-read path silently dropped the parsed body.
      writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_REQUEST,
        "Invalid Request: 'method' field is required and must be a string"));
      return;
    }

    const params = readParams(envelope["params"]);

    switch (method) {
      case "tasks/send":
        await handleTasksSend(req, res, reqId, params, {
          surface,
          handler,
          taskStore,
          routeRegistry,
        });
        return;

      case "tasks/get":
        await handleTasksGet(res, reqId, params, taskStore);
        return;

      case "tasks/cancel":
        await handleTasksCancel(res, reqId, params, taskStore);
        return;

      case "tasks/sendSubscribe":
      case "tasks/resubscribe":
        // SSE methods are handled by the sibling SSE-middleware. If we
        // see them here it means the SSE middleware fell through — most
        // commonly because the client did not send `Accept: text/event-stream`.
        // Surface a clear error matching Java's MeshA2ADispatcher.
        writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_METHOD_NOT_FOUND,
          `Method '${method}' requires an SSE-capable client. ` +
          `Set 'Accept: text/event-stream' or use a streaming HTTP client.`));
        return;

      default:
        writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_METHOD_NOT_FOUND,
          `Method not implemented: '${method}'. ` +
          `Supported A2A v1.0 methods: tasks/send, tasks/get, tasks/cancel, tasks/sendSubscribe, tasks/resubscribe.`));
        return;
    }
  };
}

// ─────────────────────────────────────────────────────────────────────────
// tasks/send
// ─────────────────────────────────────────────────────────────────────────

async function handleTasksSend(
  _req: Request,
  res: Response,
  reqId: unknown,
  params: Record<string, unknown>,
  deps: DispatcherDeps
): Promise<void> {
  // Spec §4.2: extract (task_id, session_id, message).
  let taskId = stringFromParams(params, "id");
  if (!taskId) {
    taskId = randomUUID();
  }
  let sessionId = stringFromParams(params, "sessionId");
  if (!sessionId) {
    sessionId = taskId;
  }
  const message = mapFromParams(params, "message");

  // Spec §4.3: duplicate in-flight task_id → -32602 already in use.
  // Terminal entries within the eviction window are also rejected.
  if (deps.taskStore.contains(taskId)) {
    writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
      `A2A task id '${taskId}' is already in use`));
    return;
  }

  // Resolve dependencies the same way mesh.route() does — via the shared
  // RouteRegistry. The surface registered a synthetic route at mount time
  // (see mount.ts); resolved McpMeshTool proxies surface here keyed by
  // capability name.
  const resolvedDeps = deps.routeRegistry.getDependenciesForRoute(
    deps.surface.routeId
  );
  // Ensure every declared capability key is present (null when unresolved)
  // — the user's destructure shouldn't crash on a partially-resolved
  // dependency graph.
  for (const dep of deps.surface.dependencies) {
    if (resolvedDeps[dep.capability] === undefined) {
      resolvedDeps[dep.capability] = null;
    }
  }

  let handlerResult: unknown;
  try {
    handlerResult = await deps.handler(resolvedDeps, message);
  } catch (err) {
    // Spec §4.3 "Response — handler raised": exceptions become
    // state=failed Tasks, NOT JSON-RPC errors.
    const errorText = errorTextOf(err);
    const envelope = buildFailedTask(taskId, sessionId, message, errorText);
    deps.taskStore.put(taskId, {
      sessionId,
      requestMessage: hasOwn(message) ? message : undefined,
      terminalEnvelope: envelope,
      terminalAt: Date.now(),
      jobProxy: null,
    });
    writeJsonRpc(res, jsonRpcSuccess(reqId, envelope));
    return;
  }

  // Spec §4.3 long-running branch: handler returned a JobProxy →
  // park the task and respond with state=working immediately. The
  // client polls tasks/get / tasks/sendSubscribe for progress and
  // the terminal artifact.
  if (isJobProxy(handlerResult)) {
    const envelope = buildWorkingTask(taskId, sessionId, message);
    parkLongRunning(deps.taskStore, taskId, sessionId, message, handlerResult);
    writeJsonRpc(res, jsonRpcSuccess(reqId, envelope));
    return;
  }

  // Sync path: handler returned a value → state=completed envelope.
  const envelope = buildCompletedTask(taskId, sessionId, message, handlerResult);
  deps.taskStore.put(taskId, {
    sessionId,
    requestMessage: hasOwn(message) ? message : undefined,
    terminalEnvelope: envelope,
    terminalAt: Date.now(),
    jobProxy: null,
  });
  writeJsonRpc(res, jsonRpcSuccess(reqId, envelope));
}

// ─────────────────────────────────────────────────────────────────────────
// tasks/get
// ─────────────────────────────────────────────────────────────────────────

async function handleTasksGet(
  res: Response,
  reqId: unknown,
  params: Record<string, unknown>,
  taskStore: A2ATaskStore
): Promise<void> {
  const taskId = stringFromParams(params, "id");
  if (!taskId) {
    writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
      "Invalid params: 'id' is required for tasks/get"));
    return;
  }
  const record = taskStore.get(taskId);
  if (!record) {
    writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
      `Unknown task id: ${taskId}`));
    return;
  }
  if (record.terminalEnvelope) {
    writeJsonRpc(res, jsonRpcSuccess(reqId, record.terminalEnvelope));
    return;
  }
  // Non-terminal record: pull live status from the parked JobProxy.
  // Per spec §4.4 "transient unreachability": if status() throws we
  // return state=working with the error text in status.message rather
  // than a JSON-RPC error — the registry's transient failure isn't
  // authoritative evidence the job is dead.
  const envelope = await buildTaskFromLiveStatus(taskStore, taskId, record);
  writeJsonRpc(res, jsonRpcSuccess(reqId, envelope));
}

// ─────────────────────────────────────────────────────────────────────────
// tasks/cancel
// ─────────────────────────────────────────────────────────────────────────

async function handleTasksCancel(
  res: Response,
  reqId: unknown,
  params: Record<string, unknown>,
  taskStore: A2ATaskStore
): Promise<void> {
  const taskId = stringFromParams(params, "id");
  if (!taskId) {
    writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
      "Invalid params: 'id' is required for tasks/cancel"));
    return;
  }
  const record = taskStore.get(taskId);
  if (!record) {
    writeJsonRpc(res, jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
      `Unknown task id: ${taskId}`));
    return;
  }

  // Idempotent ack: already-terminal task → echo the cached envelope.
  // Spec §4.5 "Idempotent; best-effort".
  if (record.terminalEnvelope) {
    writeJsonRpc(res, jsonRpcSuccess(reqId, record.terminalEnvelope));
    return;
  }

  const reason = stringFromParams(params, "reason") ?? undefined;
  const proxy = record.jobProxy ?? null;
  let cancelThrew = false;
  if (proxy) {
    try {
      await proxy.cancel(reason);
    } catch {
      // Spec §4.5: cancel exceptions are logged and swallowed — the
      // underlying job may already be terminal.
      cancelThrew = true;
    }
  }

  // Re-read status post-cancel so the response reflects the latest
  // state. Java's BLOCKER fix from #934: if BOTH cancel() AND status()
  // throw (double-failure), synthesize a state=canceled envelope rather
  // than propagating exceptions (spec §4.5 fallback).
  let envelope: Record<string, unknown>;
  let statusThrew = false;
  if (proxy) {
    try {
      envelope = await buildTaskFromLiveStatusInternal(taskId, record, proxy);
    } catch {
      statusThrew = true;
      envelope = buildCanceledTask(taskId, record.sessionId, record.requestMessage, reason);
    }
  } else {
    // Lost-JobProxy on a non-terminal record — spec §4.5 best-effort
    // cancel says synthesize state=canceled rather than returning an
    // error. Match Java's behaviour.
    envelope = buildCanceledTask(taskId, record.sessionId, record.requestMessage, reason);
  }

  // If the post-cancel state is terminal, mark the record so future
  // tasks/get calls hit the cached envelope and don't re-poll a closed
  // JobProxy.
  const statusObj = (envelope["status"] as Record<string, unknown> | undefined);
  const state = typeof statusObj?.["state"] === "string" ? (statusObj["state"] as string) : null;
  if (state && isTerminal(state)) {
    taskStore.markTerminal(taskId, envelope);
  } else if (cancelThrew && statusThrew) {
    // Double-failure path already produced a synthesized canceled
    // envelope above — mark terminal so the client sees a stable cached
    // response on retry.
    taskStore.markTerminal(taskId, envelope);
  } else {
    // Status didn't show terminal yet but cancel was requested —
    // synthesize a canceled envelope so the client gets a clean terminal
    // response. Matches Python's a2a.py:817-826 fallback.
    const synth = buildCanceledTask(taskId, record.sessionId, record.requestMessage, reason);
    taskStore.markTerminal(taskId, synth);
    envelope = synth;
  }
  writeJsonRpc(res, jsonRpcSuccess(reqId, envelope));
}

// ─────────────────────────────────────────────────────────────────────────
// tasks/sendSubscribe + tasks/resubscribe (SSE plan builders)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Build the SSE stream plan for a `tasks/sendSubscribe` request. The
 * dispatcher invokes the user handler eagerly (before the stream opens)
 * so handler exceptions become a single SSE failed frame, not an opaque
 * HTTP error mid-stream (spec §4.6).
 */
export async function buildSendSubscribeStream(
  reqId: unknown,
  params: Record<string, unknown>,
  deps: DispatcherDeps
): Promise<SseStreamPlan> {
  let taskId = stringFromParams(params, "id");
  if (!taskId) {
    taskId = randomUUID();
  }
  let sessionId = stringFromParams(params, "sessionId");
  if (!sessionId) {
    sessionId = taskId;
  }
  const message = mapFromParams(params, "message");

  if (deps.taskStore.contains(taskId)) {
    // Duplicate in-flight task_id — surface as a single SSE failed
    // event so the SSE client sees a structured A2A failure rather
    // than an opaque HTTP error (Python a2a.py:1143-1149).
    return sseSingleFrame(buildStatusUpdateFrame(
      reqId, taskId, A2A_FAILED,
      `A2A task id '${taskId}' is already in use`, true, null
    ));
  }

  const resolvedDeps = deps.routeRegistry.getDependenciesForRoute(
    deps.surface.routeId
  );
  for (const dep of deps.surface.dependencies) {
    if (resolvedDeps[dep.capability] === undefined) {
      resolvedDeps[dep.capability] = null;
    }
  }

  let handlerResult: unknown;
  try {
    handlerResult = await deps.handler(resolvedDeps, message);
  } catch (err) {
    const errorText = errorTextOf(err);
    // Cache the failed envelope so a subsequent tasks/get returns it
    // consistently with the JSON-RPC path.
    const failed = buildFailedTask(taskId, sessionId, message, errorText);
    deps.taskStore.put(taskId, {
      sessionId,
      requestMessage: hasOwn(message) ? message : undefined,
      terminalEnvelope: failed,
      terminalAt: Date.now(),
      jobProxy: null,
    });
    return sseSingleFrame(buildStatusUpdateFrame(
      reqId, taskId, A2A_FAILED, errorText, true, null
    ));
  }

  if (isJobProxy(handlerResult)) {
    parkLongRunning(deps.taskStore, taskId, sessionId, message, handlerResult);
    return sseLongRunning(reqId, taskId, handlerResult);
  }

  // Sync handler over tasks/sendSubscribe: per spec §5.3, emit one
  // artifact event then one final status event (state=completed).
  const artifactFrame = buildArtifactUpdateFrame(reqId, taskId, handlerResult);
  const terminalFrame = buildStatusUpdateFrame(
    reqId, taskId, A2A_COMPLETED, null, true, null
  );
  // Cache the resulting envelope so a follow-up tasks/get returns the
  // same payload deterministically.
  const envelope = buildCompletedTask(taskId, sessionId, message, handlerResult);
  deps.taskStore.put(taskId, {
    sessionId,
    requestMessage: hasOwn(message) ? message : undefined,
    terminalEnvelope: envelope,
    terminalAt: Date.now(),
    jobProxy: null,
  });
  return sseSyncCompleted(reqId, taskId, artifactFrame, terminalFrame);
}

/**
 * Build the SSE stream plan for a `tasks/resubscribe` request (spec §4.7).
 * Looks up the parked task, emits an initial state=working event, then
 * resumes polling from the registry's current view (no replay).
 */
export function buildResubscribeStream(
  reqId: unknown,
  params: Record<string, unknown>,
  taskStore: A2ATaskStore
): SseStreamPlan {
  const taskId = stringFromParams(params, "id");
  if (!taskId) {
    // Spec §4.7 errors: return JSON-RPC, not SSE — the response has not
    // been promoted to text/event-stream yet.
    return sseError(
      jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
        "Invalid params: 'id' is required for tasks/resubscribe"),
      200
    );
  }
  const record = taskStore.get(taskId);
  if (!record) {
    return sseError(
      jsonRpcError(reqId, JSONRPC_INVALID_PARAMS,
        `Unknown task id: ${taskId}`),
      200
    );
  }
  if (record.terminalEnvelope) {
    // Already terminal — emit ONE terminal status event and close.
    // No replay per Python's a2a.py:1175-1178.
    const env = record.terminalEnvelope;
    const statusObj = env["status"] as Record<string, unknown> | undefined;
    let state = A2A_COMPLETED;
    let msgText: string | null = null;
    if (statusObj) {
      const st = statusObj["state"];
      if (typeof st === "string") state = st;
      const msg = statusObj["message"] as Record<string, unknown> | undefined;
      if (msg && typeof msg === "object") {
        const parts = msg["parts"];
        if (Array.isArray(parts) && parts.length > 0) {
          const first = parts[0] as Record<string, unknown> | undefined;
          const text = first?.["text"];
          if (text !== undefined && text !== null) {
            msgText = String(text);
          }
        }
      }
    }
    return sseSingleFrame(buildStatusUpdateFrame(
      reqId, taskId, state, msgText, true, null
    ));
  }
  const proxy = record.jobProxy ?? null;
  if (!proxy) {
    // Non-terminal record without a JobProxy is an inconsistent state.
    // Java's BLOCKER fix from #934: emit a single failed terminal event
    // so the client doesn't hang the SSE connection.
    return sseSingleFrame(buildStatusUpdateFrame(
      reqId, taskId, A2A_FAILED,
      "Task state inconsistent: no live JobProxy and no terminal envelope",
      true, null
    ));
  }
  return sseLongRunning(reqId, taskId, proxy);
}

// ─────────────────────────────────────────────────────────────────────────
// Live-status poll (shared by tasks/get + SSE emitter terminal frame)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Pull the latest status from a parked task's `JobProxy` and project it
 * into an A2A v1.0 Task envelope. Handles the "transient unreachability"
 * branch per spec §4.4 by returning `state=working` with the error text
 * in `status.message` rather than throwing — matches Python's
 * `a2a.py:718-735` behavior.
 *
 * Used by `tasks/get` (top-level dispatcher) and exposed via
 * {@link projectLiveStatus} for the SSE emitter's terminal-frame
 * synthesis.
 */
export async function buildTaskFromLiveStatus(
  _taskStore: A2ATaskStore,
  taskId: string,
  record: TaskRecord
): Promise<Record<string, unknown>> {
  const proxy = record.jobProxy ?? null;
  if (!proxy) {
    return buildWorkingTask(taskId, record.sessionId, record.requestMessage);
  }
  return buildTaskFromLiveStatusInternal(taskId, record, proxy);
}

async function buildTaskFromLiveStatusInternal(
  taskId: string,
  record: TaskRecord,
  proxy: JobProxy
): Promise<Record<string, unknown>> {
  let status: Record<string, unknown>;
  try {
    const raw = (await proxy.status()) as unknown;
    status = (raw && typeof raw === "object" && !Array.isArray(raw))
      ? (raw as Record<string, unknown>)
      : {};
  } catch (err) {
    // Spec §4.4: transient unreachability → state=working + error text in
    // status.message. Do NOT escalate to JSON-RPC error.
    return buildWorkingTask(
      taskId,
      record.sessionId,
      record.requestMessage,
      `status unavailable: ${errorTextOf(err)}`
    );
  }

  const meshState = meshStatusOf(status);
  const a2aState = fromMesh(meshState);

  // On completed, attempt proxy.wait(timeoutSecs=1) to fetch the final
  // artifact synchronously. Tight timeout per spec §4.4 so we don't
  // block on a transiently-unreachable payload — fall back to no
  // artifact in that case. On failed/canceled, do NOT call wait() —
  // it would throw and the error text is already in status.error /
  // status.progress_message.
  let finalResult: unknown = null;
  let hasFinalResult = false;
  if (a2aState === A2A_COMPLETED) {
    try {
      finalResult = await proxy.wait(1.0);
      hasFinalResult = true;
    } catch {
      // Best-effort: artifact omitted if the result payload is
      // transiently unreachable.
    }
  }

  return buildTaskFromStatus(
    taskId,
    record.sessionId,
    record.requestMessage,
    a2aState,
    status,
    finalResult,
    hasFinalResult
  );
}

/**
 * Project the live status of a parked task into an A2A v1.0 Task
 * envelope. Exposed for the SSE emitter so it can render terminal
 * frames consistently with `tasks/get`.
 */
export async function projectLiveStatus(
  taskStore: A2ATaskStore,
  taskId: string
): Promise<Record<string, unknown> | null> {
  const record = taskStore.get(taskId);
  if (!record) return null;
  if (record.terminalEnvelope) return record.terminalEnvelope;
  return buildTaskFromLiveStatus(taskStore, taskId, record);
}

// ─────────────────────────────────────────────────────────────────────────
// Task envelope builders (spec §4.3)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Build a `state=completed` Task envelope (spec §4.3). The handler result
 * is stringified per the spec — string returns pass through verbatim,
 * everything else is JSON-stringified. `null` / `undefined` produce an
 * empty-string artifact.
 *
 * Exported for testability + the symmetry with the SSE artifact frame
 * builder.
 */
export function buildCompletedTask(
  taskId: string,
  sessionId: string,
  requestMessage: Record<string, unknown>,
  result: unknown
): Record<string, unknown> {
  const text = stringifyResult(result);
  return {
    id: taskId,
    sessionId,
    status: {
      state: A2A_COMPLETED,
      timestamp: utcIso8601(),
    },
    artifacts: [
      {
        name: "result",
        // Appendix A: parts[0].type MUST be emitted as "text" for forward
        // compatibility even though consumers ignore it.
        parts: [{ type: "text", text }],
        index: 0,
      },
    ],
    history: historyOf(requestMessage),
  };
}

/**
 * Build a `state=failed` Task envelope (spec §4.3 "handler raised"
 * branch). The error text is folded into `status.message.parts[0].text`.
 */
export function buildFailedTask(
  taskId: string,
  sessionId: string,
  requestMessage: Record<string, unknown>,
  errorText: string
): Record<string, unknown> {
  return {
    id: taskId,
    sessionId,
    status: {
      state: A2A_FAILED,
      timestamp: utcIso8601(),
      message: {
        role: "agent",
        parts: [{ type: "text", text: errorText }],
      },
    },
    artifacts: [],
    history: historyOf(requestMessage),
  };
}

/**
 * Build a `state=working` Task envelope (spec §4.3 long-running branch /
 * spec §4.4 transient unreachability fallback).
 */
export function buildWorkingTask(
  taskId: string,
  sessionId: string,
  requestMessage?: Record<string, unknown>,
  progressMessage?: string | null,
  progress?: number | null
): Record<string, unknown> {
  const status: Record<string, unknown> = {
    state: A2A_WORKING,
    timestamp: utcIso8601(),
  };
  if (progressMessage && progressMessage.length > 0) {
    status.message = {
      role: "agent",
      parts: [{ type: "text", text: progressMessage }],
    };
  }
  const envelope: Record<string, unknown> = {
    id: taskId,
    sessionId,
    status,
    artifacts: [],
    history: historyOf(requestMessage ?? {}),
  };
  if (progress !== undefined && progress !== null) {
    envelope.metadata = { progress };
  }
  return envelope;
}

/**
 * Build a `state=canceled` Task envelope (spec §4.5 cancel fallback / spec
 * §7.2). Used when:
 * - `tasks/cancel` post-cancel status read didn't show terminal yet, OR
 * - both `proxy.cancel()` AND `proxy.status()` threw, OR
 * - the parked task lost its `JobProxy` reference.
 */
export function buildCanceledTask(
  taskId: string,
  sessionId: string,
  requestMessage: Record<string, unknown> | undefined,
  reason: string | undefined
): Record<string, unknown> {
  const status: Record<string, unknown> = {
    state: A2A_CANCELED,
    timestamp: utcIso8601(),
  };
  if (reason && reason.length > 0) {
    status.message = {
      role: "agent",
      parts: [{ type: "text", text: reason }],
    };
  }
  return {
    id: taskId,
    sessionId,
    status,
    artifacts: [],
    history: historyOf(requestMessage ?? {}),
  };
}

/**
 * Build a Task envelope from a `JobProxy.status()` result dict (spec
 * §4.4). Mirrors Python's `_build_task_from_status` and Java's
 * `MeshA2ADispatcher.buildTaskFromStatus` — folds `error` /
 * `progress_message` into A2A `status.message`, materialises an artifact
 * for completed tasks when the final result is available, and lifts
 * `progress` to `metadata.progress`.
 *
 * Per Appendix A, `progress` is emitted as a real JSON number (no
 * stringification) and `parts[0].type` is always `"text"`.
 */
export function buildTaskFromStatus(
  taskId: string,
  sessionId: string,
  requestMessage: Record<string, unknown> | undefined,
  a2aState: string,
  meshStatus: Record<string, unknown>,
  finalResult: unknown,
  hasFinalResult: boolean
): Record<string, unknown> {
  const status: Record<string, unknown> = {
    state: a2aState,
    timestamp: utcIso8601(),
  };

  let msgText: string | null = null;
  if (a2aState === A2A_FAILED) {
    const err = meshStatus["error"];
    if (err !== null && err !== undefined && String(err).length > 0) {
      msgText = String(err);
    } else {
      const pm = meshStatus["progress_message"];
      if (pm !== null && pm !== undefined && String(pm).length > 0) {
        msgText = String(pm);
      }
    }
  } else {
    const pm = meshStatus["progress_message"];
    if (pm !== null && pm !== undefined && String(pm).length > 0) {
      msgText = String(pm);
    }
  }
  if (msgText) {
    status.message = {
      role: "agent",
      parts: [{ type: "text", text: msgText }],
    };
  }

  const artifacts: Array<Record<string, unknown>> = [];
  if (hasFinalResult && a2aState === A2A_COMPLETED) {
    artifacts.push({
      name: "result",
      parts: [{ type: "text", text: stringifyResult(finalResult) }],
      index: 0,
    });
  }

  const envelope: Record<string, unknown> = {
    id: taskId,
    sessionId,
    status,
    artifacts,
    history: historyOf(requestMessage ?? {}),
  };
  const progress = meshStatus["progress"];
  if (progress !== null && progress !== undefined) {
    envelope.metadata = { progress };
  }
  return envelope;
}

/**
 * Stringify a handler return value as the text body of the `result`
 * artifact. `string` returns pass through verbatim; everything else is
 * JSON-stringified. Non-serializable returns fall back to `String(value)`
 * so the artifact is always well-formed (mirrors Python's `default=str`
 * coercion in `a2a.py:403`).
 */
export function stringifyResult(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function historyOf(
  requestMessage: Record<string, unknown> | undefined
): Array<Record<string, unknown>> {
  if (!requestMessage || !hasOwn(requestMessage)) {
    return [];
  }
  return [{ ...requestMessage }];
}

// ─────────────────────────────────────────────────────────────────────────
// SSE frame builders (spec §5)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Build a JSON-RPC envelope carrying an A2A v1.0 `TaskStatusUpdateEvent`
 * (spec §5.2).
 *
 * Per Appendix A:
 * - `final` MUST be a real JSON boolean (no stringification).
 * - `progress` (when non-null) MUST be a JSON number.
 * - `parts[0].type` MUST be emitted as `"text"`.
 *
 * @param reqId       JSON-RPC request id to echo
 * @param taskId      A2A task id
 * @param a2aState    one of the four enumerated A2A states
 * @param messageText optional text for `status.message.parts[0].text`
 * @param finalFlag   `true` only on the terminal frame
 * @param progress    optional numeric progress; emitted as `metadata.progress`
 */
export function buildStatusUpdateFrame(
  reqId: unknown,
  taskId: string,
  a2aState: string,
  messageText: string | null | undefined,
  finalFlag: boolean,
  progress: number | null | undefined
): Record<string, unknown> {
  const status: Record<string, unknown> = {
    state: a2aState,
    timestamp: utcIso8601(),
  };
  if (messageText && messageText.length > 0) {
    status.message = {
      role: "agent",
      parts: [{ type: "text", text: messageText }],
    };
  }

  const result: Record<string, unknown> = {
    id: taskId,
    status,
    // Appendix A: real boolean, not a string.
    final: finalFlag,
  };
  if (progress !== null && progress !== undefined) {
    result.metadata = { progress };
  }

  return {
    jsonrpc: "2.0",
    id: reqId ?? null,
    result,
  };
}

/**
 * Build a JSON-RPC envelope carrying an A2A v1.0 `TaskArtifactUpdateEvent`
 * (spec §5.2). The handler result is stringified per the
 * {@link stringifyResult} contract.
 */
export function buildArtifactUpdateFrame(
  reqId: unknown,
  taskId: string,
  value: unknown
): Record<string, unknown> {
  return {
    jsonrpc: "2.0",
    id: reqId ?? null,
    result: {
      id: taskId,
      artifact: {
        name: "result",
        parts: [{ type: "text", text: stringifyResult(value) }],
        index: 0,
      },
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// JobProxy detection
// ─────────────────────────────────────────────────────────────────────────

/**
 * `instanceof`-based detection with duck-type fallback. JobProxy is a
 * napi-rs class that survives across module loaders; using `instanceof`
 * first matches Java's branching. The duck-type fallback covers any
 * future case where a JobProxy-shaped object is returned (subclass /
 * test double).
 */
function isJobProxy(value: unknown): value is JobProxy {
  if (value instanceof JobProxy) return true;
  if (value === null || value === undefined) return false;
  if (typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v["status"] === "function" &&
    typeof v["wait"] === "function" &&
    typeof v["cancel"] === "function" &&
    typeof v["jobId"] === "string"
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Task store helpers
// ─────────────────────────────────────────────────────────────────────────

function parkLongRunning(
  taskStore: A2ATaskStore,
  taskId: string,
  sessionId: string,
  message: Record<string, unknown>,
  proxy: JobProxy
): void {
  taskStore.put(taskId, {
    sessionId,
    requestMessage: hasOwn(message) ? message : undefined,
    // terminalEnvelope + terminalAt undefined: non-terminal record.
    jobProxy: proxy,
  });
}

// ─────────────────────────────────────────────────────────────────────────
// JSON-RPC helpers
// ─────────────────────────────────────────────────────────────────────────

function jsonRpcSuccess(reqId: unknown, result: unknown): Record<string, unknown> {
  return { jsonrpc: "2.0", id: reqId ?? null, result };
}

function jsonRpcError(
  reqId: unknown,
  code: number,
  message: string
): Record<string, unknown> {
  return {
    jsonrpc: "2.0",
    error: { code, message },
    id: reqId ?? null,
  };
}

function writeJsonRpc(res: Response, body: Record<string, unknown>): void {
  res.status(200).type("application/json").send(JSON.stringify(body));
}

function writeJsonRpcParseErrorHttp400(res: Response, message: string): void {
  res.status(400).type("application/json").send(
    JSON.stringify({
      jsonrpc: "2.0",
      error: { code: JSONRPC_PARSE_ERROR, message },
      id: null,
    })
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Param + envelope parsing
// ─────────────────────────────────────────────────────────────────────────

function extractRequestId(envelope: Record<string, unknown>): unknown {
  // Spec §4.1: `id` MAY be any JSON value the client picks; echo back
  // verbatim (including `null` and 0). Returning `undefined` here causes
  // `jsonRpcSuccess` / `jsonRpcError` to substitute `null` per JSON-RPC.
  if (!Object.prototype.hasOwnProperty.call(envelope, "id")) {
    return undefined;
  }
  return envelope["id"];
}

function readParams(params: unknown): Record<string, unknown> {
  if (params === null || params === undefined) return {};
  if (typeof params !== "object" || Array.isArray(params)) return {};
  return params as Record<string, unknown>;
}

function stringFromParams(
  params: Record<string, unknown>,
  key: string
): string | null {
  const v = params[key];
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v.length === 0 ? null : v;
  return String(v);
}

function mapFromParams(
  params: Record<string, unknown>,
  key: string
): Record<string, unknown> {
  const v = params[key];
  if (v === null || v === undefined) return {};
  if (typeof v !== "object" || Array.isArray(v)) return {};
  return { ...(v as Record<string, unknown>) };
}

function hasOwn(obj: Record<string, unknown> | undefined | null): boolean {
  if (!obj) return false;
  for (const _key in obj) {
    if (Object.prototype.hasOwnProperty.call(obj, _key)) return true;
  }
  return false;
}

function errorTextOf(err: unknown): string {
  if (err instanceof Error) {
    return err.message || err.name || "Error";
  }
  if (typeof err === "string") return err;
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}

/**
 * UTC ISO-8601 with the `Z` suffix (NOT `+00:00`) per spec §5.2 /
 * Appendix A. `Date.prototype.toISOString()` already emits the right form
 * (`2026-05-11T12:34:56.789Z`).
 */
function utcIso8601(): string {
  return new Date().toISOString();
}

// ─────────────────────────────────────────────────────────────────────────
// SSE stream plan (consumed by sse-emitter.ts)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Framework-agnostic description of an SSE stream for a single
 * `tasks/sendSubscribe` / `tasks/resubscribe` call. The Express SSE
 * adapter ({@link sse-emitter}) maps this into a `text/event-stream`
 * response body.
 *
 * Four shapes:
 * - `error` — preflight error before SSE is even started (parse error,
 *   unknown task id, missing path). Adapter emits a JSON-RPC error
 *   response, NOT an SSE stream.
 * - `single-frame` — one terminal SSE frame then close (sync handler
 *   completed, handler raised, already-terminal resubscribe).
 * - `sync-completed` — one artifact frame + one final status frame then
 *   close (sync handler called via `tasks/sendSubscribe`).
 * - `long-running` — initial working frame, then poll loop with progress
 *   frames, keepalives, and a terminal frame.
 */
export type SseStreamPlan =
  | {
      readonly kind: "error";
      readonly errorBody: Record<string, unknown>;
      readonly httpStatus: number;
    }
  | {
      readonly kind: "single-frame";
      readonly frame: Record<string, unknown>;
    }
  | {
      readonly kind: "sync-completed";
      readonly reqId: unknown;
      readonly taskId: string;
      readonly artifactFrame: Record<string, unknown>;
      readonly terminalFrame: Record<string, unknown>;
    }
  | {
      readonly kind: "long-running";
      readonly reqId: unknown;
      readonly taskId: string;
      readonly proxy: JobProxy;
    };

function sseError(
  errorBody: Record<string, unknown>,
  httpStatus: number
): SseStreamPlan {
  return { kind: "error", errorBody, httpStatus };
}

function sseSingleFrame(frame: Record<string, unknown>): SseStreamPlan {
  return { kind: "single-frame", frame };
}

function sseSyncCompleted(
  reqId: unknown,
  taskId: string,
  artifactFrame: Record<string, unknown>,
  terminalFrame: Record<string, unknown>
): SseStreamPlan {
  return { kind: "sync-completed", reqId, taskId, artifactFrame, terminalFrame };
}

function sseLongRunning(
  reqId: unknown,
  taskId: string,
  proxy: JobProxy
): SseStreamPlan {
  return { kind: "long-running", reqId, taskId, proxy };
}

// Re-export helpers under more obvious names for the SSE emitter so it
// doesn't need to import every individual builder.
export {
  isJobProxy as __isJobProxyForTests,
};
