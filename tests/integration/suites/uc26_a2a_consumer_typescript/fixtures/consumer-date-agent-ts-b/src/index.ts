/**
 * uc26 TS consumer (alt) — second bridge over the same date_a2a_agent
 * producer at localhost:9090, but registered under
 * `date-consumer-ts-alt` so the auto-injected consumer-name tag (via
 * `a2aConfig`) distinguishes it from `date-consumer-ts` for failover
 * (tc03).
 */
import { FastMCP, mesh, type A2AClient } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9202", 10);

const server = new FastMCP({
  name: "Date Consumer Bridge (TS alt, uc26)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "date-consumer-alt",
  httpPort: HTTP_PORT,
  description:
    "uc26 TS A2A consumer (alt) — second bridge for failover tests.",
});

agent.addTool({
  name: "current_date",
  capability: "current-date",
  tags: ["a2a-bridge"],
  description: "Bridge upstream A2A get-date skill onto the mesh (alt).",
  parameters: z.object({}),
  a2aConfig: {
    url: "http://localhost:9090/agents/date",
    skillId: "get-date",
  },
  execute: async (_args, ..._injected) => {
    const a2a = _injected[_injected.length - 1] as A2AClient | null;
    if (!a2a) {
      throw new Error("A2AClient was not injected — did you set a2aConfig?");
    }
    const r = await a2a.send({
      role: "user",
      parts: [{ type: "text", text: "now" }],
    });
    if (!r.artifactText) return "";
    try {
      return JSON.parse(r.artifactText);
    } catch {
      return r.artifactText;
    }
  },
});

console.log(
  `consumer-date-agent-ts-alt (uc26) defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
