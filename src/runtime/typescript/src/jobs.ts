/**
 * Public `mesh.jobs` namespace — convenience helpers for the MeshJob
 * event-injection primitive (Phase 1, MeshJob substrate; event-channel
 * extension landed in v2.2).
 *
 * The primary surfaces are:
 *
 *   - {@link postEvent} — fire-and-forget helper to push an event into a
 *     running job by id, without holding a `JobProxy` reference. Intended
 *     for MCP tool bodies that receive a `jobId` in their request payload
 *     (e.g. a "submit_user_input" tool exposed by an orchestrator agent).
 *
 *   - {@link JobNotFoundError} / {@link JobTerminalError} — typed `Error`
 *     subclasses translated from the Rust core's `JobError` variants. The
 *     napi binding surfaces all `JobError` variants as a plain `Error`
 *     today (see `src/runtime/core/src/jobs_napi.rs::job_error_to_napi`),
 *     so we re-classify on the TypeScript side via stable
 *     error-message substrings ("job is terminal" / "job not found").
 *
 * The `JobController` / `JobProxy` napi-rs classes from `@mcpmesh/core`
 * already expose `recvEvent` / `sendEvent` methods directly — application
 * code calls them via the `MeshJob`-typed parameter the framework
 * injects. This module just adds the helper + error classes around that
 * surface, mirroring Python's `mesh.jobs.post_event` API one-for-one.
 */

import { JobProxy } from "@mcpmesh/core";

/**
 * Event posted into a running job's event log. Matches the OpenAPI
 * `JobEvent` schema field-for-field (and the Rust `JobEvent` /
 * Python `job_event_to_pydict` shape). Returned by `JobController.recvEvent`.
 */
export interface JobEvent {
  /** Server-assigned job UUID this event belongs to. */
  job_id: string;
  /** Per-job monotonic sequence number assigned by the registry. */
  seq: number;
  /** User-supplied event type tag (e.g. "signal", "user_input"). */
  type: string;
  /** Arbitrary JSON-shaped payload carried with the event (or `null`). */
  payload: unknown;
  /** W3C trace context propagated by the poster (or `null`). */
  trace_context: unknown;
  /** Identifier of the agent that posted the event (or `null`). */
  posted_by: string | null;
  /** Unix epoch seconds at which the registry created the row. */
  created_at: number;
}

/**
 * Receipt returned by `JobProxy.sendEvent` / `postEvent`. Matches the
 * OpenAPI `JobEventPostResponse` schema field-for-field.
 */
export interface JobEventReceipt {
  /** Server-assigned job UUID the event was posted into. */
  job_id: string;
  /** Per-job monotonic sequence number assigned by the registry. */
  seq: number;
  /** Unix epoch seconds at which the registry created the row. */
  created_at: number;
}

/**
 * Latest job-row snapshot returned by `JobProxy.status` / {@link status}.
 *
 * Matches the registry's OpenAPI `Job` schema field-for-field — the same
 * shape `job_to_json` in `src/runtime/core/src/jobs_napi.rs` produces.
 * Every key is ALWAYS present on the wire: required fields are typed
 * `T`, and Rust `Option<T>` fields are emitted as `T | null` (never
 * absent / `undefined`). The Rust `serde_json::json!` macro the binding
 * uses serialises `None` → `null` for every field unconditionally, so
 * downstream callers can rely on key-presence and only need to null-check
 * the nullable fields.
 */
