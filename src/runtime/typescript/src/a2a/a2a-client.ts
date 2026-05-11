/**
 * Thin A2A v1.0 client — sync `tasks/send` + non-blocking `submit` +
 * SSE `subscribe` (issue #917).
 *
 * One instance per (url, skillId, auth, timeout) tuple — the framework
 * caches and re-uses clients across tool invocations so the underlying
 * undici connection pool is amortised. Mirrors
 * `mesh._a2a_consumer.A2AClient` (Python) and
 * `io.mcpmesh.a2a.A2AClient` (Java) — same JSON-RPC envelope shape +
 * polling backoff + auth header semantics.
 */
import { randomUUID } from "node:crypto";
import { getDispatcher } from "../http-pool.js";
import {
  A2ABearer,
  type A2ABearerConfig,
  resolveBearer,
} from "./a2a-bearer.js";
import {
  A2AAuthError,
  A2AError,
  A2ATimeoutError,
} from "./errors.js";
import { A2AJob } from "./a2a-job.js";
import { A2AStream } from "./a2a-stream.js";

/** Default per-call deadline for `send`. */
export const DEFAULT_TIMEOUT_MS = 30_000;
/** Initial poll interval for `tasks/get` (ms). */
export const DEFAULT_POLL_INTERVAL_MS = 500;
/** Capped poll interval for `tasks/get` (ms). */
export const DEFAULT_POLL_INTERVAL_MAX_MS = 2_000;
/** Multiplier applied between consecutive polls. */
export const POLL_BACKOFF_FACTOR = 1.5;

const _TERMINAL_STATES = new Set([
  "completed",
  "failed",
  "canceled",
  // A2A v1.0 uses US "canceled"; mesh JobController uses UK "cancelled".
  // Accept both so a heterogeneous deployment doesn't get stuck polling.
  "cancelled",
]);

export function isTerminalState(state: string | undefined | null): boolean {
  return state != null && _TERMINAL_STATES.has(state.toLowerCase());
}

/** A2A v1.0 message dict — `{ role, parts: [...] }` shape. */
export type A2AMessage = Record<string, unknown>;

export interface A2AClientConfig {
  /** A2A endpoint URL. Trailing slashes are stripped. */
  url: string;
  /** Skill ID to invoke on the upstream. */
  skillId: string;
  /** Bearer credential (instance or config). */
  auth?: A2ABearer | A2ABearerConfig;
  /** Per-call deadline for `send` (ms). Default 30_000. */
  timeoutMs?: number;
  /** Initial backoff between `tasks/get` polls (ms). Default 500. */
  pollIntervalMs?: number;
  /** Cap on the backoff between polls (ms). Default 2_000. */
  pollIntervalMaxMs?: number;
}

/** Result of a synchronous `A2AClient.send`. */
export interface A2AResponse {
  /** First artifact's first text part — the canonical sync return. */
  artifactText: string;
  /** Final lifecycle state (typically "completed"). */
  state: string;
  /** Consumer-generated task ID echoed back by the producer. */
  taskId: string;
  /** Full Task envelope (status, artifacts, metadata, history). */
  rawTask: Record<string, unknown>;
}

/** Raw task envelope returned by `A2AJob.status` etc. */
export type A2ATaskEnvelope = Record<string, unknown>;

interface JsonRpcEnvelope {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params: Record<string, unknown>;
}

/** Sentinel that controls whether `_postJsonRpc` asserts a `result` field. */
type JsonRpcAcceptShape = "result-required" | "result-or-error";

export class A2AClient {
  readonly url: string;
  readonly skillId: string;
  readonly auth?: A2ABearer;
  readonly timeoutMs: number;
  readonly pollIntervalMs: number;
  readonly pollIntervalMaxMs: number;
  private closed = false;
  // JSON-RPC requires a unique id per request — a per-instance monotonic
  // counter is the spec-conforming choice. Some servers/middleware
  // enforce this, so don't reuse `2` across every tasks/get poll.
  private nextRpcId = 1;

