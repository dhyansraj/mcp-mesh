/**
 * Inbound `MeshJob` dispatch wrapper (Phase 1 — MeshJob substrate).
 *
 * Mirrors Python's `_mcp_mesh.engine.job_dispatch.maybe_dispatch_as_job`.
 *
 * When a tool registered with `task: true` receives an inbound
 * `tools/call` carrying `X-Mesh-Job-Id`, this wrapper:
 *
 *   1. Reads `X-Mesh-Job-Id` and (optionally) `X-Mesh-Timeout` from the
 *      propagated headers (TS upstream proxies inject these into the
 *      tool's args under `_mesh_headers`; the inbound `tools/call`
 *      handler in agent.ts extracts them into a header dict before
 *      invoking this wrapper).
 *   2. Builds a `JobController` from `@mcpmesh/core` bound to that job
 *      id and the running agent's instance id.
 *   3. Sets BOTH the JS-side `CURRENT_JOB` AsyncLocalStorage AND the
 *      Rust-side `with_job` task-local via `withJobAsync` from
 *      `@mcpmesh/core`. Both are needed:
 *        * JS-side for in-process `currentJob()` reads;
 *        * Rust-side for the cancel-registry binding (so
 *          `POST /jobs/{id}/cancel` can fire the in-flight token) and
 *          for outbound HTTP header injection on Rust-originated work.
 *   4. Injects the `JobController` into the user function's args at
 *      `meshJobParamIndex`.
 *   5. Awaits the user function inside both contexts.
 *   6. Auto-completes the controller with the user's return value if the
 *      user did not explicitly call `complete()`/`fail()`.
 *
 * Tools without `task: true` are bypassed entirely (zero overhead).
 * `task: true` tools invoked WITHOUT `X-Mesh-Job-Id` (a regular
 * synchronous `tools/call`) fall through to the user function with
 * `null` in the MeshJob slot per `MESHJOB_DDDI_CONTRACT.md`.
 *
 * The dispatch logic is centralised here so the per-tool wrapper in
 * `agent.ts` and the claim dispatcher both call into the same path.
 */
import { JobController, withJobAsync } from "@mcpmesh/core";
import { CURRENT_JOB, type JobContextSnapshot } from "./job-context.js";

const _HDR_JOB_ID = "x-mesh-job-id";
const _HDR_TIMEOUT = "x-mesh-timeout";
// Claim generation minted by the registry on POST /jobs/claim (issue #1252).
// Seeded by the claim dispatcher; absent on the push-mode inbound path.
const _HDR_CLAIM_EPOCH = "x-mesh-claim-epoch";

/**
 * Read `X-Mesh-Job-Id` / `X-Mesh-Timeout` / `X-Mesh-Claim-Epoch` from a
 * header dict (case normalised to lowercase). Returns
 * `[null, null, null]` when the job id is absent. `claimEpoch` is present
 * only on the claim path; a push-mode inbound job leaves it `null` (legacy
 * owner-only fencing) — a non-negative integer is required (never fabricate
 * a `0` the registry didn't mint).
 */
export function readJobHeaders(
  headers: Record<string, string> | null | undefined,
): [string | null, number | null, number | null] {
  if (!headers) return [null, null, null];
  const jobId = headers[_HDR_JOB_ID] ?? null;
  if (!jobId) return [null, null, null];
  const timeoutRaw = headers[_HDR_TIMEOUT];
  let deadlineSecs: number | null = null;
  if (timeoutRaw) {
    const parsed = parseFloat(timeoutRaw);
    if (Number.isFinite(parsed) && parsed > 0) {
      deadlineSecs = parsed;
    }
  }
  const epochRaw = headers[_HDR_CLAIM_EPOCH];
  let claimEpoch: number | null = null;
  // Strict: only a clean, wholly-numeric, non-negative integer string is a
  // real epoch. `Number.parseInt` is too permissive (`"5.5"`/`"5abc"` → 5),
  // so match the whole string against digits first — aligns with the
  // claim-dispatcher's number-typed `Number.isInteger` check. Never fabricate
  // a `0` the registry didn't mint (empty/malformed ⇒ null ⇒ legacy path).
  if (epochRaw !== undefined && /^\d+$/.test(epochRaw)) {
    const parsed = Number(epochRaw);
    if (Number.isInteger(parsed) && parsed >= 0) {
      claimEpoch = parsed;
    }
  }
  return [jobId, deadlineSecs, claimEpoch];
}

