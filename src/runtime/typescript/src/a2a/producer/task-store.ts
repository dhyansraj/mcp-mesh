/**
 * Process-local A2A task store (spec §4.8).
 *
 * Two record shapes coexist:
 * - Terminal: `tasks/send` returned a sync value (or the handler raised).
 *   `terminalEnvelope` + `terminalAt` are populated; `jobProxy` is `null`.
 *   Cached for 300s so subsequent `tasks/get` requests return the same
 *   envelope (spec Appendix B item 5 — match Python / Java exactly for
 *   cross-runtime parity).
 * - Long-running: handler returned a `JobProxy`. `jobProxy` is populated;
 *   `terminalEnvelope` / `terminalAt` are `undefined` until the SSE
 *   stream / `tasks/cancel` / `tasks/get` observes a terminal mesh state
 *   and calls {@link A2ATaskStore.markTerminal}.
 *
 * Eviction is lazy: every read/write sweeps entries whose `terminalAt`
 * timestamp is older than `TERMINAL_EVICTION_MS`. No background sweeper is
 * required (spec §4.8). JavaScript's single-threaded event loop avoids the
 * race windows that Java needs `computeIfPresent` for — but we still
 * defensively re-check `terminalAt === undefined` before flipping a record
 * to terminal so concurrent async handlers can't clobber each other.
 *
 * Non-terminal records are never auto-evicted; long-running paths keep
 * them alive across arbitrary durations.
 *
 * Cross-replica semantics: the store is process-local. A `tasks/get`
 * against a replica that doesn't own the task returns `Unknown task id`
 * per spec Appendix B item 3.
 */
import type { JobProxy } from "@mcpmesh/core";

/**
 * Cached A2A task envelope plus the metadata needed to keep it alive during
 * the 300s idempotency window.
 *
 * Fields:
 * - `sessionId` — the A2A session id (defaults to `taskId` per spec §4.2)
 * - `requestMessage` — the originating request `message` object (echoed
 *   into `result.history[]`); `undefined` when the client omitted it
 * - `terminalEnvelope` — the full Task envelope cached for `tasks/get`
 *   lookups; `undefined` for non-terminal records (long-running paths
 *   stamp this on terminal transition)
 * - `terminalAt` — `Date.now()` timestamp when the task first entered a
 *   terminal state, or `undefined` when still in-flight
 * - `jobProxy` — the parked `JobProxy` for long-running tasks (handler
 *   returned a `JobProxy` instance); `null` for sync-completed records
 *   so the field stays present + type-stable.
 */
export interface TaskRecord {
  readonly sessionId: string;
  readonly requestMessage?: Record<string, unknown>;
  readonly terminalEnvelope?: Record<string, unknown>;
  readonly terminalAt?: number;
  readonly jobProxy?: JobProxy | null;
}

/**
 * Grace window in milliseconds before a terminal-state task is evicted from
 * the store. Matches Python's `_TERMINAL_GRACE_SECS = 300` and Java's
 * `MeshA2ATaskStore.TERMINAL_EVICTION_MILLIS` exactly for cross-runtime
 * parity (spec Appendix B item 5).
 */
export const TERMINAL_EVICTION_MS = 300_000;

/**
 * Process-local A2A task store.
 */
export class A2ATaskStore {
  private readonly store = new Map<string, TaskRecord>();

  /**
   * Store the task record for `taskId`. Caller is responsible for having
   * checked for duplicates via {@link contains} when uniqueness matters
   * (spec §4.3 idempotency window).
   */
  put(taskId: string, record: TaskRecord): void {
    this.sweepExpired();
    this.store.set(taskId, record);
  }

  /**
   * Atomically reserve `taskId` for an in-flight request by inserting a
   * placeholder record. Returns `true` when the slot was free and is now
   * reserved by the caller; returns `false` when the slot was already taken
   * (caller must surface the spec §4.3 "already in use" error).
   *
   * Closes the race window between `contains(taskId)` and `put(taskId, ...)`
   * for two concurrently-arriving `tasks/send` requests with the same id:
   * Node's event loop is single-threaded, but `await deps.handler(...)`
   * between the pre-check and the final `put()` yields control, letting
   * another request slip its own check through.
   */
  reserveTask(taskId: string, placeholder: TaskRecord): boolean {
    this.sweepExpired();
    if (this.store.has(taskId)) {
      return false;
    }
    this.store.set(taskId, placeholder);
    return true;
  }

  /**
   * Drop a previously-reserved placeholder for `taskId`. Used by callers
   * when the handler raised before producing a terminal envelope and the
   * reservation needs to be released so the failure envelope can be put
   * cleanly. No-op when the record is absent.
   */
  remove(taskId: string): void {
    this.store.delete(taskId);
  }

  /**
   * @returns the record for `taskId`, or `undefined` when missing or
   *     already evicted. Triggers a lazy sweep on each call.
   */
  get(taskId: string): TaskRecord | undefined {
    this.sweepExpired();
    return this.store.get(taskId);
  }

  /**
   * @returns `true` when the store currently holds a record for `taskId`
   *     and that record has not been evicted by the lazy sweep.
   */
  contains(taskId: string): boolean {
    this.sweepExpired();
    return this.store.has(taskId);
  }

  /** @returns current size (post-sweep). For diagnostics + tests. */
  size(): number {
    this.sweepExpired();
    return this.store.size;
  }

  /**
   * Atomically mark a previously parked non-terminal record as terminal by
   * stamping `terminalEnvelope` + `terminalAt`. No-op when the record is
   * absent or already terminal (idempotent — spec §4.5 "Idempotent;
   * best-effort"). First-write-wins is preserved.
   *
   * Used by Chunk 1B's long-running path to flip a `state=working` record
   * to a cached terminal envelope so subsequent `tasks/get` calls return
   * the same payload deterministically.
   *
   * @returns the new (or existing) terminal record, or `undefined` when
   *     the task is unknown
   */
  markTerminal(
    taskId: string,
    terminalEnvelope: Record<string, unknown>
  ): TaskRecord | undefined {
    this.sweepExpired();
    const existing = this.store.get(taskId);
    if (!existing) {
      return undefined;
    }
    if (existing.terminalAt !== undefined) {
      return existing;
    }
    const next: TaskRecord = {
      sessionId: existing.sessionId,
      requestMessage: existing.requestMessage,
      terminalEnvelope,
      terminalAt: Date.now(),
      // Preserve the JobProxy reference on the terminal record — callers
      // may want to read `proxy.status()` one last time for diagnostics
      // before the eviction sweep drops it (300s grace window).
      jobProxy: existing.jobProxy ?? null,
    };
    this.store.set(taskId, next);
    return next;
  }

  /** Clear all stored tasks. Mainly for testing. */
  clear(): void {
    this.store.clear();
  }

  /**
   * Lazy sweep: evict any record whose terminal-state timestamp is older
   * than {@link TERMINAL_EVICTION_MS}. Non-terminal records are never
   * evicted (long-running paths keep them alive across arbitrary
   * durations).
   */
  private sweepExpired(): void {
    const now = Date.now();
    for (const [taskId, record] of this.store) {
      if (record.terminalAt === undefined) continue;
      if (now - record.terminalAt > TERMINAL_EVICTION_MS) {
        this.store.delete(taskId);
      }
    }
  }
}
