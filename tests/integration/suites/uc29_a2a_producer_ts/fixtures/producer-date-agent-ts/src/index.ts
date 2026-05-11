/**
 * uc29_a2a_producer_ts fixture (issue #933 Chunk 1C-integration) — TS
 * A2A producer mirroring date_a2a_agent.py and
 * tests/integration/suites/uc28_a2a_producer_java's Java fixture.
 *
 * Same path (/agents/date), same skill id (get-date), same artifact
 * shape ({"date": "<value>"} JSON-stringified into parts[0].text) so
 * the existing Python consumer (consumer_date_agent.py) is wire-
 * compatible without modification.
 *
 * Listens on port 9090. Card at
 * GET /agents/date/.well-known/agent.json; JSON-RPC entry at
 * POST /agents/date. Depends on the date_service mesh capability
 * (provided by examples/simple/system_agent.py on port 9100).
 */
const HTTP_PORT = parseInt(
  (process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9090"),
  10,
);
process.env.MCP_MESH_AGENT_NAME = process.env.MCP_MESH_AGENT_NAME ?? "date-a2a-agent";

import express from "express";
import { mesh, type McpMeshTool } from "@mcpmesh/sdk";

const app = express();
// express.json() is REQUIRED — the A2A dispatcher reads req.body to
// parse JSON-RPC envelopes. Without it req.body is undefined and every
// request falls through to a -32700 Parse error.
app.use(express.json());

mesh.a2a.mount(
  app,
  {
    path: "/agents/date",
    skillId: "get-date",
    skillName: "Get Date",
    description: "Get current date/time via A2A protocol",
    tags: ["system", "date"],
    dependencies: ["date_service"],
  },
  async (deps, _payload) => {
    const dateService = deps.date_service as McpMeshTool | null;
    if (dateService === null) {
      // Defer-resolution sentinel: keeps the fixture runnable solo and
      // mirrors the Python/Java producer fallback path.
      return {
        date: new Date().toISOString(),
        note: "date_service not yet resolved",
      };
    }
    const result = await dateService.call({});
    return { date: result };
  },
);

app.listen(HTTP_PORT, () => {
  console.log(`Date A2A Producer (TS, uc29) on port ${HTTP_PORT}`);
});