  constructor(config: A2AClientConfig) {
    if (!config.url || config.url.trim() === "") {
      throw new A2AError("A2AClient: url must be non-empty");
    }
    if (config.timeoutMs !== undefined && config.timeoutMs <= 0) {
      throw new A2AError("A2AClient: timeoutMs must be > 0");
    }
    // Trim trailing slashes to match Python's url.rstrip("/") and Java's
    // trim loop — keeps the on-the-wire URL stable regardless of how
    // the user wrote the constructor argument.
    let trimmed = config.url;
    while (trimmed.endsWith("/")) {
      trimmed = trimmed.slice(0, -1);
    }
    this.url = trimmed;
    this.skillId = config.skillId;
    this.auth = resolveBearer(config.auth);
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.pollIntervalMs = config.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
    this.pollIntervalMaxMs =
      config.pollIntervalMaxMs ?? DEFAULT_POLL_INTERVAL_MAX_MS;
  }

  /**
   * POST `tasks/send` and poll `tasks/get` until terminal.
   *
   * `message` is the A2A v1.0 request message dict — typically
   * `{ role: "user", parts: [{ type: "text", text: "..." }] }`.
   * Returns an `A2AResponse` whose `artifactText` carries the
   * producer-side handler's return value (JSON-stringified for
   * non-string returns; consumers `JSON.parse` when the upstream
   * returns a dict).
   */
  async send(
    message: A2AMessage,
    options?: { taskId?: string; timeoutMs?: number },
  ): Promise<A2AResponse> {
    this._ensureOpen();
    if (message == null) {
      throw new A2AError("A2AClient.send: message must be non-null");
    }
    const timeoutMs = options?.timeoutMs ?? this.timeoutMs;
    if (timeoutMs <= 0) {
      throw new A2AError("A2AClient.send: timeoutMs must be > 0");
    }
    const taskId = options?.taskId ?? this._newTaskId();
    const deadline = Date.now() + timeoutMs;

    let result = await this._postJsonRpc(
      "tasks/send",
      { id: taskId, message },
      Math.max(1, deadline - Date.now()),
    );
    let state = readState(result);
    if (isTerminalState(state)) {
      return this._buildResponse(taskId, result);
    }

    let intervalMs = this.pollIntervalMs;
    while (Date.now() < deadline) {
      await sleep(Math.min(intervalMs, Math.max(1, deadline - Date.now())));
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      result = await this._postJsonRpc(
        "tasks/get",
        { id: taskId },
        remaining,
      );
      state = readState(result);
      if (isTerminalState(state)) {
        return this._buildResponse(taskId, result);
      }
      intervalMs = Math.min(
        this.pollIntervalMaxMs,
        Math.floor(intervalMs * POLL_BACKOFF_FACTOR),
      );
    }

    throw new A2ATimeoutError(
      `A2A task '${taskId}' on ${this.url} did not reach terminal state ` +
        `within ${timeoutMs}ms (last state='${state}')`,
    );
  }

  /**
   * POST `tasks/send` and return an `A2AJob` handle WITHOUT polling.
   *
   * Use this when the surrounding `addTool({ task: true, ... })` body
   * wants explicit control over when to poll — typically via
   * `A2AJob.bridge(jobController)` which mirrors progress into the
   * framework-injected `JobController`.
   */
  async submit(
    message: A2AMessage,
    options?: { taskId?: string },
  ): Promise<A2AJob> {
    this._ensureOpen();
    if (message == null) {
      throw new A2AError("A2AClient.submit: message must be non-null");
    }
    const taskId = options?.taskId ?? this._newTaskId();
    const result = await this._postJsonRpc(
      "tasks/send",
      { id: taskId, message },
      this.timeoutMs,
    );
    const state = readState(result);
    return new A2AJob(this, taskId, state, result);
  }

