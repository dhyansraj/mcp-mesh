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
import { JobController } from "@mcpmesh/core";
import {
  runWithJobContext,
  makeJobController,
} from "./inbound-job-dispatch.js";

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

  constructor(
    capability: string,
    instanceId: string,
    registryUrl: string,
    handler: ClaimHandler,
  ) {
    this.capability = capability;
    this.instanceId = instanceId;
    this.registryUrl = registryUrl;
    this.handler = handler;
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

  /** Signal stop and await the loop. Best-effort; never throws. */
  async stop(): Promise<void> {
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
        });
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
      return;
    }

    try {
      await runWithJobContext(jobId, deadlineSecs, controller, () =>
        this.handler(payload, controller),
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
    void this._dispatch(claimed).finally(() => this._release());
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
