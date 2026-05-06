/**
 * Consumer-side `MeshJob` submitter (Phase 1 — MeshJob substrate).
 *
 * Mirrors Python's `_mcp_mesh.engine.mesh_job_submitter.MeshJobSubmitter`.
 *
 * When a consumer tool declares a parameter typed as `MeshJob` (i.e.
 * `meshJobParamIndex` is set on the resolved tool definition), the
 * runtime injects an instance of this class into that slot. The user
 * calls `await submitter.submit({ payload: ..., maxDuration: ... })` to
 * enqueue work on the remote producer and gets back a `JobProxy`
 * exposing `wait`/`status`/`cancel`.
 *
 * Per the design's "decouple resolver from capability metadata"
 * decision: this class does NOT verify the target capability is
 * registered with `task=true`. The registry rejects `submit_job`
 * against a non-task capability with a clear error which surfaces
 * verbatim to the caller.
 *
 * Resilience: `submit` retries on transient registry errors (network
 * drops / 5xx / 503) up to 3 attempts with 200ms then 1s backoff
 * between them. 4xx / NotFound / Conflict / serialization errors
 * propagate immediately — those won't self-heal.
 */
import { submitJob, type JobProxy } from "@mcpmesh/core";

const _SUBMIT_MAX_ATTEMPTS = 3;
// Backoff applied BETWEEN attempts. With 3 attempts there are 2 gaps,
// so this array has exactly 2 entries — a third entry would never be
// reached (the previous `[200, 1000, 5000]` had the 5s tier silently
// dead). Tests assert 3 total attempts; mirror that here precisely.
const _SUBMIT_BACKOFF_MS = [200, 1000];

/**
 * Heuristic: does this error string represent a transient registry
 * failure that's worth retrying? Errs on the side of NOT retrying when
 * the signal is ambiguous — submit failures are user-facing and a fast
 * clear failure beats a slow flaky one.
 *
 * The Rust napi binding propagates `JobError` as `Error(message)`. The
 * Rust side emits messages like:
 *   "backend error: network error: <reqwest::Error>"
 *   "backend error: backend unavailable: <body>"
 *   "backend error: server error (HTTP 502): <body>"
 *   "backend error: backend error: HTTP 400: <body>"   (4xx, NOT transient)
 *   "backend error: job not found: <id>"               (404, NOT transient)
 *   "backend error: conflict: <reason>"                (409, NOT transient)
 */
function isTransientSubmitError(err: unknown): boolean {
  const msg = String((err as Error)?.message ?? err).toLowerCase();
  if (msg.includes("network error")) return true;
  if (msg.includes("backend unavailable")) return true;
  if (msg.includes("server error (http 5")) return true;
  return false;
}

/**
 * Per-submission options for `MeshJobSubmitter.submit(...)`. Matches
 * the napi `SubmitJobArgs` shape (minus `registryUrl`/`capability`/
 * `submittedBy` which the submitter binds at construction).
 */
export interface SubmitOptions {
  /** Per-attempt soft timeout (seconds). `undefined` ≡ registry default. */
  maxDuration?: number;
  /**
   * Maximum retries on failure (registry default is 1 — one attempt,
   * no retry). `undefined` ≡ registry default.
   */
  maxRetries?: number;
  /**
   * Absolute wall-clock deadline across all retries. Accepts a `Date`
   * or a unix-epoch number (seconds). `undefined` ≡ unlimited per the
   * "Resolved Decisions" section of MESHJOB_DESIGN.org.
   */
  totalDeadline?: Date | number;
}

/**
 * Per-binding submit handle for a `MeshJob`-typed dependency.
 *
 * Constructed by the dependency injector at agent startup, one per
 * (consumer-tool, dependency-capability) pair.
 */
export class MeshJobSubmitter {
  /** Remote capability this submitter targets. */
  readonly capability: string;
  /** Identifier written to the registry's `submitted_by` column. */
  readonly submittedBy: string;
  /** Base URL of the mesh registry. */
  readonly registryUrl: string;

  constructor(
    capability: string,
    submittedBy: string,
    registryUrl: string,
  ) {
    this.capability = capability;
    this.submittedBy = submittedBy;
    this.registryUrl = registryUrl;
  }

  /**
   * Submit a new job on the bound capability and return a `JobProxy`.
   *
   * The first positional argument carries the user-supplied payload
   * fields the producer will receive as its tool args. Optional
   * second-arg knobs map to registry columns (`max_duration`,
   * `max_retries`, `total_deadline`).
   *
   * @example
   * ```ts
   * const proxy = await jobSubmitter.submit(
   *   { user_id: "demo", sections: ["intro", "summary"] },
   *   { maxDuration: 60 },
   * );
   * const result = await proxy.wait(60);
   * ```
   *
   * Error semantics:
   *   - Transient registry errors (network/5xx/503) → up to 3 attempts
   *     with 200ms then 1s backoff between them before propagating.
   *   - 4xx / NotFound / Conflict / serialization → fail-fast.
   */
  async submit(
    payload: Record<string, unknown>,
    options: SubmitOptions = {},
  ): Promise<JobProxy> {
    let totalDeadlineEpoch: number | undefined;
    if (options.totalDeadline !== undefined) {
      if (options.totalDeadline instanceof Date) {
        totalDeadlineEpoch = Math.floor(options.totalDeadline.getTime() / 1000);
      } else if (typeof options.totalDeadline === "number") {
        // If looks like ms, downgrade to seconds. Anything > 1e12 is ms.
        totalDeadlineEpoch =
          options.totalDeadline > 1e12
            ? Math.floor(options.totalDeadline / 1000)
            : Math.floor(options.totalDeadline);
      } else {
        throw new TypeError(
          `MeshJobSubmitter.submit: totalDeadline must be a Date or a number ` +
            `(unix epoch seconds); got ${typeof options.totalDeadline}`,
        );
      }
    }

    let lastErr: unknown = null;
    for (let attempt = 1; attempt <= _SUBMIT_MAX_ATTEMPTS; attempt++) {
      try {
        const proxy = await submitJob({
          registryUrl: this.registryUrl,
          capability: this.capability,
          payload,
          submittedBy: this.submittedBy,
          // Let the registry assign owner via pull-claim.
          ownerInstanceId: undefined,
          maxDuration: options.maxDuration,
          maxRetries: options.maxRetries,
          totalDeadline: totalDeadlineEpoch,
        });
        return proxy;
      } catch (err) {
        lastErr = err;
        if (!isTransientSubmitError(err) || attempt >= _SUBMIT_MAX_ATTEMPTS) {
          throw err;
        }
        const backoffMs =
          _SUBMIT_BACKOFF_MS[Math.min(attempt - 1, _SUBMIT_BACKOFF_MS.length - 1)];
        await new Promise((resolve) => setTimeout(resolve, backoffMs));
      }
    }
    // Defensive — unreachable: we either return or throw above.
    throw lastErr ?? new Error("MeshJobSubmitter.submit: unreachable");
  }
}