export interface JobStatus {
  /** Server-assigned job UUID. */
  id: string;
  /** Capability the job was submitted against. */
  capability: string;
  /** Instance id of the replica currently holding the lease (if any). */
  owner_instance_id: string | null;
  /** Lifecycle status. */
  status: "working" | "input_required" | "completed" | "failed" | "cancelled";
  /** Latest progress fraction in `[0.0, 1.0]`. */
  progress: number | null;
  /** Latest progress message string. */
  progress_message: string | null;
  /** Terminal result payload (set when `status === "completed"`). */
  result: unknown;
  /** Terminal error reason (set when `status === "failed"` / `"cancelled"`). */
  error: string | null;
  /** Original request payload the job was submitted with. */
  submitted_payload: unknown;
  /** Number of attempts so far (1-indexed). */
  attempt_count: number;
  /** Maximum retries beyond the initial attempt. */
  max_retries: number;
  /** Per-attempt soft timeout in seconds. */
  max_duration: number | null;
  /** Hard ceiling across all attempts, as a unix epoch second. */
  total_deadline: number | null;
  /** Unix epoch second when the current lease expires. */
  lease_expires_at: number | null;
  /** Unix epoch second of the last heartbeat from the owner replica. */
  last_heartbeat_at: number | null;
  /** Unix epoch second the job row was created. */
  submitted_at: number;
  /** Identifier of the agent that submitted the job. */
  submitted_by: string;
}

// ---------------------------------------------------------------------------
// Typed error classes
// ---------------------------------------------------------------------------
//
// The Rust core's `JobError::Other(BackendError::NotFound)` and
// `JobError::JobTerminal` variants currently surface as plain `Error` from
// the napi layer (see `src/runtime/core/src/jobs_napi.rs::job_error_to_napi`).
// Until the napi binding switches to a custom exception type, we
// re-classify on the TypeScript side via stable substrings emitted by the
// NAPI wrapper's explicit error remap in
// `src/runtime/core/src/jobs_napi.rs` (`job_error_to_napi` at lines
// 85-102, specifically the `JobTerminal` arm at 97-99). The wrapper
// deliberately remaps `JobError::Display` to a stable SDK-facing format
// — do NOT collapse this remap thinking it just passes core's Display
// through; the substring contract here depends on it. Both classes
// derive from `Error` so existing `catch (Error)` handlers continue to
// catch them.

/**
 * The targeted job does not exist (or has been swept) in the registry.
 *
 * Translated from the Rust `JobError::Other(BackendError::NotFound)`
 * path (`GET/POST /jobs/{id}/events` → HTTP 404).
 */
export class JobNotFoundError extends Error {
  readonly name = "JobNotFoundError";
  constructor(message: string) {
    super(message);
  }
}

/**
 * The targeted job is in a terminal state (completed / failed /
 * cancelled) and no longer accepts events.
 *
 * Translated from the Rust `JobError::JobTerminal` variant — the
 * registry returns HTTP 409 once the job row is terminal and the Rust
 * layer maps that to `JobTerminal`.
 */
export class JobTerminalError extends Error {
  readonly name = "JobTerminalError";
  constructor(message: string) {
    super(message);
  }
}

/**
 * Re-classify a generic `Error` raised by the napi layer into one of the
 * typed subclasses, if the message matches. Returns the original error
 * (or a typed clone) — callers should `throw` the returned value.
 *
 * Exported so tests can exercise the substring contract without a real
 * napi failure path.
 */
export function translateJobError(err: unknown): unknown {
  if (
    !(err instanceof Error) ||
    err instanceof JobNotFoundError ||
    err instanceof JobTerminalError
  ) {
    return err;
  }
  const msg = err.message ?? "";
  const msgLower = msg.toLowerCase();
  // Order matters: "job is terminal" is the JobTerminal variant's Display
  // prefix (see jobs_napi.rs::job_error_to_napi); "job not found" is
  // BackendError::NotFound's Display prefix.
  if (msgLower.includes("job is terminal")) {
    const typed = new JobTerminalError(msg);
    (typed as Error & { cause?: unknown }).cause = err;
    return typed;
  }
  if (msgLower.includes("job not found")) {
    const typed = new JobNotFoundError(msg);
    (typed as Error & { cause?: unknown }).cause = err;
    return typed;
  }
  return err;
}

