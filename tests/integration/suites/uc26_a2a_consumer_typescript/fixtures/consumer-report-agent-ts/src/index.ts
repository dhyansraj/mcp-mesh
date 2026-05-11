/**
 * uc26 TS A2A consumer (long-running polling bridge) — bridges
 * report_a2a_agent.py generate-report onto the mesh as the `report`
 * capability so the existing Python caller-agent-report fixture can
 * drive it without re-wiring.
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
  name: "Report Consumer Bridge (TS, polling, uc26)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "report-consumer",
  httpPort: HTTP_PORT,
  description:
    "uc26 TS A2A consumer (polling) — bridges report_a2a_agent.py generate-report as `report`.",
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
  `consumer-report-agent-ts (uc26, polling bridge) defined on port ${HTTP_PORT}.`,
);
