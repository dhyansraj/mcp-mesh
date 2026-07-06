/**
 * Typed supersession signal (issue #1278) — TS Consumer: a job executor whose
 * mutating writes unwind with ONE `instanceof MeshSupersededError`.
 *
 * This is the consumer half of the fencing pattern. `run_writer` is a
 * `task: true` handler — it executes AS a job, so it runs under a `claimEpoch`.
 * Every outbound mesh call it makes (here to the provider's `apply_write`)
 * automatically carries this job's identity on the propagated headers, so the
 * provider can fence it via `callingJob()` without the executor threading
 * `jobId` / `claimEpoch` through each payload.
 *
 * The point of #1278 is the UNWIND. A job executor makes many mutating
 * downstream calls; if this executor has been superseded (a newer claim of the
 * same job is now authoritative) it must stop and bail — cleanly, from wherever
 * it is in the batch. Because a superseded write re-throws the TYPED
 * `MeshSupersededError`, the whole batch is wrapped in ONE `catch`:
 *
 *     try {
 *       for (const entry of entries) {
 *         await applyWrite({ entry });        // any of these may be fenced
 *       }
 *     } catch (e) {
 *       if (e instanceof MeshSupersededError) {
 *         return { status: "superseded", detail: e.detail };   // one unwind
 *       }
 *       throw e;
 *     }
 *
 * Contrast the OLD pattern this REPLACES — inspecting every call's result and
 * string-matching the marker after each one:
 *
 *     for (const entry of entries) {
 *       const result = await applyWrite({ entry });
 *       // brittle: re-check the shape/marker on EVERY call site
 *       if (result?.error === "claim_superseded") return { status: "superseded" };
 *     }
 *
 * Note this is DISTINCT from `dependency_unavailable` (issue #1273): that says
 * "the capability isn't reachable"; supersession says "you personally are
 * stale, a newer you is authoritative". Both are typed so the CONTRACT (the
 * reserved envelope), not the error string, drives classification.
 *
 * Run after the provider is up:
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts
 */
import { FastMCP } from "fastmcp";
import {
  mesh,
  type MeshJob,
  type McpMeshTool,
  MeshSupersededError,
} from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Superseded Writer Job (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "superseded-consumer-ts",
  httpPort: 9115,
  description:
    "Issue #1278 consumer (TS) — a task=true writer job that unwinds mutating " +
    "writes with one instanceof MeshSupersededError",
});

agent.addTool({
  name: "run_writer",
  capability: "run_writer",
  // task: true — this handler is dispatched AS a job (claimed from the
  // registry), so it runs under a claimEpoch that the mesh stamps onto the
  // calling-job headers of the applyWrite call below.
  task: true,
  // Regular McpMeshTool dependency on the provider's mutating capability.
  // (A dependency, NOT a MeshJob submitter — apply_write is a plain tool.)
  dependencies: [{ capability: "apply_write" }],
  // Injection order: pos 0 is `args`, dep[0] (applyWrite) lands at pos 1, and
  // the MeshJob controller is spliced at meshJobParamIndex 2. So the execute
  // signature is (args, applyWrite, job).
  meshJobParamIndex: 2,
  description:
    "Run a batch of ledger writes as a job. If this executor is superseded " +
    "mid-batch, unwind cleanly with one instanceof MeshSupersededError.",
  parameters: z.object({
    count: z.number().int().default(3),
  }),
  execute: async (
    { count },
    applyWrite: McpMeshTool | null = null,
    _job: MeshJob | null = null,
  ) => {
    if (!applyWrite) {
      return {
        error:
          "apply_write not injected — check that the superseded-provider-ts " +
          "is registered",
      };
    }

    const written: string[] = [];
    try {
      for (let i = 0; i < count; i++) {
        const entry = `line-${i}`;
        // Any of these calls may be fenced by the provider. If this executor
        // has been superseded, the provider throws MeshSupersededError; the
        // injected proxy recognizes the reserved envelope and re-throws
        // MeshSupersededError here — so we do NOT inspect each result for a
        // marker.
        await applyWrite({ entry });
        written.push(entry);
      }
    } catch (e) {
      if (e instanceof MeshSupersededError) {
        // ONE unwind for the whole batch. A newer claim of this job is
        // authoritative — stop writing and hand back what we managed before
        // being fenced. No rollback needed: the provider already rejected the
        // stale write, so the ledger reflects only the authoritative executor.
        return {
          status: "superseded",
          written_before_fence: written,
          detail: e.detail,
        };
      }
      throw e;
    }

    return { status: "completed", written };
  },
});

console.log("superseded-consumer-ts agent defined. Waiting for auto-start...");
