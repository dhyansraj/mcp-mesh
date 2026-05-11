/**
 * Express SSE adapter for the framework-agnostic
 * {@link SseStreamPlan} produced by {@link buildSendSubscribeStream} /
 * {@link buildResubscribeStream} (spec §4.6 / §4.7 / §5).
 *
 * The dispatcher returns a stream-plan value object describing one of
 * four SSE shapes. This adapter materialises that plan as `data: <json>\n\n`
 * frames on an Express {@link Response} plus `: keepalive\n\n` comment
 * lines every {@link KEEPALIVE_MILLIS} milliseconds of inactivity.
 *
 * ## Why a separate file?
 *
 * Keeping the dispatcher framework-agnostic makes it unit-testable
 * without an HTTP server. This adapter contains the only dependency on
 * Express's `Response` streaming API. Mirrors Java's
 * `MeshA2ASseDispatcher` → `MeshA2ADispatcher` split.
 *
 * ## Client-disconnect handling
 *
 * Per spec §7.3 / §5.4: a client-side SSE disconnect MUST NOT cancel the
 * underlying job — the client may rejoin via `tasks/resubscribe`. We
 * detect disconnect via:
 *   1. `res.writableEnded` / `res.destroyed` (Node http.ServerResponse).
 *   2. `res.write(...)` returning `false` on an already-closed socket.
 *   3. `req.on("close", ...)` firing while the poll loop is sleeping.
 * In all three cases we exit the loop cleanly without calling
 * `JobProxy.cancel()` — the job continues running and the task store is
 * preserved.
 *
 * ## BLOCKER-fix invariants (Java #934 carry-over)
 *
 * 1. Transient `proxy.status()` failures during the poll loop emit a
 *    `state=working` (NOT terminal `state=failed`) frame and continue
 *    polling. Spec §4.4 conformance: transient unreachability is NOT
 *    authoritative evidence the job is dead.
 *
 * 2. After {@link MAX_CONSECUTIVE_STATUS_FAILURES} consecutive status()
 *    exceptions the adapter closes the SSE stream WITHOUT marking the
 *    task store record terminal — subsequent `tasks/get` resumes
 *    polling normally.
 *
 * 3. The {@link MAX_STREAM_MILLIS} cap emits a `state=working, final=false`
 *    frame (NOT `final=true`) so the client knows to reconnect via
 *    `tasks/resubscribe` — the task is still running, only the SSE
 *    transport is closed.
 */
import type { Request, RequestHandler, Response } from "express";
import type { JobProxy } from "@mcpmesh/core";

import { A2ATaskStore } from "./task-store.js";
import {
  buildArtifactUpdateFrame,
  buildResubscribeStream,
  buildSendSubscribeStream,
  buildStatusUpdateFrame,
  buildTaskFromStatus,
  type DispatcherDeps,
  type SseStreamPlan,
  JSONRPC_PARSE_ERROR,
} from "./dispatcher.js";
import {
  A2A_COMPLETED,
  A2A_FAILED,
  A2A_CANCELED,
  A2A_WORKING,
  fromMesh,
  isMeshTerminal,
  meshStatusOf,
} from "./state-translator.js";

/** Poll cadence for the long-running stream (spec §4.6 sequence diagram: 1s). */
export const POLL_INTERVAL_MILLIS = 1000;
/** Keepalive interval — SSE comment frame after this much inactivity (spec §5.1: 15s). */
export const KEEPALIVE_MILLIS = 15_000;
/** Maximum total stream duration as a defensive cap (1 hour, matches Java). */
export const MAX_STREAM_MILLIS = 60 * 60_000;
/**
 * Consecutive `proxy.status()` failures to tolerate during the SSE poll
 * loop before giving up. Spec §4.4: transient unreachability is NOT
 * authoritative evidence the job is dead, so we keep emitting
 * `state=working` status frames and continue polling until this cap.
 * Once reached we close the SSE stream WITHOUT marking the task store
 * record terminal — subsequent `tasks/get` resumes polling normally.
 *
 * Matches Java's `MAX_CONSECUTIVE_STATUS_FAILURES`.
 */
export const MAX_CONSECUTIVE_STATUS_FAILURES = 5;

