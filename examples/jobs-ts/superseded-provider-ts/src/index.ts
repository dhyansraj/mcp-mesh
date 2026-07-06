/**
 * Typed supersession signal (issue #1278) — TS Provider: a write authority
 * that fences stale-executor writes.
 *
 * This is the provider half of the calling-job fencing pattern. A state
 * authority (here an in-memory ledger) accepts mutating writes from job
 * executors. When a job is re-claimed after a crash/reclaim, a NEWER executor
 * runs under a HIGHER `claimEpoch`; the OLD executor may still be mid-flight
 * and try to write. Those stale writes must be rejected so the newer executor
 * owns the outcome.
 *
 * Two mesh surfaces make this a few lines:
 *
 *     // 1. Read WHO called me (issue #1263 — the calling job's identity).
 *     const cj = callingJob();          // -> CallingJob | null
 *
 *     // 2. Reject a superseded caller with the TYPED signal (issue #1278).
 *     throw new MeshSupersededError(detail);
 *
 * The framework does NOT auto-detect supersession — the APP decides. The mesh
 * only propagates the calling job's identity and provides the typed error plus
 * its emit/recognize plumbing. Here the "is superseded" rule is deliberately
 * simple and deterministic for teaching: the authority remembers the highest
 * `claimEpoch` it has seen per calling `jobId` and rejects any call whose epoch
 * is lower — i.e. "an older executor is trying to write after a newer one
 * already has".
 *
 * `MeshSupersededError` crosses the wire as the reserved app envelope
 * `{"error":"claim_superseded"}` (plus an optional `"detail"`). The calling
 * side's injected proxy recognizes that envelope and re-throws
 * `MeshSupersededError` — so the CONSUMER unwinds with ONE
 * `if (e instanceof MeshSupersededError)` (see
 * `../superseded-consumer-ts/src/index.ts`) instead of string-matching a
 * marker after every call.
 *
 * Run:
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts
 */
import { FastMCP } from "fastmcp";
import { mesh, callingJob, MeshSupersededError } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Superseded Write Authority (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "superseded-provider-ts",
  httpPort: 9114,
  description:
    "Issue #1278 provider (TS) — write authority that fences superseded " +
    "executors via calling-job epoch + typed MeshSupersededError",
});

// Highest claimEpoch this authority has accepted a write under, per calling
// jobId. This is the APP's supersession state — the framework does not keep
// it. A single-process server touches this from one event loop, so a plain
// Map is safe here; a multi-replica authority would keep it in a shared store.
const latestEpochByJob = new Map<string, number>();

// The in-memory "ledger" we are protecting from stale writes.
const ledger: Array<{ entry: string; byEpoch: number | null }> = [];

agent.addTool({
  name: "apply_write",
  capability: "apply_write",
  description:
    "Apply a mutating write to the ledger, fencing out writes from a " +
    "superseded (older-epoch) executor. Demonstrates calling-job fencing " +
    "with the typed MeshSupersededError.",
  parameters: z.object({
    entry: z.string(),
  }),
  execute: async ({ entry }) => {
    // The mutating payload (`entry`) is an ordinary tool argument. The
    // caller's IDENTITY is NOT in the payload — it rides the propagated
    // headers the mesh seeds on outbound calls made from within a job
    // execution context, and we read it back with callingJob().
    const cj = callingJob();

    // No calling-job identity → a regular (non-job) call, or a caller on an
    // old SDK that does not propagate identity. Nothing to fence against;
    // apply the write. (Fencing is defense-in-depth — soft-fail-open when
    // identity is absent.)
    if (!cj || cj.claimEpoch == null) {
      ledger.push({ entry, byEpoch: null });
      return { applied: true, ledger_size: ledger.length, fenced: false };
    }

    const seen = latestEpochByJob.get(cj.jobId) ?? -1;

    if (cj.claimEpoch < seen) {
      // APP DECISION: a newer executor (epoch `seen`) has already written for
      // this job, so this older executor's write is stale. Reject with the
      // typed signal — this serializes to the reserved
      // {"error":"claim_superseded","detail":...} envelope, and the caller's
      // injected proxy re-throws MeshSupersededError on its side.
      const detail =
        `job ${cj.jobId}: calling epoch ${cj.claimEpoch} < ` +
        `latest accepted epoch ${seen}`;
      throw new MeshSupersededError(detail);
    }

    // Caller is current (>= highest seen). Record its epoch and apply.
    latestEpochByJob.set(cj.jobId, Math.max(seen, cj.claimEpoch));
    ledger.push({ entry, byEpoch: cj.claimEpoch });
    return {
      applied: true,
      ledger_size: ledger.length,
      accepted_epoch: cj.claimEpoch,
      fenced: false,
    };
  },
});

console.log("superseded-provider-ts agent defined. Waiting for auto-start...");