// ---------------------------------------------------------------------------
// JobProxy cache (mirror of Python's `_get_or_create_proxy`)
// ---------------------------------------------------------------------------
//
// `postEvent` used to construct a fresh `JobProxy` on every call. Each
// proxy wraps a Rust `reqwest::Client` with its own connection pool, so a
// steady-state sender that fires off `postEvent` in a hot loop would
// force a fresh TCP/TLS handshake against the registry on every call.
// Cache by `(registryUrl, jobId)` for the process lifetime; the cache
// key is invalidated naturally when a different registry URL or job id is
// used.
//
// Bounded LRU eviction: long-lived senders that post events to many
// distinct jobs (e.g. a router fanning out across thousands of jobs) would
// otherwise grow the cache without bound. `Map` preserves insertion
// order; deleting + re-inserting on hit and shifting off the first key on
// overflow gives us O(1) LRU semantics. The Rust `JobProxy` does not
// expose an explicit `close()` over napi — eviction just drops the Map
// entry and lets JS GC release the wrapped `reqwest::Client` connection
// pool when no JS references remain.

const _PROXY_CACHE_DEFAULT_MAX = 256;

function proxyCacheMax(): number {
  const raw = process.env.MCP_MESH_JOBPROXY_CACHE_MAX;
  if (!raw) return _PROXY_CACHE_DEFAULT_MAX;
  const value = parseInt(raw, 10);
  if (!Number.isFinite(value) || value <= 0) return _PROXY_CACHE_DEFAULT_MAX;
  return value;
}

const _proxyCache = new Map<string, JobProxy>();

/**
 * Return a process-cached `JobProxy` for the given
 * `(registryUrl, jobId)` pair, constructing one on first miss.
 *
 * Cache is a bounded LRU: hits bump the entry to the most-recent end of
 * the insertion-order map, misses on a full cache evict the
 * least-recent entry before inserting. Exported only for tests; not
 * part of the public API.
 */
export function _getOrCreateProxy(registryUrl: string, jobId: string): JobProxy {
  const key = `${registryUrl} ${jobId}`;
  const existing = _proxyCache.get(key);
  if (existing !== undefined) {
    // Bump to most-recent end of insertion order: delete + re-set.
    _proxyCache.delete(key);
    _proxyCache.set(key, existing);
    return existing;
  }
  const proxy = new JobProxy(jobId, registryUrl);
  const maxSize = proxyCacheMax();
  while (_proxyCache.size >= maxSize) {
    // Evict LRU = first entry in insertion order. The Map iterator yields
    // keys in insertion order; pull the oldest and delete it. Dropping
    // the entry releases our reference to the JobProxy; JS GC reclaims
    // the wrapped reqwest client (and its connection pool) when no other
    // refs exist.
    const oldest = _proxyCache.keys().next().value as string | undefined;
    if (oldest === undefined) break;
    _proxyCache.delete(oldest);
  }
  _proxyCache.set(key, proxy);
  return proxy;
}

/**
 * Clear the JobProxy cache. Exposed for tests — not part of the public
 * API. Equivalent to dropping all entries; the underlying napi handles
 * are released when JS GC runs.
 */
export function _clearProxyCache(): void {
  _proxyCache.clear();
}

// ---------------------------------------------------------------------------
// postEvent convenience helper
// ---------------------------------------------------------------------------

/**
 * Discover the registry base URL the running agent is bound to.
 *
 * Mirrors Python's `mesh.jobs._resolve_registry_url`: the canonical
 * source is the `MCP_MESH_REGISTRY_URL` environment variable. The
 * configuration pipeline writes this on agent startup and every
 * job-substrate code path reads it.
 *
 * @throws Error if the variable isn't set — the caller can't post an
 *   event without knowing which registry to target.
 */
function resolveRegistryUrl(): string {
  const url = process.env.MCP_MESH_REGISTRY_URL;
  if (!url) {
    throw new Error(
      "mesh.jobs: MCP_MESH_REGISTRY_URL is not set; " +
        "cannot resolve registry base URL. Ensure the calling " +
        "process is running inside a mesh agent.",
    );
  }
  return url;
}

