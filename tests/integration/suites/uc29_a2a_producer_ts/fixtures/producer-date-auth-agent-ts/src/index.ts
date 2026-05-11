/**
 * uc29_a2a_producer_ts fixture (bearer auth) — TS A2A producer with
 * mesh.a2a.mount(..., auth: "bearer") so the JSON-RPC entry rejects
 * requests without an Authorization: Bearer <token> header.
 *
 * Listens on port 9092 to coexist with the non-auth fixtures.
 *
 * The handler is dependency-free so the test doesn't need a sibling
 * provider — solo agent + registry are enough.
 */
const HTTP_PORT = parseInt(
  (process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9092"),
  10,
);
process.env.MCP_MESH_AGENT_NAME =
  process.env.MCP_MESH_AGENT_NAME ?? "date-auth-agent";

import express from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

mesh.a2a.mount(
  app,
  {
    path: "/agents/date",
    skillId: "get-date",
    skillName: "Get Date (auth)",
    description: "Get current date via bearer-protected A2A surface",
    tags: ["system", "date", "auth"],
    auth: "bearer",
  },
  async (_deps, _payload) => {
    return { date: new Date().toISOString() };
  },
);

app.listen(HTTP_PORT, () => {
  console.log(`Date A2A Producer (TS, uc29, auth=bearer) on port ${HTTP_PORT}`);
});