/**
 * Best-effort JSON-safety check for the auto-complete payload.
 *
 * Mirrors the Python helper: primitives, plain arrays of safe values,
 * and plain objects keyed by strings with safe values pass through.
 * Anything else (Map, Set, class instances, Symbol, BigInt, undefined,
 * functions) gets wrapped as `{ value: String(result) }` so the Rust
 * JSON layer doesn't error inside auto-complete.
 *
 * The plain-object check uses `Object.getPrototypeOf` rather than
 * `Object.entries`, because Maps/Sets/class instances have empty
 * `Object.entries(...)` results — which would otherwise (mis-)pass the
 * "every entry is safe" guard.
 */
function isJsonSafe(value: unknown): boolean {
  if (value === null) return true;
  const t = typeof value;
  if (t === "boolean" || t === "number" || t === "string") {
    // Reject NaN / +Infinity — they JSON-stringify to `null` and would
    // round-trip lossy through the registry's payload column.
    if (t === "number" && !Number.isFinite(value as number)) return false;
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonSafe);
  if (t === "object") {
    // Plain-object check: prototype must be Object.prototype or null.
    // This rejects Maps, Sets, Dates, class instances, etc. — all of
    // which serialise to `{}` (lossy) under default JSON.stringify and
    // would not survive the FFI serde-json round-trip cleanly.
    const proto = Object.getPrototypeOf(value);
    if (proto !== Object.prototype && proto !== null) return false;
    return Object.entries(value as Record<string, unknown>).every(
      ([k, v]) => typeof k === "string" && isJsonSafe(v),
    );
  }
  return false;
}

/**
 * Run `invoke()` inside a job context (when `jobId` is set) or
 * directly (otherwise).
 *
 * `invoke` must be a thunk — when the caller wants to inject the
 * controller into the user function's args, it is the caller's
 * responsibility to overlay the controller before passing the thunk.
 *
 * `controller` may be `null` when the call is NOT a job (no
 * `X-Mesh-Job-Id`). In that case the wrapper just runs the thunk.
 *
 * @param jobId - Server-assigned job UUID (from `X-Mesh-Job-Id`), or
 *   `null` when the call is a regular `tools/call`.
 * @param deadlineSecs - Per-attempt deadline in seconds (from
 *   `X-Mesh-Timeout`), or `null`.
 * @param controller - Pre-constructed `JobController` bound to `jobId`,
 *   or `null` when not running as a job.
 * @param invoke - Thunk that runs the user function and returns its
 *   result. The caller has already overlaid the controller into the
 *   user function's args at `meshJobParamIndex`.
 * @param retryOn - Issue #894: per-tool retry-eligible exception
 *   whitelist. When the user thunk raises an Error matching one of the
 *   constructor classes, the wrapper calls `controller.releaseLease`
 *   instead of `controller.fail` so a peer replica can re-claim within
 *   ~5s. `undefined` / `[]` disables retry (existing fail-on-throw
 *   behaviour). Match check is `err instanceof cls`.
 */