/**
 * Build the SSE dispatcher middleware. Mounted in front of the JSON-RPC
 * dispatcher: when the request body's `method` is `tasks/sendSubscribe`
 * or `tasks/resubscribe`, this middleware consumes the request and
 * streams an SSE response. Otherwise it calls `next()` and execution
 * falls through to the JSON-RPC dispatcher.
 *
 * The middleware peeks at the parsed body (`req.body.method`) rather
 * than `Accept` header — even when the client sends both, we want to
 * route by JSON-RPC method to keep the dispatch deterministic.
 */
export function buildSseDispatcherMiddleware(deps: DispatcherDeps): RequestHandler {
  return async function a2aSseDispatcher(req, res, next): Promise<void> {
    const body = req.body as unknown;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      // Let the JSON-RPC dispatcher emit the canonical parse error.
      next();
      return;
    }
    const envelope = body as Record<string, unknown>;
    const method = envelope["method"];
    if (method !== "tasks/sendSubscribe" && method !== "tasks/resubscribe") {
      next();
      return;
    }
    const reqId = Object.prototype.hasOwnProperty.call(envelope, "id")
      ? envelope["id"]
      : null;
    const params = readParams(envelope["params"]);

    let plan: SseStreamPlan;
    try {
      if (method === "tasks/sendSubscribe") {
        plan = await buildSendSubscribeStream(reqId, params, deps);
      } else {
        plan = buildResubscribeStream(reqId, params, deps.taskStore);
      }
    } catch (err) {
      // Unexpected dispatcher error — surface as a JSON-RPC parse
      // error (HTTP 400) so the client can distinguish it from an SSE
      // mid-stream failure.
      res.status(400).type("application/json").send(
        JSON.stringify({
          jsonrpc: "2.0",
          error: {
            code: JSONRPC_PARSE_ERROR,
            message: `Dispatcher error: ${(err as Error)?.message ?? String(err)}`,
          },
          id: reqId ?? null,
        })
      );
      return;
    }
    await renderSsePlan(req, res, plan, deps.taskStore);
  };
}

/**
 * Materialise an SSE stream-plan as an Express response. Exposed for
 * advanced wiring / tests; the public mount API calls this via the
 * middleware above.
 */
export async function renderSsePlan(
  req: Request,
  res: Response,
  plan: SseStreamPlan,
  taskStore: A2ATaskStore
): Promise<void> {
  switch (plan.kind) {
    case "error": {
      res
        .status(plan.httpStatus)
        .type("application/json")
        .send(JSON.stringify(plan.errorBody));
      return;
    }
    case "single-frame": {
      writeSseHeaders(res);
      writeDataFrame(res, plan.frame);
      endSse(res);
      return;
    }
    case "sync-completed": {
      writeSseHeaders(res);
      writeDataFrame(res, plan.artifactFrame);
      writeDataFrame(res, plan.terminalFrame);
      endSse(res);
      return;
    }
    case "long-running": {
      writeSseHeaders(res);
      await runLongRunningStream(
        req,
        res,
        plan.reqId,
        plan.taskId,
        plan.proxy,
        taskStore
      );
      endSse(res);
      return;
    }
    default: {
      const exhaustive: never = plan;
      throw new Error(`Unknown SSE plan kind: ${JSON.stringify(exhaustive)}`);
    }
  }
}

/**
 * Run the long-running poll loop (spec §5.3 long-running case):
 *
 *  1. Emit an initial `state=working, final=false` frame so the client
 *     confirms subscription liveness.
 *  2. Poll `proxy.status()` every {@link POLL_INTERVAL_MILLIS} ms.
 *  3. Emit a `state=working` frame only when `progress` or
 *     `progress_message` changed — suppresses redundant updates
 *     (Python `a2a.py:1057-1070`, Java's equivalent).
 *  4. Emit a `: keepalive\n\n` SSE comment after {@link KEEPALIVE_MILLIS}
 *     of inactivity.
 *  5. On terminal mesh state: attempt `proxy.wait(1.0)` for the completed
 *     branch, emit the artifact frame, then the terminal status frame
 *     (`final=true`), mark the task store record terminal, return.
 */
