/**
 * TypeScript-side claim dispatcher (Phase 1 — MeshJob substrate).
 *
 * Mirrors Python's `_mcp_mesh.engine.claim_dispatcher.PythonClaimDispatcher`.
 *
 * Per `MESHJOB_DESIGN.org` / "Producer-side flow / Resched": the
 * registry's HEAD heartbeat may include `X-Mesh-Pending-Jobs: <n>` when
 * this agent has unclaimed jobs in capabilities it serves. The runtime
 * calls `POST /jobs/claim` to atomically acquire one job per round-trip,
 * then dispatches it locally.
 *
 * Architecture choice for Phase 1
 * --------------------------------
 *
 * The Rust core exposes the substrate to do this in-process via
 * `crate::claim_worker::spawn_claim_worker` + a per-language
 * `ClaimDispatcher` trait. Bridging that trait to a JS object across
 * napi-rs (with proper `Send + Sync + 'static` bounds and an async
 * return) is non-trivial — the cleanest cross-language design ships in
 * Phase 2. For Phase 1 the dispatcher is implemented purely in TS:
 * a polling loop bound to the agent lifecycle.
 *
 * Concurrency cap defaults to 4 in-flight handlers, matching:
 *   - `crate::claim_worker::ClaimWorkerConfig::new` (Rust core)
 *   - `_MAX_CONCURRENT_DISPATCHES` (Python claim dispatcher)
 *
 * The permit is acquired BEFORE polling `/jobs/claim` (not after) so
 * the dispatcher cannot claim more jobs than it can immediately
 * execute. Without this, the dispatcher could pull a 5th job from the
 * registry and stamp itself as owner while it sat in a queue with the
 * lease ticking down — the registry would then orphan and re-claim the
 * job after the lease expired. PR #883 fixed this same divergence in
 * the Python dispatcher; we mirror the fix here from the start.
 */
import { Agent } from "undici";
import { JobController } from "@mcpmesh/core";
import {
  runWithJobContext,
  makeJobController,
} from "./inbound-job-dispatch.js";
import { runWithPropagatedHeaders } from "./proxy.js";

const _POLL_BASE_MS = 500;
const _POLL_MAX_MS = 5000;
const _MAX_CONCURRENT_DISPATCHES = 4;
const _CONSECUTIVE_FAILURES_ERROR_THRESHOLD = 5;

/**
 * Handler signature: the user's `task=true` execute function as
 * registered via `agent.addTool({ task: true, execute: ... })`. The
 * dispatcher invokes it with the claimed payload as args + the
 * controller injected at `meshJobParamIndex` (or appended if no index
 * is set on the spec).
 *
 * Returning a value is fine — the wrapper auto-completes the job with
 * the return value (matching Python's W8 fix). Throwing is also fine —
 * the wrapper reports the failure to the registry.
 */
export type ClaimHandler = (
  payload: Record<string, unknown>,
  controller: JobController,
) => Promise<unknown>;

/**
 * One dispatcher per (capability, handler) pair. Spawned on agent
 * startup for every tool registered with `task: true`.
 */
export class ClaimDispatcher {
  readonly capability: string;
  readonly instanceId: string;
  readonly registryUrl: string;
  private readonly handler: ClaimHandler;
  /**
   * Issue #894: per-tool retryOn whitelist. When the handler raises an
   * Error matching one of the constructor classes, the dispatch wrapper
   * calls `controller.releaseLease(reason)` instead of `fail(reason)`
   * so a peer replica can re-claim within ~5s. Threaded straight through
   * to `runWithJobContext`. `undefined` / `[]` disables retry (existing
   * fail-on-throw behaviour).
   */
  private readonly retryOn?: ReadonlyArray<new (...args: unknown[]) => Error>;