export async function runWithJobContext<T>(
  jobId: string | null,
  deadlineSecs: number | null,
  controller: JobController | null,
  invoke: () => Promise<T>,
  retryOn?: ReadonlyArray<new (...args: unknown[]) => Error>,
  claimEpoch: number | null = null,
): Promise<T> {
  if (!jobId || !controller) {
    // Not a job — run directly.
    return invoke();
  }

  const snap: JobContextSnapshot = {
    jobId,
    deadlineSecsRemaining: deadlineSecs,
    claimEpoch,
  };

  // Auto-complete on successful return iff the user didn't already
  // close the row themselves. Matches Python's `_run_and_autocomplete`.
  // On exception we let the throw propagate; we attempt a best-effort
  // `controller.fail(...)` only if the controller is not yet terminal.
  //
  // We capture the user's actual return value in a closure (`captured`)
  // and feed only a JSON-safe sentinel (`null`) through the napi
  // boundary in `withJobAsync`. The user value goes back to the JS
  // caller via the returned closure variable — keeping non-JSON-safe
  // returns (Map, Symbol, class instance, BigInt, undefined) from
  // hitting the Rust serde-json round-trip and producing a cryptic
  // FFI error. The auto-complete path still applies `isJsonSafe` and
  // wraps non-safe values for `controller.complete(...)`.
  let captured: T;
  let didCapture = false;
  // Issue #894: when retryOn matches we suppress the user's exception
  // and the wrapper returns the default value of T (undefined). The
  // claim-dispatch path is the primary consumer; it ignores the return
  // value when re-claim happens. Inbound HTTP path is a no-op for
  // retryOn since headers-driven invocations don't auto-retry on the
  // producer side anyway.
  let suppressed = false;
  const runAndAutoComplete = async (): Promise<null> => {
    try {
      captured = await invoke();
      didCapture = true;
    } catch (err) {
      // Step 1: probe is_terminal — if user already called complete/fail,
      // their terminal call is the source of truth; leave the row alone
      // and propagate.
      let alreadyTerminal = false;
      try {
        alreadyTerminal = await controller.isTerminal();
      } catch {
        // Probe failed; treat as not-terminal so we still attempt a
        // best-effort terminal report below.
      }
      if (alreadyTerminal) throw err;

      // Step 2 (issue #894): retryOn match → releaseLease so a peer
      // replica can re-claim within ~5s. Suppress the exception on
      // success — the job lifecycle becomes the registry's responsibility.
      if (
        retryOn &&
        retryOn.length > 0 &&
        err instanceof Error &&
        retryOn.some((cls) => err instanceof cls)
      ) {
        const reason = `${err.constructor.name}: ${err.message}`;
        try {
          await controller.releaseLease(reason);
          suppressed = true;
          return null;
        } catch (releaseErr) {
          // releaseLease failed — fall back to fail() so the row
          // doesn't sit in `working` until lease expiry. Best-effort;
          // swallow any further failure (the registry's lease sweeper
          // is the ultimate backstop). Log for parity with Python
          // (`job_dispatch.py:365-383`) so operators can correlate
          // unexpected fail-rows with the underlying release failure.
          console.warn(
            `[mesh-jobs] release_lease failed for job=${jobId} (${
              releaseErr instanceof Error
                ? releaseErr.message
                : String(releaseErr)
            }); falling back to fail()`,
          );
          try {
            await controller.fail(
              `retry-eligible ${reason}; release_lease failed: ${
                releaseErr instanceof Error
                  ? releaseErr.message
                  : String(releaseErr)
              }`,
            );
          } catch (failErr) {
            console.debug(
              `[mesh-jobs] fallback fail() also failed for job=${jobId}:`,
              failErr,
            );
          }
          suppressed = true;
          return null;
        }
      }

      // Step 3: non-retryable → existing behaviour (best-effort fail()
      // then propagate).
      try {
        await controller.fail(
          err instanceof Error ? err.message : String(err),
        );
      } catch {
        // Swallow — the registry sweep is the ultimate backstop.
      }
      throw err;
    }

    // Only auto-complete if the user didn't already call complete/fail.
    try {
      const alreadyTerminal = await controller.isTerminal();
      if (alreadyTerminal) return null;
    } catch {
      // If we can't probe, skip auto-complete to avoid double-flush.
      return null;
    }
    try {
      const safe = isJsonSafe(captured)
        ? captured
        : { value: String(captured) };
      await controller.complete(safe);
    } catch {
      // Auto-complete failed — registry sweep will eventually mark
      // the row terminal. Don't shadow the user's return value.
    }
    return null;
  };

  // Bind the JS-side ALS first; then bind the Rust-side task-local
  // around the same Promise so cancel registry + outbound headers see
  // the active job. Both must be set in parallel because the Rust
  // task-local does NOT cross the FFI boundary into the Node loop.
  //
  // The Promise handed to `withJobAsync` resolves to `null` (the
  // sentinel) — Rust serde never sees the user's value, so non-JSON
  // returns can't trip the FFI boundary. The user's actual return is
  // pulled from `captured` after the await resolves.
  return CURRENT_JOB.run(snap, async () => {
    const body = runAndAutoComplete();
    // Bind claim_epoch onto the Rust JobContext so currentJob() exposes it
    // (issue #1252). The napi core ships with this SDK in lockstep.
    await withJobAsync(jobId, deadlineSecs, body, claimEpoch ?? undefined);
    if (!didCapture) {
      if (suppressed) {
        // Issue #894: the user threw a retryOn-matched exception and the
        // wrapper called releaseLease() (or its fail() fallback). The
        // lifecycle is now the registry's concern — return undefined to
        // unwind. wrappedExecute (agent.ts) maps undefined/null to the
        // empty string "" before FastMCP serialises the response, which
        // is benign here because the registry's row state (working/failed)
        // is what consumers poll on, not the inbound HTTP body.
        return undefined as unknown as T;
      }
      // Defensive: the body resolved without setting `captured` —
      // should be unreachable since runAndAutoComplete only returns
      // after invoke() succeeds (which sets captured), but guard
      // against future refactors.
      throw new Error(
        "runWithJobContext: invoke completed but no value was captured",
      );
    }
    return captured;
  });
}