  /**
   * POST `tasks/sendSubscribe` and return an `A2AStream` of parsed events.
   *
   * The returned stream MUST be either iterated to completion (the
   * terminal `final=true` frame closes it) OR explicitly closed via
   * `await using` / `await stream.aclose()` to release the underlying
   * connection.
   */
  async subscribe(
    message: A2AMessage,
    options?: { taskId?: string },
  ): Promise<A2AStream> {
    this._ensureOpen();
    if (message == null) {
      throw new A2AError("A2AClient.subscribe: message must be non-null");
    }
    const taskId = options?.taskId ?? this._newTaskId();
    const envelope: JsonRpcEnvelope = {
      jsonrpc: "2.0",
      id: this.nextRpcId++,
      method: "tasks/sendSubscribe",
      params: { id: taskId, message },
    };

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (this.auth) {
      headers["Authorization"] = this.auth.authorizationHeader();
    }

    let response: Response;
    try {
      // No request timeout on the SSE call — the stream lifetime is
      // dictated by the producer, not a per-request deadline. The
      // dispatcher's keep-alive still applies to the initial handshake.
      response = await fetch(this.url, {
        method: "POST",
        headers,
        body: JSON.stringify(envelope),
        // undici extension: dispatcher is honoured for connection pooling.
        dispatcher: getDispatcher(this.url),
      });
    } catch (err) {
      throw new A2AError(
        `A2A tasks/sendSubscribe ${this.url} transport failure: ` +
          `${(err as Error)?.message ?? String(err)}`,
        err,
      );
    }
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new A2AError(
        `A2A tasks/sendSubscribe ${this.url} HTTP ${response.status}: ` +
          truncate(body, 256),
      );
    }
    if (!response.body) {
      throw new A2AError(
        `A2A tasks/sendSubscribe ${this.url} returned no response body`,
      );
    }
    return new A2AStream(response, taskId);
  }

  /**
   * Lifecycle marker (forward-compat).
   *
   * The undici Agent pool is shared process-wide via `closeHttpPool()`
   * — there's no per-client connection state to tear down. We mark
   * `closed = true` so subsequent `send`/`submit`/`subscribe` raise
   * cleanly (matches Python's `_closed` flag behaviour).
   */
  async close(): Promise<void> {
    this.closed = true;
  }

  // --- internal API used by A2AJob / A2AStream -----------------------------

  /** Internal: POST `tasks/get` for the supplied task ID. */
  async tasksGet(taskId: string): Promise<A2ATaskEnvelope> {
    this._ensureOpen();
    return this._postJsonRpc("tasks/get", { id: taskId }, this.timeoutMs);
  }

  /** Internal: POST `tasks/cancel`. Best-effort; transport errors swallowed by caller. */
  async tasksCancel(taskId: string, reason?: string): Promise<void> {
    this._ensureOpen();
    const params: Record<string, unknown> = { id: taskId };
    if (reason !== undefined) params.reason = reason;
    // A2A spec-conforming producers may return `{jsonrpc:"2.0",id:N}` for
    // tasks/cancel (no result, no error) — accept that envelope shape so
    // we don't false-fail the cancel on producers that don't echo a Task
    // body back.
    await this._postJsonRpc(
      "tasks/cancel",
      params,
      this.timeoutMs,
      "result-or-error",
    );
  }

  /** Internal: build an `A2AResponse` from a Task envelope. */
  buildResponse(taskId: string, result: A2ATaskEnvelope): A2AResponse {
    return this._buildResponse(taskId, result);
  }

  // --- helpers -------------------------------------------------------------

  private _newTaskId(): string {
    return `c-${randomUUID().replace(/-/g, "")}`;
  }

  private _ensureOpen(): void {
    if (this.closed) {
      throw new A2AError(
        `A2AClient(url=${this.url}) is closed; create a new instance instead.`,
      );
    }
  }

  private async _postJsonRpc(
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
    accept: JsonRpcAcceptShape = "result-required",
  ): Promise<A2ATaskEnvelope> {
    const envelope: JsonRpcEnvelope = {
      jsonrpc: "2.0",
      id: this.nextRpcId++,
      method,
      params,
    };
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (this.auth) {
      try {
        headers["Authorization"] = this.auth.authorizationHeader();
      } catch (err) {
        if (err instanceof A2AAuthError) throw err;
        throw new A2AAuthError(
          `A2A ${method} ${this.url}: failed to resolve bearer header: ` +
            `${(err as Error)?.message ?? String(err)}`,
          err,
        );
      }
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetch(this.url, {
        method: "POST",
        headers,
        body: JSON.stringify(envelope),
        signal: controller.signal,
        // undici extension: dispatcher is honoured for connection pooling.
        dispatcher: getDispatcher(this.url),
      });
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") {
        throw new A2ATimeoutError(
          `A2A ${method} ${this.url} timed out after ${timeoutMs}ms`,
          err,
        );
      }
      throw new A2AError(
        `A2A ${method} ${this.url} transport failure: ` +
          `${(err as Error)?.message ?? String(err)}`,
        err,
      );
    } finally {
      clearTimeout(timer);
    }

    const body = await response.text();
    if (!response.ok) {
      throw new A2AError(
        `A2A ${method} ${this.url} HTTP ${response.status}: ` +
          truncate(body, 256),
      );
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch (err) {
      throw new A2AError(
        `A2A ${method} ${this.url} returned malformed JSON: ` +
          truncate(body, 256),
        err,
      );
    }
    if (parsed == null || typeof parsed !== "object") {
      throw new A2AError(`A2A ${method} ${this.url} returned empty body`);
    }
    const obj = parsed as Record<string, unknown>;
    if (obj.error != null) {
      const err = obj.error as Record<string, unknown>;
      const code = err.code !== undefined ? String(err.code) : "?";
      const msg =
        err.message !== undefined ? String(err.message) : "<no message>";
      throw new A2AError(`A2A error from ${this.url}: ${code} ${msg}`);
    }
    if (obj.result === undefined || obj.result === null) {
      if (accept === "result-or-error") {
        return {} as A2ATaskEnvelope;
      }
      // A producer that returns {"jsonrpc":"2.0","id":1} (no result and
      // no error) is malformed JSON-RPC. Coercing this to an empty
      // object would make `readState()` return "unknown" and the
      // polling loop spin until the user-supplied deadline. Fail fast
      // with a clear message instead — matches Java parity.
      throw new A2AError(
        `A2A ${method} ${this.url} response has neither 'result' nor 'error' ` +
          `field — malformed JSON-RPC envelope: ${truncate(body, 256)}`,
      );
    }
    return obj.result as A2ATaskEnvelope;
  }

  private _buildResponse(
    taskId: string,
    result: A2ATaskEnvelope,
  ): A2AResponse {
    return {
      artifactText: extractArtifactText(result),
      state: readState(result),
      taskId,
      rawTask: result,
    };
  }
}

