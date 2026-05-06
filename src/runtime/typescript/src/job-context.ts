/**
 * AsyncLocalStorage mirror of the Rust core's `JobContext` (Phase 1 —
 * MeshJob substrate).
 *
 * The Rust core (`mcp_mesh_core::job_context`) holds the source of truth
 * for the active job context — set via `with_job` / `run_as_job` from
 * the inbound HTTP tool wrapper or the claim worker. The Rust outbound
 * paths read it via `injectJobHeaders` to attach
 * `X-Mesh-Job-Id` / `X-Mesh-Timeout` headers to downstream calls.
 *
 * JS user code can also need to read the active job context (e.g. to
 * log the current job id or branch on whether a tool is running under a
 * job). Crossing the FFI boundary on every read is wasteful, AND the
 * Rust task-local does not propagate into the Node event loop across
 * the FFI boundary — so this module exposes an `AsyncLocalStorage`
 * mirror that the inbound wrapper (next dispatch) sets alongside the
 * Rust call.
 *
 * For the current dispatch only the JS surface is defined; the inbound
 * wrapper that populates it lands in the next dispatch. Until then
 * `currentJob()` returns `null` (no active job) — which is the correct
 * answer for any tool invoked via a regular `tools/call` rather than a
 * job-dispatch path.
 *
 * See `MESHJOB_DESIGN.org` → "Timeout & Cancellation" → "Async-local
 * primitives" for the cross-runtime parity (Python `contextvars` ≡
 * TypeScript `AsyncLocalStorage` ≡ Java `ThreadLocal`).
 */

import { AsyncLocalStorage } from "node:async_hooks";

/**
 * Read-only snapshot of the active job context for the current async
 * scope. Mirrors the fields of the Rust core's `JobContext` that JS
 * user code can usefully observe. The cancel token itself stays in the
 * Rust core — JS observes its effects via FFI (e.g. an awaited Rust
 * future rejecting with "cancelled") rather than polling it directly.
 */
export interface JobContextSnapshot {
  /** Server-assigned job UUID this scope is executing for. */
  jobId: string;
  /**
   * Seconds left until the per-attempt deadline expires, or `null` if
   * no deadline is set (unlimited per design-doc default).
   *
   * NB: this snapshot value is captured at the time `withJobAsync`
   * binds the context. It does NOT auto-decrement as wall-clock time
   * passes. For an always-fresh remaining-seconds value, query the
   * Rust core via `currentJob()` from `@mcpmesh/core` instead.
   */
  deadlineSecsRemaining: number | null;
}

/**
 * Active `JobContextSnapshot` on the current async scope, or `null`.
 *
 * The inbound HTTP tool wrapper (next dispatch) sets this alongside
 * the Rust core's `withJobAsync` so JS user code can read either side
 * without crossing FFI. When neither side is active, the value is
 * `null`.
 *
 * Exported so the dispatch wrapper (and tests) can call `.run()` /
 * `.exit()` / `.getStore()` directly when finer control than
 * `withJobAsync` is required.
 */
export const CURRENT_JOB = new AsyncLocalStorage<JobContextSnapshot | null>();

/**
 * Return the active job snapshot for the current async scope, or
 * `null`.
 *
 * Safe to call from any context — never throws. Returns `null` outside
 * any active job (e.g. for tools invoked via a regular `tools/call` or
 * in unit tests with no job-dispatch path).
 *
 * Note: The source of truth is the Rust core. This function reads the
 * JS-side mirror for fast in-process access; for cross-FFI parity (and
 * always-fresh `deadlineSecsRemaining`) use `currentJob()` from
 * `@mcpmesh/core`.
 */
export function currentJob(): JobContextSnapshot | null {
  return CURRENT_JOB.getStore() ?? null;
}

/**
 * Seconds remaining on the active job's deadline, or `null`.
 *
 * Returns `null` if no job is active, or if the active job has no
 * deadline set (unlimited). Returns `0` once the deadline has passed —
 * caller should treat that as "no time left" and abort outbound work.
 *
 * Snapshot semantics (see {@link JobContextSnapshot.deadlineSecsRemaining}):
 * this returns the value captured when the scope was bound, not a
 * live wall-clock countdown.
 */
export function remainingSeconds(): number | null {
  const snap = CURRENT_JOB.getStore();
  if (!snap) return null;
  return snap.deadlineSecsRemaining;
}

/**
 * Run `fn` inside an `AsyncLocalStorage` scope with `snap` as the
 * active job context.
 *
 * This is the JS-side analogue of the Rust `with_job` task-local
 * binding. The inbound dispatch wrapper (next dispatch) calls BOTH
 * this AND the Rust `withJobAsync` so:
 *
 *   - JS user code reading via `currentJob()` sees the snapshot;
 *   - Rust-originated work (e.g. `call_tool`, `submit_job`) within
 *     the scope sees the Rust task-local for header injection and
 *     cancel-registry binding.
 *
 * The two contexts are deliberately set in parallel because the Rust
 * task-local does not cross the FFI boundary into the Node event loop.
 */
export async function withJobAsync<T>(
  snap: JobContextSnapshot,
  fn: () => Promise<T>
): Promise<T> {
  return CURRENT_JOB.run(snap, fn);
}