/**
 * Post an event to a running job by ID.
 *
 * Convenience helper for tool bodies that hold a `jobId` (e.g. from a
 * request body, a token lookup, or a stashed reference) but do NOT
 * have a `JobProxy` reference in scope. Constructs (or reuses, via the
 * LRU cache) a `JobProxy` bound to the current agent's registry URL
 * and forwards the call.
 *
 * Mirrors Python's `mesh.jobs.post_event` API one-for-one.
 *
 * @param jobId - Target job's server-assigned id.
 * @param eventType - Event type tag (e.g. `"extend_deadline"`,
 *   `"user_input"`, or any user-defined string). The running handler
 *   can filter via `await job.recvEvent(["..."])`.
 * @param payload - Optional JSON-serializable payload carried with the
 *   event. `undefined`/`null` is normalized to an empty object before
 *   forwarding — the Rust layer accepts either.
 * @returns Receipt `{ job_id, seq, created_at }`. `seq` is the
 *   server-assigned sequence number useful for stitching follow-up
 *   `recvEvent` calls.
 *
 * @throws {@link JobNotFoundError} If the registry doesn't know the
 *   job (sweep already removed it, or wrong id).
 * @throws {@link JobTerminalError} If the job has already reached a
 *   terminal state — no more events accepted.
 * @throws Error For transport errors (registry unreachable, 5xx after
 *   retries, malformed payload, etc.) — the underlying error message
 *   is preserved.
 *
 * @example
 * Inside an MCP tool body that holds a job id:
 * ```ts
 * agent.addTool({
 *   name: "submit_user_input",
 *   capability: "submit_user_input",
 *   parameters: z.object({ jobId: z.string(), text: z.string() }),
 *   execute: async ({ jobId, text }) => {
 *     const receipt = await mesh.jobs.postEvent(
 *       jobId,
 *       "user_input",
 *       { text },
 *     );
 *     return { posted_seq: receipt.seq };
 *   },
 * });
 * ```
 */