// --- exported helpers (used by A2AJob + A2AStream) ----------------------------

export function readState(result: A2ATaskEnvelope | undefined | null): string {
  if (!result || typeof result !== "object") return "unknown";
  const status = (result as Record<string, unknown>).status as
    | Record<string, unknown>
    | undefined;
  if (!status || typeof status !== "object") return "unknown";
  const state = status.state;
  if (typeof state !== "string") return "unknown";
  return state;
}

export function extractArtifactText(result: A2ATaskEnvelope): string {
  const artifacts = (result as Record<string, unknown>).artifacts;
  if (!Array.isArray(artifacts) || artifacts.length === 0) return "";
  const first = artifacts[0];
  if (!first || typeof first !== "object") return "";
  const parts = (first as Record<string, unknown>).parts;
  if (!Array.isArray(parts) || parts.length === 0) return "";
  const firstPart = parts[0];
  if (!firstPart || typeof firstPart !== "object") return "";
  const text = (firstPart as Record<string, unknown>).text;
  return typeof text === "string" ? text : "";
}

export function readStatusMessage(result: A2ATaskEnvelope): string | undefined {
  const status = (result as Record<string, unknown>).status as
    | Record<string, unknown>
    | undefined;
  if (!status || typeof status !== "object") return undefined;
  const msg = status.message;
  if (!msg || typeof msg !== "object") return undefined;
  const parts = (msg as Record<string, unknown>).parts;
  if (!Array.isArray(parts) || parts.length === 0) return undefined;
  const firstPart = parts[0];
  if (!firstPart || typeof firstPart !== "object") return undefined;
  const text = (firstPart as Record<string, unknown>).text;
  return typeof text === "string" ? text : undefined;
}

export function readProgress(result: A2ATaskEnvelope): number | undefined {
  const metadata = (result as Record<string, unknown>).metadata as
    | Record<string, unknown>
    | undefined;
  if (!metadata || typeof metadata !== "object") return undefined;
  const progress = metadata.progress;
  if (progress === undefined || progress === null) return undefined;
  if (typeof progress === "number" && Number.isFinite(progress)) {
    return progress;
  }
  // Tolerate stringified numerics — some producers JSON-encode metadata
  // fields as strings.
  if (typeof progress === "string") {
    const n = Number.parseFloat(progress);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

export function maybeJsonParse(text: string): unknown {
  if (!text) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function isCanceledState(state: string | undefined | null): boolean {
  if (!state) return false;
  const s = state.toLowerCase();
  return s === "canceled" || s === "cancelled";
}

function truncate(s: string | undefined | null, max: number): string {
  if (s == null) return "";
  return s.length <= max ? s : s.slice(0, max) + "...";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
