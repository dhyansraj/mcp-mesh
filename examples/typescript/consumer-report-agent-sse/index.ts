/**
 * TypeScript A2A consumer example (SSE) — port of
 * `examples/a2a/consumer_report_agent_sse.py` and
 * `examples/java/consumer-report-agent-sse`.
 *
 * Same end-to-end shape as the polling sibling but uses
 * `A2AClient.subscribe` (SSE) instead of poll-based submit + bridge.
 * Validates the `A2AStream` async iterator + `A2AStream.bridge()`
 * helper end-to-end.
 *
 * Cancel propagation note
 * =======================
 *
 * Per A2A v1.0, client disconnect is a transient signal — the
 * producer continues running unless explicitly canceled.
 * `A2AStream.bridge` therefore does NOT POST `tasks/cancel` upstream
 * when the mesh-side job is cancelled (it just closes the SSE
 * connection). Users who need cancel propagation should use the
 * polling `consumer-report-agent` (which races
 * `awaitJobCancel(jobId)` against the polling sleep and POSTs
 * `tasks/cancel`).
 *
 * Stack same as the polling variant — uses port 9212 to coexist.
 *
 * Run
 * ===
 *   cd examples/typescript/consumer-report-agent-sse
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

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9212", 10);

const server = new FastMCP({
  name: "Report Consumer Bridge (TS, SSE)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "report-consumer-sse-ts",
  httpPort: HTTP_PORT,
  description:
    "TypeScript A2A consumer (SSE) — bridges generate-report via the A2A SSE stream as the mesh `report_sse` capability.",
});

agent.addTool({
  name: "report_sse",
  // Underscore form (`report_sse`) matches the existing Python
  // caller-agent-report fixture's `report_sse` dependency name —
  // makes the TS example a drop-in replacement for the Python
  // `consumer_report_agent_sse.py` without re-wiring downstream callers.
  capability: "report_sse",
  task: true,
  tags: ["a2a-bridge", "sse"],
  description:
    "Bridge upstream A2A generate-report skill via SSE as a mesh `report_sse` capability.",
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
    // Sync tools/call fallback — drain the stream and surface the
    // first artifact's parsed payload (or the raw text).
    if (!job || typeof (job as JobController).updateProgress !== "function") {
      const stream = await a2a.subscribe(message);
      try {
        for await (const event of stream) {
          if (event.kind === "artifact" && event.artifactText) {
            try {
              return JSON.parse(event.artifactText);
            } catch {
              return event.artifactText;
            }
          }
        }
      } finally {
        await stream.aclose();
      }
      return "";
    }
    const stream = await a2a.subscribe(message);
    return await stream.bridge(job as JobController);
  },
});

console.log(
  `report-consumer-sse-ts (SSE bridge) defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
