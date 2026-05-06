/**
 * MeshJob Phase 1 — TypeScript Provider Example: long-running report generator.
 *
 * Demonstrates the producer-side dispatch surface in TS:
 *
 *     agent.addTool({
 *       name: "generate_report",
 *       capability: "generate_report",
 *       task: true,
 *       meshJobParamIndex: 1,            // job lands at sig pos 1 (after `args`)
 *       parameters: z.object({ ... }),
 *       execute: async ({ user_id, sections }, job: MeshJob | null = null) => {
 *         await job?.updateProgress(...);
 *         await job?.complete({ ... });
 *       },
 *     });
 *
 * When invoked via the consumer's `MeshJobSubmitter.submit(...)` (see
 * `../long-task-consumer-ts/index.ts`), the dispatcher claims the job
 * from the registry, builds a `JobController` bound to the claimed
 * id, and injects it at `meshJobParamIndex`. Progress updates and the
 * terminal `complete()` flush directly to the registry — the
 * consumer's `await proxy.wait(...)` polls until terminal.
 *
 * If you call `generate_report` synchronously (regular `tools/call`,
 * no `X-Mesh-Job-Id` header), the runtime injects `null` for `job`
 * per `MESHJOB_DDDI_CONTRACT.md` — the function then runs the fast
 * path and returns its result.
 *
 * Run:
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx index.ts
 */
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Long Task Provider (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-provider-ts",
  httpPort: 9110,
  description:
    "MeshJob Phase 1 producer (TS) — generates reports as long-running jobs",
});

agent.addTool({
  name: "generate_report",
  capability: "generate_report",
  task: true,
  // Signature position 1: position 0 is `args`, the MeshJob lands at 1.
  meshJobParamIndex: 1,
  description:
    "Long-running report generator. Demonstrates progress updates and " +
    "structured terminal results.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async ({ user_id, sections }, job: MeshJob | null = null) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.0, "starting");
    }
    const results: { section: string; content: string }[] = [];
    const total = Math.max(sections.length, 1);
    for (let i = 0; i < sections.length; i++) {
      // Simulate substantive work — in a real producer this might be
      // an LLM call, a long DB query, or video transcoding.
      await new Promise((r) => setTimeout(r, 2000));
      results.push({
        section: sections[i],
        content: `Generated content for ${sections[i]}`,
      });
      if (job?.updateProgress) {
        await job.updateProgress(
          (i + 1) / total,
          `finished section ${i + 1}/${total}`,
        );
      }
    }
    const payload = { user_id, report: results };
    if (job?.complete) {
      // Explicit terminal — flushes immediately so the consumer sees
      // status=completed without waiting on the next batch tick.
      await job.complete(payload);
    }
    return payload;
  },
});
