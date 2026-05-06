/**
 * MeshJob Phase 1 — TypeScript Consumer Example: commission a remote long-running job.
 *
 * Demonstrates the consumer-side dispatch surface:
 *
 *     agent.addTool({
 *       name: "commission_report",
 *       capability: "commission_report",
 *       dependencies: [{ capability: "generate_report" }],
 *       meshJobDepIndex: 0,        // dep[0] is task=true
 *       parameters: z.object({ ... }),
 *       execute: async (
 *         { user_id, sections },
 *         generateReport: MeshJob | null = null,
 *       ) => {
 *         const proxy = await generateReport!.submit({ ... });
 *         return await proxy.wait(60);
 *       },
 *     });
 *
 * The DI layer sees `meshJobDepIndex: 0` and injects a
 * `MeshJobSubmitter` (instead of a regular `McpMeshTool` proxy) at
 * dep slot 0. `submit(...)` posts to `POST /jobs` on the registry and
 * returns a `JobProxy` bound to the new job id; `wait(...)` polls
 * `GET /jobs/{id}` until the status is terminal.
 *
 * Run after the provider is up:
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx index.ts
 */
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Long Task Consumer (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-consumer-ts",
  httpPort: 9111,
  description:
    "MeshJob Phase 1 consumer (TS) — commissions and awaits remote reports",
});

agent.addTool({
  name: "commission_report",
  capability: "commission_report",
  dependencies: [{ capability: "generate_report" }],
  // Replace dep[0]'s slot with a MeshJobSubmitter.
  meshJobDepIndex: 0,
  description:
    "Commission a report from the long-task provider and await its " +
    "result. Demonstrates the submit-and-wait pattern.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async (
    { user_id, sections },
    generateReport: MeshJob | null = null,
  ) => {
    if (!generateReport || !generateReport.submit) {
      return {
        error:
          "generate_report submitter not injected — check that the " +
          "long-task-provider-ts is registered with task=true",
      };
    }
    // submit() posts to /jobs and returns a JobProxy bound to the new
    // job id. maxDuration is the per-attempt soft timeout the provider
    // runtime enforces.
    const proxy = await generateReport.submit(
      { user_id, sections },
      { maxDuration: 60 },
    );
    if (!proxy.wait) {
      return { error: "submitter returned a proxy without .wait()" };
    }
    // Poll the registry until terminal. Returns the producer's
    // complete() payload on success; rejects on failure / cancel /
    // timeout.
    return await proxy.wait(60);
  },
});
