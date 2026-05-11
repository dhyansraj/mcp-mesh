/**
 * uc26 TS A2A consumer (SSE bridge) — bridges report_a2a_agent.py
 * generate-report via the A2A tasks/sendSubscribe SSE stream as the
 * mesh `report_sse` capability. Underscore form matches the existing
 * caller-agent-report Python fixture so the test driver doesn't need
 * to be re-wired.
 */
import {
  FastMCP,
  mesh,
  type A2AClient,
  type MeshJob,
  type JobController,
} from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9212", 10);

const server = new FastMCP({
  name: "Report Consumer Bridge (TS, SSE, uc26)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "report-consumer-sse",
  httpPort: HTTP_PORT,
  description:
    "uc26 TS A2A consumer (SSE) — bridges generate-report via the A2A SSE stream as `report_sse`.",
});

agent.addTool({
  name: "report_sse",
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
  `consumer-report-agent-ts-sse (uc26) defined on port ${HTTP_PORT}.`,
);
