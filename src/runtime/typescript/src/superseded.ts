/**
 * Typed supersession signal (issue #1278).
 *
 * A provider tool that detects it is being called by a SUPERSEDED executor —
 * the app compares the calling job's epoch via {@link callingJob} (issue
 * #1263) against its own live epoch — rejects the call by throwing
 * {@link MeshSupersededError}. That crosses the wire as the reserved app
 * envelope `{"error":"claim_superseded"}` (plus an optional `"detail"`
 * string), and the CALLING side's injected proxy recognizes the envelope and
 * re-throws {@link MeshSupersededError}. A superseded caller then unwinds with
 * one `catch (e) { if (e instanceof MeshSupersededError) ... }` instead of
 * string-matching `claim_superseded` after every mutating call.
 *
 * The framework does NOT auto-detect supersession — the app decides (full
 * control); the framework provides the typed class plus the emit/recognize
 * plumbing. This is the structural parallel of the `dependency_unavailable`
 * refusal (issue #1273): both throw a `UserError` whose message is a reserved
 * JSON envelope, so the contract (not the carrier) drives classification.
 */

import { UserError } from "fastmcp";

/**
 * Reserved marker string for the supersession envelope. This is the SAME
 * canonical marker the job path already uses on the wire (Rust
 * `task_backend.rs` `CLAIM_SUPERSEDED_REASON` / Go `ent_service_jobs.go`),
 * reused verbatim so a superseded signal is one string end-to-end.
 */
export const CLAIM_SUPERSEDED_MARKER = "claim_superseded";

/**
 * Thrown by a provider tool to reject a call from a superseded executor.
 *
 * Extends fastmcp's {@link UserError} — the same error primitive the
 * `dependency_unavailable` refusal uses (agent.ts) — so throwing it from a
 * `@mesh.tool` handler auto-emits an `isError` tool result whose text is the
 * reserved envelope, through the EXISTING fastmcp UserError path (fastmcp maps
 * a thrown `UserError` to `{content:[{text: error.message}], isError:true}`,
 * so no provider wrapper change is needed).
 *
 * The serialized message (`err.message`) is
 * `{"error":"claim_superseded","detail":<detail>}` — the `detail` key is
 * omitted entirely when no detail is supplied.
 *
 * Provider usage:
 * ```ts
 * const cj = callingJob();
 * if (cj && cj.claimEpoch != null && cj.claimEpoch < myLiveEpoch) {
 *   throw new MeshSupersededError(`stale epoch ${cj.claimEpoch}`);
 * }
 * ```
 *
 * `if (e instanceof MeshSupersededError)` is the specific catch this enables;
 * because it IS a `UserError`, `if (e instanceof UserError)` still catches it
 * too.
 */
export class MeshSupersededError extends UserError {
  readonly detail?: string;

  constructor(detail?: string) {
    const envelope: { error: string; detail?: string } = {
      error: CLAIM_SUPERSEDED_MARKER,
    };
    if (detail !== undefined) {
      envelope.detail = detail;
    }
    super(JSON.stringify(envelope));
    this.name = "MeshSupersededError";
    this.detail = detail;
  }
}

/**
 * Return a {@link MeshSupersededError} if `text` is the reserved supersession
 * envelope, else `null`.
 *
 * Defensive parse for the consumer recognize path: a non-JSON body, a JSON
 * body that is not a plain object, or one whose `error` field is not exactly
 * the reserved marker all return `null` so the caller falls through to its
 * existing generic error handling. Only the exact reserved marker is
 * classified — a `dependency_unavailable` (or any other) envelope is left
 * alone.
 */
export function parseSupersededEnvelope(
  text: string,
): MeshSupersededError | null {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  if (
    payload === null ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return null;
  }
  const obj = payload as Record<string, unknown>;
  if (obj.error !== CLAIM_SUPERSEDED_MARKER) {
    return null;
  }
  const detail = obj.detail;
  return new MeshSupersededError(
    typeof detail === "string" ? detail : undefined,
  );
}