  private _stopped = false;
  private _loopPromise: Promise<void> | null = null;
  private _consecutiveFailures = 0;
  /**
   * Permits in-flight; counts down toward 0. The loop blocks on
   * `acquire()` before issuing a claim, so the dispatcher never owns
   * more jobs than it can immediately execute. Released in the
   * dispatch task's `finally` block.
   */
  private _permits = _MAX_CONCURRENT_DISPATCHES;
  /** Wake-up callbacks for the permit semaphore. */
  private _permitWaiters: Array<() => void> = [];
  /** Wake-up callbacks for the backoff sleep (so stop() exits promptly). */
  private _sleepWaiters: Array<() => void> = [];
  /**
   * In-flight handler dispatch promises. Tracked so `stop()` can drain
   * them before closing `_httpAgent` — without this, the keep-alive
   * pool gets torn down while handler `controller.complete(...)` /
   * `controller.fail(...)` calls are still mid-fetch, which surfaces
   * as cryptic socket-close errors and (worse) leaves rows in `working`
   * because the terminal delta never reached the registry.
   */
  private _inflightHandlers: Set<Promise<void>> = new Set();
  /**
   * Per-dispatcher keep-alive HTTP agent for `/jobs/claim` polls.
   *
   * Mirrors Python's `httpx.AsyncClient(timeout=10)` lifetime — one
   * client per dispatcher (not per poll) so the TLS handshake + TCP
   * connection are reused across the polling loop. Pool size matches
   * the dispatch semaphore (`_MAX_CONCURRENT_DISPATCHES`) since claim
   * polls are serialised by the loop and never need more than that.
   * Closed in `stop()` so socket pools don't leak across agent restarts.
   */
  private readonly _httpAgent: Agent = new Agent({
    keepAliveTimeout: 30_000,
    keepAliveMaxTimeout: 60_000,
    connections: _MAX_CONCURRENT_DISPATCHES,
  });

  constructor(
    capability: string,
    instanceId: string,
    registryUrl: string,
    handler: ClaimHandler,
    retryOn?: ReadonlyArray<new (...args: unknown[]) => Error>,
  ) {
    this.capability = capability;
    this.instanceId = instanceId;
    this.registryUrl = registryUrl;
    this.handler = handler;
    this.retryOn = retryOn;
  }

  /** Spawn the polling loop. Idempotent. */
  start(): void {
    if (this._loopPromise) return;
    this._loopPromise = this._runLoop().catch((err) => {
      console.error(
        `[mesh-claim] dispatcher capability=${this.capability} loop crashed:`,
        err,
      );
    });
  }

  /**
   * Signal stop and await the loop. Best-effort; never throws.
   *
   * Drain order:
   *   1. flip `_stopped` so the loop exits at its next yield;
   *   2. wake any blocked waiters so the loop observes the signal;
   *   3. await the loop promise (no more new dispatches after this);
   *   4. await any in-flight handler dispatches (bounded by `timeoutMs`)
   *      so handlers finish their final `controller.complete/fail` HTTP
   *      calls before `_httpAgent` is torn down;
   *   5. close the keep-alive pool.
   *
   * @param timeoutMs - Bounded wait for in-flight handlers. Defaults to
   *   30s — long enough that a typical job's terminal flush completes,
   *   short enough that a runaway handler doesn't block shutdown
   *   forever. Caller is free to override (e.g. tests pass `0` for an
   *   immediate close).
   */
  async stop(timeoutMs: number = 30_000): Promise<void> {
    this._stopped = true;
    // Wake any waiters so the loop can observe the stop signal.
    while (this._permitWaiters.length) this._permitWaiters.shift()!();
    while (this._sleepWaiters.length) this._sleepWaiters.shift()!();
    if (this._loopPromise) {
      try {
        await this._loopPromise;
      } catch {
        /* swallow */
      }
    }
    // Drain in-flight handler dispatches before closing the keep-alive
    // pool. `_inflightHandlers` is a Set<Promise<void>> populated in
    // _dispatchWithPermit; entries self-remove via .finally().
    if (this._inflightHandlers.size > 0) {
      const drain = Promise.allSettled([...this._inflightHandlers]);
      if (timeoutMs <= 0) {
        // Caller asked for an immediate close — skip the drain entirely.
      } else {
        let drainTimer: ReturnType<typeof setTimeout> | null = null;
        const drainTimeout = new Promise<void>((resolve) => {
          drainTimer = setTimeout(() => {
            console.warn(
              `[mesh-claim] capability=${this.capability} instance=${this.instanceId}: ` +
                `stop() drain timed out after ${timeoutMs}ms with ${this._inflightHandlers.size} ` +
                `handler(s) still in-flight; closing keep-alive pool anyway`,
            );
            resolve();
          }, timeoutMs);
        });
        try {
          await Promise.race([drain, drainTimeout]);
        } finally {
          if (drainTimer) clearTimeout(drainTimer);
        }
      }
    }
    // Close the keep-alive pool so sockets don't leak across agent
    // restarts in long-lived test harnesses (mirrors the Python
    // dispatcher's `httpx.AsyncClient.aclose()` in `stop()`).
    try {
      await this._httpAgent.close();
    } catch {
      /* best-effort cleanup */
    }
  }