/**
 * Construct a `JobController` for `(jobId, instanceId, registryUrl)`.
 *
 * Wraps the napi binding so callers don't import `@mcpmesh/core`
 * directly — keeps the injection point in agent.ts compact.
 */
export function makeJobController(
  jobId: string,
  instanceId: string,
  registryUrl: string,
  claimEpoch?: number | null,
): JobController {
  // `claimEpoch` undefined/null (push-mode inbound job / old registry) ⇒
  // legacy owner-only fencing; on the claim path the dispatcher passes the
  // epoch from the /jobs/claim response so this execution is fenced (#1252).
  return new JobController(
    jobId,
    instanceId,
    registryUrl,
    claimEpoch ?? undefined,
  );
}

/**
 * Build the positional call args array for a `task: true` tool, splicing
 * the `controller` into the user signature at `meshJobParamIndex`.
 *
 * Position 0 is always the parsed `args` payload; deps begin at 1. The
 * MeshJob slot is orthogonal to MeshTool positional indexing — when
 * `meshJobParamIndex` lands inside the dep range the deps shift past
 * it; when it lands after all deps the helper pads any gap with `null`
 * and places the controller at the trailing position.
 *
 * Centralised here so both the inbound HTTP wrapper (agent.ts) and the
 * claim-path dispatcher (claim handler in agent.ts) share one
 * implementation — historically these splice loops had drifted apart.
 *
 * @param payload - The parsed `args` payload (signature position 0).
 * @param deps - Resolved dep proxies (or `MeshJobSubmitter` for the
 *   meshJobDepIndex slot, or `null` for unresolved deps) in declaration
 *   order. Positionally injected starting at sig pos 1.
 * @param controller - The `JobController` to inject at
 *   `meshJobParamIndex`, or `null` when the call is not running under
 *   a job context.
 * @param meshJobParamIndex - Signature position where the controller
 *   should land, or `undefined` when the user didn't declare a MeshJob
 *   slot (controller is then dropped — the user just doesn't get one).
 */
export function spliceJobController<D>(
  payload: unknown,
  deps: ReadonlyArray<D>,
  controller: JobController | null,
  meshJobParamIndex: number | undefined,
): unknown[] {
  const callArgs: unknown[] = [payload];
  let depCursor = 0;
  let pos = 1;
  while (depCursor < deps.length || pos === meshJobParamIndex) {
    if (pos === meshJobParamIndex) {
      callArgs.push(controller);
      pos += 1;
      continue;
    }
    callArgs.push(deps[depCursor]);
    depCursor += 1;
    pos += 1;
  }
  // Trailing meshJobParamIndex case (after all deps).
  if (
    meshJobParamIndex !== undefined &&
    callArgs.length <= meshJobParamIndex
  ) {
    while (callArgs.length < meshJobParamIndex) {
      callArgs.push(null);
    }
    callArgs[meshJobParamIndex] = controller;
  }
  return callArgs;
}
