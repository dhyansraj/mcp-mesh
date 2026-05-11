/**
 * TypeScript A2A consumer example (long-running) — port of
 * `examples/a2a/consumer_report_agent.py` and
 * `examples/java/consumer-report-agent`.
 *
 * Bridges the existing `examples/a2a/report_a2a_agent.py`
 * `generate-report` skill onto the mesh as a long-running `report`
 * capability that downstream callers consume via the standard
 * MeshJob interface — they have no idea the actual work is happening
 * on an external A2A backend.
 *
 * Bridging pattern
 * ================
 *
 * The `task: true` body issues a non-blocking `A2AClient.submit`
 * against the upstream A2A surface, then hands the returned
 * `A2AJob` to `bridge(job)` which polls the A2A backend, mirrors
 * progress into the framework-injected `JobController`, and returns
 * the final artifact value (the producer's report payload). The mesh
 * `task: true` wrapper takes that return and calls
 * `controller.complete(...)` itself.
 *
 * Cancel semantics
 * ================
 *
 * `A2AJob.bridge` races each iteration's sleep against
 * `awaitJobCancel(jobId)` so a mesh-side cancel arriving DURING a
 * sleep wakes the bridge immediately. On detection it POSTs
 * `tasks/cancel` upstream so the A2A producer stops billing for the
 * work, then throws `A2AJobCanceledError`.
 *
 * Stack
 * =====
 *   1) Registry — `meshctl start --registry-only`
 *   2) Long-task provider (Python) — produces the report
 *   3) Report A2A surface (Python) — exposes generate-report via A2A
 *   4) This TS consumer — bridges A2A back into the mesh as
 *      `report` (port 9211)
 *
 * Run
 * ===
 *   cd examples/typescript/consumer-report-agent
 *   npm install
 *   npx tsx index.ts
 */
import {
  FastMCP,
  mesh,
  type A2AClient,
  type MeshJob,
  JobController,
} from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9211", 10);

const server = new FastMCP({
  name: "Report Consumer Bridge (TS, polling)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "report-consumer-ts",
  httpPort: HTTP_PORT,
  description:
    "TypeScript A2A consumer (long-running) — bridges the report_a2a_agent.py generate-report skill as a mesh `report` capability.",
});

agent.addTool({
  name: "report",
  capability: "report",
  task: true,
  tags: ["a2a-bridge"],
  description:
    "Bridge upstream A2A generate-report skill onto the mesh as a long-running `report` capability.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  meshJobParamIndex: 1,
  a2aConfig: {
    url: "http://localhost:9091/agents/report",
    skillId: "generate-report",
  },
  execute: async ({ user_id, sections }, ..._injected) => {
    // Positional layout (set by the framework):
    //   _injected[0] = JobController | null   (from meshJobParamIndex)
    //   _injected[1] = A2AClient              (from a2aConfig)
    const job = _injected[0] as MeshJob | null;
    const a2a = _injected[1] as A2AClient;
    const message = {
      role: "user",
      parts: [
        {
          type: "text",
          text: JSON.stringify({ user_id, sections }),
        },
      ],
    };
    // When invoked as a synchronous tools/call (no X-Mesh-Job-Id), no
    // controller arrives — fall back to a simple sync send + parse.
    if (!job || typeof (job as JobController).updateProgress !== "function") {
      const r = await a2a.send(message);
      if (!r.artifactText) return r.artifactText;
      try {
        return JSON.parse(r.artifactText);
      } catch {
        return r.artifactText;
      }
    }
    const a2aJob = await a2a.submit(message);
    return await a2aJob.bridge(job as JobController);
  },
});

console.log(
  `report-consumer-ts (polling bridge) defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
