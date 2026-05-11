/**
 * Mesh job lifecycle ↔ A2A v1.0 state translation (spec §7.2).
 *
 * The mesh job substrate emits these internal statuses:
 * - `working`, `completed`, `failed`, `cancelled` (UK spelling)
 *
 * A2A v1.0 uses:
 * - `working`, `completed`, `failed`, `canceled` (US spelling)
 *
 * The UK ↔ US spelling boundary is the most error-prone part of the
 * translation (spec Appendix B item flagged). Consumers accept both
 * spellings; producers MUST emit the US form.
 *
 * Unknown / unset mesh statuses fall back to `working` — preserves the
 * invariant that we never emit an A2A state outside the spec's enumerated
 * set, even when the registry reports a status we haven't mapped. Mirrors
 * Java's `MeshA2AStateTranslator.fromMesh` exactly.
 */

/** A2A v1.0 state: task submitted (conceptual — never actually emitted by the producer). */
export const A2A_SUBMITTED = "submitted";
/** A2A v1.0 state: long-running task in flight. */
export const A2A_WORKING = "working";
/** A2A v1.0 terminal state: task finished successfully. */
export const A2A_COMPLETED = "completed";
/** A2A v1.0 terminal state: handler raised or job failed. */
export const A2A_FAILED = "failed";
/** A2A v1.0 terminal state: task canceled (US spelling). */
export const A2A_CANCELED = "canceled";

/**
 * Translate a mesh job status string to its A2A v1.0 equivalent.
 *
 * Mapping table:
 * - `pending` → `submitted` (conceptual; mesh produces it briefly before claim)
 * - `working` / `running` → `working`
 * - `completed` → `completed`
 * - `failed` → `failed`
 * - `cancelled` (UK) / `canceled` (US) → `canceled` (US — A2A spelling)
 * - `cancelling` → `working` (still in progress; cancel signal in flight)
 * - anything else / null / empty → `working` (fallback)
 *
 * @param meshStatus the mesh-side status string (may be `null`/`undefined`)
 * @returns one of the four A2A v1.0 enumerated states; never `null`
 */
export function fromMesh(meshStatus: string | null | undefined): string {
  if (!meshStatus) {
    return A2A_WORKING;
  }
  switch (meshStatus) {
    case "pending":
      return A2A_SUBMITTED;
    case "working":
    case "running":
      return A2A_WORKING;
    case "completed":
      return A2A_COMPLETED;
    case "failed":
      return A2A_FAILED;
    case "cancelled":
    case "canceled":
      return A2A_CANCELED;
    case "cancelling":
    case "canceling":
      // Still in progress; cancel signal in flight but the job has not
      // yet observed the cancel. Surfaces as `working` so clients keep
      // polling — they'll see `canceled` once the job acknowledges.
      return A2A_WORKING;
    default:
      return A2A_WORKING;
  }
}

/**
 * @returns `true` when the A2A state is one of the three terminal values
 *     (`completed` / `failed` / `canceled`).
 */
export function isTerminal(a2aState: string | null | undefined): boolean {
  return (
    a2aState === A2A_COMPLETED ||
    a2aState === A2A_FAILED ||
    a2aState === A2A_CANCELED
  );
}

/**
 * @returns `true` when the mesh status string represents a terminal state.
 *     Accepts both UK and US `canceled` spellings (the mesh substrate emits
 *     `cancelled` but a normalizer upstream may have already translated).
 */
export function isMeshTerminal(meshStatus: string | null | undefined): boolean {
  if (!meshStatus) return false;
  return (
    meshStatus === "completed" ||
    meshStatus === "failed" ||
    meshStatus === "cancelled" ||
    meshStatus === "canceled"
  );
}

/**
 * Extract the mesh-side status string from a `proxy.status()` payload.
 *
 * Returns `null` when the payload lacks a recognisable status field —
 * callers default to `working` via {@link fromMesh}.
 */
export function meshStatusOf(
  statusPayload: Record<string, unknown> | null | undefined
): string | null {
  if (!statusPayload || typeof statusPayload !== "object") {
    return null;
  }
  const s = (statusPayload as Record<string, unknown>)["status"];
  if (s === null || s === undefined) return null;
  return typeof s === "string" ? s : String(s);
}