  private async _acquire(): Promise<void> {
    if (this._permits > 0) {
      this._permits -= 1;
      return;
    }
    return new Promise<void>((resolve) => {
      this._permitWaiters.push(() => {
        this._permits -= 1;
        resolve();
      });
    });
  }

  private _release(): void {
    this._permits += 1;
    const next = this._permitWaiters.shift();
    if (next) next();
  }

  /**
   * Single `POST /jobs/claim` round-trip. Returns the list of claimed
   * jobs (empty when no work is available, or 1-element when a job
   * was claimed — the Phase 1 wire is single-claim).
   *
   * Errors are logged and treated as "no work" so the loop backs off
   * rather than crashing.
   */
  private async _claimOnce(): Promise<Array<Record<string, unknown>>> {
    const url = `${this.registryUrl.replace(/\/$/, "")}/jobs/claim`;
    const body = {
      capability: this.capability,
      instance_id: this.instanceId,
    };
    let resp: Response;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        resp = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
          // Keep-alive pool — reuses TCP/TLS across polls. See
          // `_httpAgent` field for sizing rationale. Cast required
          // because Node's `fetch` types don't expose the undici
          // dispatcher slot; runtime accepts it.
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          dispatcher: this._httpAgent as any,
        } as RequestInit);
      } finally {
        clearTimeout(timeout);
      }
    } catch (err) {
      this._consecutiveFailures += 1;
      this._logClaimFailure(
        `claim_once error: ${(err as Error)?.name ?? "Error"}: ${
          (err as Error)?.message ?? String(err)
        }`,
      );
      return [];
    }
    if (resp.status === 204) {
      this._consecutiveFailures = 0;
      return [];
    }
    if (resp.status !== 200) {
      this._consecutiveFailures += 1;
      this._logClaimFailure(`unexpected status ${resp.status} from ${url}`);
      return [];
    }
    let parsed: unknown;
    try {
      parsed = await resp.json();
    } catch (err) {
      this._consecutiveFailures += 1;
      this._logClaimFailure(`malformed JSON: ${(err as Error)?.message}`);
      return [];
    }
    const claimed = (parsed as { claimed?: unknown })?.claimed;
    if (!Array.isArray(claimed)) {
      this._consecutiveFailures += 1;
      this._logClaimFailure(
        `malformed response — 'claimed' is not a list: ${JSON.stringify(claimed)}`,
      );
      return [];
    }
    this._consecutiveFailures = 0;
    return claimed.filter(
      (c) => c && typeof c === "object" && (c as { id?: unknown }).id,
    ) as Array<Record<string, unknown>>;
  }

  /**
   * Fail a job by posting a single `failed` delta to `/jobs/batch`,
   * bypassing the (failed) controller construction path. Used as a
   * fallback when `makeJobController` throws — without this the row
   * stays in `working` until the lease sweep, which can be minutes.
   *
   * Best-effort: any error here is logged at warn level (we already
   * lost the controller for the original error, can't lose visibility
   * of the fallback too) but does not throw — the registry sweep is
   * still the ultimate backstop.
   */
  private async _failJobByIdDirectly(
    jobId: string,
    reason: string,
  ): Promise<void> {
    const url = `${this.registryUrl.replace(/\/$/, "")}/jobs/batch`;
    const body = {
      instance_id: this.instanceId,
      deltas: [
        {
          id: jobId,
          status: "failed",
          error: reason,
        },
      ],
    };
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          dispatcher: this._httpAgent as any,
        } as RequestInit);
        if (resp.status !== 200) {
          console.warn(
            `[mesh-claim] /jobs/batch returned ${resp.status} when failing ` +
              `job=${jobId} after controller construction failure; relying ` +
              `on registry sweep`,
          );
        }
      } finally {
        clearTimeout(timeout);
      }
    } catch (err) {
      console.warn(
        `[mesh-claim] /jobs/batch fail-fast for job=${jobId} raised:`,
        err,
      );
    }
  }

  private _logClaimFailure(detail: string): void {
    const msg =
      `[mesh-claim] capability=${this.capability} instance=${this.instanceId}: ` +
      `${detail} (consecutive_failures=${this._consecutiveFailures})`;
    if (this._consecutiveFailures >= _CONSECUTIVE_FAILURES_ERROR_THRESHOLD) {
      console.error(msg);
    } else {
      console.warn(msg);
    }
  }

  /**
   * Run the local handler for a claimed job. The handler signature is
   * `(payload, controller) => Promise<unknown>`; the wrapper sets both
   * job contexts (JS ALS + Rust task-local) and auto-completes if the
   * handler returns without explicitly closing the row.
   */
  private async _dispatch(claimed: Record<string, unknown>): Promise<void> {
    const jobId = String(claimed.id ?? "");
    if (!jobId) return;

    const payload =
      claimed.submitted_payload && typeof claimed.submitted_payload === "object"
        ? (claimed.submitted_payload as Record<string, unknown>)
        : {};
    const maxDur = claimed.max_duration as number | undefined;
    const deadlineSecs =
      typeof maxDur === "number" && maxDur > 0 ? maxDur : null;

    let controller: JobController;
    try {
      controller = makeJobController(jobId, this.instanceId, this.registryUrl);
    } catch (err) {
      console.warn(
        `[mesh-claim] failed to construct JobController for job=${jobId}:`,
        err,
      );
      // Fail the job immediately so the registry doesn't wait on lease
      // expiry to mark the row terminal — without this the row sits in
      // `working` indefinitely (visible to users as a stuck job) until
      // the lease sweeper notices. We can't use controller.fail()
      // because controller construction is what failed; instead we
      // POST a single `failed` delta to /jobs/batch directly using the
      // dispatcher's keep-alive agent.
      await this._failJobByIdDirectly(
        jobId,
        `controller construction failed: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
      return;
    }

    // Seed the propagated-headers ALS so outbound calls made by the
    // handler continue the submitter's trace tree and carry the job
    // context onward. Mirrors Python's
    // `TraceContext.set_propagated_headers` block in
    // `_mcp_mesh.engine.claim_dispatcher.PythonClaimDispatcher._dispatch`.
    //
    // Trace headers (`x-trace-id`, `x-parent-span`) are not echoed by
    // the registry's claim response in the current wire (see
    // `src/core/registry/ent_handlers_jobs.go::ClaimJobs`), so we only
    // seed `x-mesh-job-id` + `x-mesh-timeout` here. If a future schema
    // adds `trace_id` to ClaimedJob, fold it in alongside.
    const headers: Record<string, string> = {
      "x-mesh-job-id": jobId,
    };
    if (deadlineSecs !== null && deadlineSecs > 0) {
      headers["x-mesh-timeout"] = String(deadlineSecs);
    }

    try {
      await runWithPropagatedHeaders(headers, () =>
        runWithJobContext(
          jobId,
          deadlineSecs,
          controller,
          () => this.handler(payload, controller),
          this.retryOn,
        ),
      );
    } catch (err) {
      console.warn(
        `[mesh-claim] handler raised for job=${jobId} capability=${this.capability}:`,
        err,
      );
      // runWithJobContext already attempted a best-effort
      // controller.fail() before re-throwing; nothing more to do here.
    }
  }

  /**
   * Main loop. Acquire-then-claim ordering — see class docstring.
   */
  private async _runLoop(): Promise<void> {
    let backoffMs = _POLL_BASE_MS;
    console.log(
      `[mesh-claim] dispatcher started: capability=${this.capability} instance=${this.instanceId}`,
    );

    while (!this._stopped) {
      // Acquire BEFORE claim so we never pull a job we can't run.
      await this._acquire();
      if (this._stopped) {
        this._release();
        break;
      }
      let permitTransferred = false;
      try {
        const claimed = await this._claimOnce();
        if (claimed.length > 1) {
          // Defensive warn (W3): the Phase 1 wire is single-claim by
          // design — `POST /jobs/claim` returns at most one job per
          // round-trip (see `crate::claim_worker::ClaimWorkerConfig`
          // and the registry's ClaimJobs handler). Receiving > 1 here
          // means a future wire change (multi-claim) shipped without
          // re-validating the dispatcher's permit accounting. We
          // already handle the multi-claim case via the
          // re-acquire-per-extra loop below — the warn just surfaces
          // the unexpected shape so a future wire change is caught
          // explicitly rather than silently relying on the loop.
          console.warn(
            `[mesh-claim] capability=${this.capability} instance=${this.instanceId}: ` +
              `unexpected multi-claim response (got ${claimed.length} jobs) — ` +
              `Phase 1 wire is single-claim by design; defensive multi-claim ` +
              `path engaged`,
          );
        }
        if (claimed.length > 0) {
          // First claim: hand the permit ownership to the dispatch
          // task. Future-safe extras: re-acquire permits one-by-one.
          let first = true;
          for (const job of claimed) {
            if (first) {
              first = false;
              permitTransferred = true;
              this._dispatchWithPermit(job);
            } else {
              await this._acquire();
              this._dispatchWithPermit(job);
            }
          }
          backoffMs = _POLL_BASE_MS;
          continue;
        }
        // No work — wait with backoff. Release permit; we won't use it.
        this._release();
        permitTransferred = true; // already released; finally must skip
        await this._sleep(backoffMs);
        backoffMs = Math.min(backoffMs * 2, _POLL_MAX_MS);
      } finally {
        if (!permitTransferred) {
          this._release();
        }
      }
    }
    console.log(
      `[mesh-claim] dispatcher stopped: capability=${this.capability} instance=${this.instanceId}`,
    );
  }

  private _dispatchWithPermit(claimed: Record<string, unknown>): void {
    // Spawn but do NOT await — _runLoop continues to the next claim
    // attempt. The permit is released when this dispatch finishes.
    // Track the promise in `_inflightHandlers` so `stop()` can drain
    // any in-flight handlers before closing the keep-alive Agent.
    const p: Promise<void> = this._dispatch(claimed).finally(() => {
      this._inflightHandlers.delete(p);
      this._release();
    });
    this._inflightHandlers.add(p);
  }

  private _sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      let resolved = false;
      const wake = () => {
        if (resolved) return;
        resolved = true;
        clearTimeout(handle);
        const idx = this._sleepWaiters.indexOf(wake);
        if (idx >= 0) this._sleepWaiters.splice(idx, 1);
        resolve();
      };
      const handle = setTimeout(wake, ms);
      this._sleepWaiters.push(wake);
    });
  }
}