export async function postEvent(
  jobId: string,
  eventType: string,
  payload?: unknown,
): Promise<JobEventReceipt> {
  const registryUrl = resolveRegistryUrl();
  const proxy = _getOrCreateProxy(registryUrl, jobId);
  const safePayload = payload !== undefined && payload !== null ? payload : {};
  try {
    const receipt = (await proxy.sendEvent(eventType, safePayload)) as JobEventReceipt;
    return receipt;
  } catch (err) {
    const translated = translateJobError(err);
    if (translated !== err) {
      throw translated;
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// subscribeEvents convenience helper (observer-side async iterator)
// ---------------------------------------------------------------------------

/**
 * Options for {@link subscribeEvents}. All fields are optional —
 * defaults match Python's `mesh.jobs.subscribe_events` keyword args.
 */
export interface SubscribeEventsOptions {
  /**
   * Optional event-type filter applied server-side. Only events whose
   * `type` matches one of these is yielded. Omit for all types.
   */
  types?: string[];
  /**
   * Initial cursor (default `0` ≡ from the beginning of the event log).
   * Pass a higher value to skip historical events. Accepts both
   * `number` and `bigint` for callers stitching from an `i64`-sourced
   * cursor.
   */
  after?: number | bigint;
  /**
   * Long-poll wait budget per registry call (in seconds). Default `30`.
   * Capped at `60` by the registry. Pass `null` to skip the long-poll
   * entirely (single immediate read; rarely needed — tight-poll callers
   * should pass `0` instead).
   */
  longPollSecs?: number | null;
}

/**
 * Subscribe to events posted to a running job by ID.
 *
 * Long-lived async iterator. Each call manages its own cursor —
 * multiple subscribers can observe the same job's events independently
 * without affecting the producer's `recvEvent` consumption (the
 * producer's cursor is per-controller; this observer's cursor is
 * per-call).
 *
 * The iterator runs indefinitely until the caller breaks out of the
 * `for await` loop or the underlying registry returns
 * {@link JobNotFoundError}. There is no automatic terminal-state
 * detection — use a synthetic event type (e.g. `{ type: "ended" }`)
 * posted by your application to signal iteration end.
 *
 * Mirrors Python's `mesh.jobs.subscribe_events` one-for-one.
 *
 * @param jobId - Target job's server-assigned id.
 * @param options - Optional filter / cursor / long-poll knobs.
 * @yields Event objects: `{ seq, type, payload, trace_context,
 *   posted_by, created_at, job_id }`.
 *
 * @throws {@link JobNotFoundError} If the job has been reaped from the
 *   registry (404 on the `GET /jobs/{id}/events` endpoint).
 * @throws Error For transport errors (registry unreachable, 5xx after
 *   retries, malformed payload, etc.) — the underlying error message
 *   is preserved.
 *
 * @example
 * Mirror events from a running job into a downstream system:
 * ```ts
 * for await (const event of mesh.jobs.subscribeEvents(jobId, {
 *   types: ["progress", "result"],
 * })) {
 *   await downstream.publish(event);
 *   if (event.type === "result") break; // caller-defined termination
 * }
 * ```
 */
export async function* subscribeEvents(
  jobId: string,
  options: SubscribeEventsOptions = {},
): AsyncGenerator<JobEvent, void, unknown> {
  const { types, after = 0, longPollSecs = 30 } = options;
  const registryUrl = resolveRegistryUrl();
  const proxy = _getOrCreateProxy(registryUrl, jobId);
  // Cursor as `number` because the napi binding types `after` as
  // `number` (i64 → JS Number). Accept `bigint` in the input options
  // for callers stitching from another i64 source, but coerce down to
  // `number` for the binding boundary — guarding the overflow case so
  // an out-of-range i64 cursor surfaces as an explicit RangeError
  // rather than silently truncating.
  let cursor: number;
  if (typeof after === "bigint") {
    if (after > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new RangeError(
        `subscribeEvents: 'after' cursor exceeds Number.MAX_SAFE_INTEGER (${Number.MAX_SAFE_INTEGER}); per-job seq overflowed JS Number range. Got: ${after}`,
      );
    }
    cursor = Number(after);
  } else {
    cursor = after ?? 0;
  }
  // The binding type signature is `number | null | undefined`; the
  // Python sibling accepts `None` for "single immediate read", and we
  // forward that through verbatim.
  const wait: number | null | undefined = longPollSecs;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let result: { events: JobEvent[]; nextAfter: number };
    try {
      result = (await proxy.listEvents(cursor, types, wait)) as {
        events: JobEvent[];
        nextAfter: number;
      };
    } catch (err) {
      const translated = translateJobError(err);
      if (translated !== err) {
        throw translated;
      }
      throw err;
    }
    const { events, nextAfter } = result;
    for (const event of events) {
      const seq = event.seq as unknown;
      // Reject booleans explicitly: `typeof true === "boolean"` but
      // JS often widens bool↔number; the registry contract is integer
      // seqs, so a bool here is a wire-level malformed payload.
      if (typeof seq === "boolean") {
        throw new Error(
          `subscribeEvents: registry returned event with boolean 'seq': ${JSON.stringify(event)}`,
        );
      }
      if (typeof seq !== "number" && typeof seq !== "bigint") {
        throw new Error(
          `subscribeEvents: registry returned event without integer 'seq': ${JSON.stringify(event)}`,
        );
      }
      const seqNum = typeof seq === "bigint" ? Number(seq) : seq;
      if (seqNum > cursor) cursor = seqNum;
      // listEvents returns ascending-seq; cursor advance before yield
      // ensures correctness across consumer cancellation.
      yield event;
    }
    // Empty pages (or pages filtered by `types` server-side) still
    // advance the cursor via the registry-supplied watermark, so
    // subsequent polls don't re-scan the same filtered range.
    if (nextAfter > cursor) cursor = nextAfter;
  }
}

// ---------------------------------------------------------------------------
// cancel / status / wait — DDDI-clean lifecycle facades (issue #1078)
// ---------------------------------------------------------------------------
//
// Mirror the `postEvent` / `subscribeEvents` pattern: take a `jobId` as
// the first positional arg, resolve the registry URL internally via
// `resolveRegistryUrl()`, dispatch through a cached `JobProxy` from
// `_getOrCreateProxy()`, and re-classify the napi layer's generic
// `Error` output via `translateJobError`.
//
// These exist so callers that hold only a `jobId` (e.g. an Express
// route handler, a tool body whose request payload carries a stashed
// id) can operate on the job's lifecycle without constructing a
// `JobProxy` directly — which would leak `MCP_MESH_REGISTRY_URL`
// addressing into user code and break the DDDI contract.

/**
 * Cancel a running job by ID.
 *
 * Convenience helper for callers that hold a `jobId` but do not have a
 * `JobProxy` reference in scope. Constructs (or reuses, via the LRU
 * cache) a transient proxy bound to the current agent's registry URL
 * and forwards the call.
 *
 * Per the registry's idempotency contract, calling `cancel` on a job
 * that is already in a terminal state returns successfully without
 * re-firing cancellation. If the registry surfaces a conflict for
 * some other reason, the facade re-classifies it as
 * {@link JobTerminalError}. The registry forwards the cancel signal to
 * the owner replica via `POST /jobs/{id}/cancel`; the running handler's
 * cancel token fires on the next `await` point, and any outbound
 * `McpMeshTool` proxy calls abort their underlying `fetch`.
 *
 * Mirrors Python's `mesh.jobs.cancel` one-for-one.
 *
 * @param jobId - Target job's server-assigned id.
 * @param reason - Optional human-readable reason recorded against the
 *   cancellation. Surfaces in the synthetic
 *   `{ type: "cancelled" }` event the registry writes into the job's
 *   event log, so a handler parked on `recvEvent(["cancelled"])` can
 *   return cleanly with the reason in scope.
 *
 * @throws {@link JobNotFoundError} If the registry doesn't know the
 *   job (sweep already removed it, or wrong id).
 * @throws {@link JobTerminalError} If the registry surfaces a conflict
 *   for this cancel (e.g. the idempotency contract changes upstream or
 *   the registry treats the targeted terminal state as a conflict).
 * @throws Error For transport errors (registry unreachable, 5xx after
 *   retries, malformed payload, etc.) — the underlying error message
 *   is preserved.
 *
 * @example
 * Cancel a job from a tool that receives the id in its payload:
 * ```ts
 * agent.addTool({
 *   name: "abort_workflow",
 *   capability: "abort_workflow",
 *   parameters: z.object({ jobId: z.string(), reason: z.string() }),
 *   execute: async ({ jobId, reason }) => {
 *     await mesh.jobs.cancel(jobId, reason);
 *     return { cancelled: jobId };
 *   },
 * });
 * ```
 */
export async function cancel(jobId: string, reason?: string): Promise<void> {
  const registryUrl = resolveRegistryUrl();
  const proxy = _getOrCreateProxy(registryUrl, jobId);
  try {
    await proxy.cancel(reason ?? null);
  } catch (err) {
    const translated = translateJobError(err);
    if (translated !== err) {
      throw translated;
    }
    throw err;
  }
}

/**
 * Get the current status of a job by ID.
 *
 * Convenience helper for callers that hold a `jobId` but do not have a
 * `JobProxy` reference in scope. Constructs (or reuses, via the LRU
 * cache) a transient proxy bound to the current agent's registry URL
 * and forwards a single `GET /jobs/{id}` to the registry.
 *
 * Mirrors Python's `mesh.jobs.status` one-for-one.
 *
 * @param jobId - Target job's server-assigned id.
 * @returns Job status snapshot — the same shape `JobProxy.status()`
 *   returns, mirroring the registry's `Job` schema field-for-field.
 *
 * @throws {@link JobNotFoundError} If the registry doesn't know the
 *   job (sweep already removed it, or wrong id).
 * @throws Error For transport errors (registry unreachable, 5xx after
 *   retries, malformed payload, etc.) — the underlying error message
 *   is preserved.
 *
 * @example
 * Poll a job's progress from outside the producer agent:
 * ```ts
 * agent.addTool({
 *   name: "check_progress",
 *   capability: "check_progress",
 *   parameters: z.object({ jobId: z.string() }),
 *   execute: async ({ jobId }) => {
 *     const snapshot = await mesh.jobs.status(jobId);
 *     return {
 *       status: snapshot.status,
 *       progress: snapshot.progress,
 *       message: snapshot.progress_message,
 *     };
 *   },
 * });
 * ```
 */
export async function status(jobId: string): Promise<JobStatus> {
  const registryUrl = resolveRegistryUrl();
  const proxy = _getOrCreateProxy(registryUrl, jobId);
  try {
    return (await proxy.status()) as JobStatus;
  } catch (err) {
    const translated = translateJobError(err);
    if (translated !== err) {
      throw translated;
    }
    throw err;
  }
}

/**
 * Wait for a job to complete and return its result.
 *
 * Convenience helper for callers that hold a `jobId` but do not have a
 * `JobProxy` reference in scope. Constructs (or reuses, via the LRU
 * cache) a transient proxy bound to the current agent's registry URL
 * and polls until the job reaches a terminal state.
 *
 * On success, returns the `result` payload the handler passed to
 * `JobController.complete` — any JSON-shaped value (object / array /
 * primitive). On a non-success terminal (`failed` / `cancelled`) the
 * underlying napi layer rejects with a generic `Error` carrying the
 * Rust `JobError` display string. On `timeoutSecs` expiry the napi
 * layer rejects with an `Error` whose message starts with
 * `"timeout:"` — `translateJobError` does NOT (currently) re-classify
 * this into a typed exception; callers that need to discriminate
 * timeout from other failures should check `err.message.startsWith(
 * "timeout:")`. A typed `TimeoutError` may be added in a future PR
 * if usage warrants it.
 *
 * Mirrors Python's `mesh.jobs.wait` one-for-one.
 *
 * @param jobId - Target job's server-assigned id.
 * @param timeoutSecs - Maximum wait duration in seconds. `undefined` /
 *   `null` ≡ no timeout (default) — wait until the job reaches a
 *   terminal state. Negative / NaN / infinite values are rejected by
 *   the napi layer with a clear `Error` before any registry call.
 * @returns The job's result payload (whatever the handler passed to
 *   `complete()`). Shape is application-defined — typically an object,
 *   but any JSON-shaped value is valid.
 *
 * @throws {@link JobNotFoundError} If the registry doesn't know the
 *   job (sweep already removed it, or wrong id).
 * @throws Error With message prefixed `"timeout:"` if `timeoutSecs`
 *   elapses before the job reaches a terminal state.
 * @throws Error If the job reached a non-success terminal state
 *   (`failed` / `cancelled`) or for transport errors — the underlying
 *   error message is preserved.
 *
 * @example
 * Submit-then-wait from a tool that doesn't hold the proxy:
 * ```ts
 * agent.addTool({
 *   name: "run_to_completion",
 *   capability: "run_to_completion",
 *   parameters: z.object({ jobId: z.string() }),
 *   execute: async ({ jobId }) => {
 *     const result = await mesh.jobs.wait(jobId, 300);
 *     return { result };
 *   },
 * });
 * ```
 */
export async function wait(jobId: string, timeoutSecs?: number): Promise<unknown> {
  const registryUrl = resolveRegistryUrl();
  const proxy = _getOrCreateProxy(registryUrl, jobId);
  try {
    return await proxy.wait(timeoutSecs ?? null);
  } catch (err) {
    const translated = translateJobError(err);
    if (translated !== err) {
      throw translated;
    }
    throw err;
  }
}