async function runLongRunningStream(
  req: Request,
  res: Response,
  reqId: unknown,
  taskId: string,
  proxy: JobProxy,
  taskStore: A2ATaskStore
): Promise<void> {
  const started = Date.now();
  let disconnected = false;
  const onClose = (): void => {
    disconnected = true;
  };
  req.on("close", onClose);
  res.on("close", onClose);

  try {
    // 1. Initial state=working frame.
    if (!writeDataFrame(res, buildStatusUpdateFrame(
      reqId, taskId, A2A_WORKING, null, false, null
    ))) {
      return;
    }

    let lastProgress: unknown = undefined;
    let lastMessage: unknown = undefined;
    let lastEventTime = Date.now();
    let consecutiveStatusFailures = 0;

    // eslint-disable-next-line no-constant-condition
    while (true) {
      if (disconnected || res.writableEnded || res.destroyed) {
        return;
      }

      // Stream-level cap — preserves task state in the store so callers
      // can resume via tasks/resubscribe or check status via tasks/get.
      // The cap protects the worker from a stuck job; it is NOT a
      // job-death signal, so we emit a non-terminal status frame and
      // do NOT mark the task terminal (spec §4.4: producer-side resource
      // limits must not poison the task store).
      if (Date.now() - started > MAX_STREAM_MILLIS) {
        writeDataFrame(res, buildStatusUpdateFrame(
          reqId, taskId, A2A_WORKING,
          "stream closed: producer-side cap exceeded " +
            "(task still running; reconnect via tasks/resubscribe)",
          // final=false: the task is NOT terminal; we are only closing
          // the SSE transport. `final=true` would signal task death to
          // A2A clients.
          false,
          null
        ));
        return;
      }

      let status: Record<string, unknown>;
      try {
        const raw = (await proxy.status()) as unknown;
        status = (raw && typeof raw === "object" && !Array.isArray(raw))
          ? (raw as Record<string, unknown>)
          : {};
        consecutiveStatusFailures = 0;
      } catch (err) {
        consecutiveStatusFailures++;
        // Spec §4.4 conformance: transient unreachability is NOT
        // authoritative evidence the job is dead. Emit state=working
        // carrying the error in status.message and CONTINUE polling.
        // Do NOT mark the task store terminal.
        if (!writeDataFrame(res, buildStatusUpdateFrame(
          reqId, taskId, A2A_WORKING,
          `status unavailable: ${errorTextOf(err)}`,
          false,
          null
        ))) {
          return;
        }
        // Transient-failure frame counts as activity — refresh
        // `lastEventTime` so the keepalive branch doesn't fire a
        // redundant `: keepalive\n\n` right after a data frame.
        lastEventTime = Date.now();
        if (consecutiveStatusFailures >= MAX_CONSECUTIVE_STATUS_FAILURES) {
          // Cap hit — close the stream WITHOUT marking terminal so the
          // client can retry via tasks/get / tasks/resubscribe.
          return;
        }
        if (!(await sleepIfConnected(POLL_INTERVAL_MILLIS, req, res))) {
          return;
        }
        continue;
      }

      const meshState = meshStatusOf(status);

      if (isMeshTerminal(meshState)) {
        const a2aState = fromMesh(meshState);
        let finalResult: unknown = null;
        let hasFinalResult = false;

        if (a2aState === A2A_COMPLETED) {
          try {
            finalResult = await proxy.wait(1.0);
            hasFinalResult = true;
            // Emit artifact frame BEFORE the terminal status — spec
            // §5.3 ordering.
            if (!writeDataFrame(res, buildArtifactUpdateFrame(
              reqId, taskId, finalResult
            ))) {
              return;
            }
          } catch {
            // Best-effort: if wait() throws we skip the artifact and
            // emit only the terminal status frame.
          }
        }

        let finalMessage: string | null = null;
        if (a2aState === A2A_FAILED) {
          const err = status["error"];
          finalMessage = (err !== null && err !== undefined && String(err).length > 0)
            ? String(err)
            : null;
          if (!finalMessage) {
            const pm = status["progress_message"];
            finalMessage = (pm !== null && pm !== undefined && String(pm).length > 0)
              ? String(pm)
              : null;
          }
        } else if (a2aState === A2A_CANCELED) {
          const pm = status["progress_message"];
          finalMessage = (pm !== null && pm !== undefined && String(pm).length > 0)
            ? String(pm)
            : null;
        }

        writeDataFrame(res, buildStatusUpdateFrame(
          reqId, taskId, a2aState, finalMessage, true, null
        ));

        // Cache the terminal envelope so subsequent tasks/get returns
        // the same view as this stream's terminal frame.
        const terminalEnvelope = buildTaskFromStatus(
          taskId, taskId, undefined, a2aState, status, finalResult, hasFinalResult
        );
        taskStore.markTerminal(taskId, terminalEnvelope);
        return;
      }

      const progress = status["progress"];
      const progressMessage = status["progress_message"];
      const now = Date.now();

      const progressChanged = !shallowEqual(progress, lastProgress);
      const messageChanged = !shallowEqual(progressMessage, lastMessage);

      if (progressChanged || messageChanged) {
        const msgText = (progressMessage !== null && progressMessage !== undefined)
          ? String(progressMessage)
          : null;
        const progressNum = typeof progress === "number" ? progress : null;
        if (!writeDataFrame(res, buildStatusUpdateFrame(
          reqId, taskId, A2A_WORKING, msgText, false, progressNum
        ))) {
          return;
        }
        lastProgress = progress;
        lastMessage = progressMessage;
        lastEventTime = now;
      } else if (now - lastEventTime > KEEPALIVE_MILLIS) {
        // Spec §5.1: SSE comment line, ignored by parsers but resets
        // proxy idle timers.
        if (!writeKeepalive(res)) {
          return;
        }
        lastEventTime = now;
      }

      if (!(await sleepIfConnected(POLL_INTERVAL_MILLIS, req, res))) {
        return;
      }
    }
  } finally {
    req.removeListener("close", onClose);
    res.removeListener("close", onClose);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Low-level SSE write helpers
// ─────────────────────────────────────────────────────────────────────────

function writeSseHeaders(res: Response): void {
  // Spec §4.6 / §5.1.
  res.status(200);
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  // Defeats nginx response buffering.
  res.setHeader("X-Accel-Buffering", "no");
  // Flush headers so the client confirms subscription liveness before
  // the first frame arrives.
  if (typeof res.flushHeaders === "function") {
    res.flushHeaders();
  }
}

/**
 * Write one JSON-RPC envelope as an SSE `data:` frame. Returns `false`
 * when the response is no longer writable (client disconnected) so
 * callers can exit the loop without calling `JobProxy.cancel()` per spec
 * §7.3.
 */
function writeDataFrame(res: Response, envelope: Record<string, unknown>): boolean {
  if (res.writableEnded || res.destroyed) {
    return false;
  }
  try {
    const json = JSON.stringify(envelope);
    const written = res.write(`data: ${json}\n\n`);
    return written !== false;
  } catch {
    return false;
  }
}

/**
 * Write a raw SSE comment line (`: keepalive\n\n`). Spec §5.1 keepalive
 * contract. Returns `false` on client disconnect.
 */
function writeKeepalive(res: Response): boolean {
  if (res.writableEnded || res.destroyed) {
    return false;
  }
  try {
    const written = res.write(": keepalive\n\n");
    return written !== false;
  } catch {
    return false;
  }
}

function endSse(res: Response): void {
  if (res.writableEnded || res.destroyed) return;
  try {
    res.end();
  } catch {
    // best-effort
  }
}

/**
 * Sleep for `ms` milliseconds, returning `false` if the client
 * disconnected during the wait. Resolves early on `req`/`res` close so
 * the poll loop exits promptly.
 */
function sleepIfConnected(ms: number, req: Request, res: Response): Promise<boolean> {
  return new Promise((resolve) => {
    if (res.writableEnded || res.destroyed) {
      resolve(false);
      return;
    }
    let resolved = false;
    const done = (ok: boolean): void => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timer);
      req.removeListener("close", onClose);
      res.removeListener("close", onClose);
      resolve(ok);
    };
    const onClose = (): void => done(false);
    const timer = setTimeout(() => done(true), ms);
    req.on("close", onClose);
    res.on("close", onClose);
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Misc helpers
// ─────────────────────────────────────────────────────────────────────────

function readParams(params: unknown): Record<string, unknown> {
  if (params === null || params === undefined) return {};
  if (typeof params !== "object" || Array.isArray(params)) return {};
  return params as Record<string, unknown>;
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
 * Cheap equality for primitives + the few non-primitive shapes the
 * status payload can hold (we only ever compare `progress` (number or
 * undefined) and `progress_message` (string or undefined). A full deep
 * equal would be overkill.
 */
function shallowEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  // Treat null == undefined for the change-detect heuristic so
  // toggling between absent and null doesn't spam frames.
  if (a == null && b == null) return true;
  return false;
}
