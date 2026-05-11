/**
 * uc26_a2a_consumer_typescript fixture (issue #917) — bridges the
 * existing date_a2a_agent.py producer's get-date skill onto the mesh
 * as a current-date capability.
 *
 * All test agents share the tsuite container's network namespace, so
 * the upstream A2A endpoint is reachable on localhost:9090 (NOT a
 * docker service name).
 */
import { FastMCP, mesh, type A2AClient } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9201", 10);

const server = new FastMCP({
  name: "Date Consumer Bridge (TS, uc26)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "date-consumer",
  httpPort: HTTP_PORT,
  description:
    "uc26 TS A2A consumer fixture — bridges date_a2a_agent.py get-date as current-date.",
});

agent.addTool({
  name: "current_date",
  capability: "current-date",
  tags: ["a2a-bridge"],
  description: "Bridge upstream A2A get-date skill onto the mesh.",
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
  `consumer-date-agent-ts (uc26) defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
