/**
 * TypeScript A2A producer example (issue #933) — port of
 * `examples/a2a/date_a2a_agent.py` and
 * `examples/java/producer-date-agent`.
 *
 * Exposes a `get-date` skill via the A2A v1.0 protocol surface using
 * `mesh.a2a.mount(app, ...)` on a user-owned Express app. The mount
 * helper wires both companion routes the A2A protocol requires:
 *
 *   GET  /agents/date/.well-known/agent.json   (agent card)
 *   POST /agents/date                          (JSON-RPC tasks/* entry)
 *
 * The user owns the Express app AND the http.listen() lifecycle, same
 * shape as `mesh.route(...)` HTTP handlers. The mesh api-runtime
 * pipeline picks up the mounted A2A surface from the
 * `A2AProducerRegistry` and registers the agent with the mesh registry
 * as `agent_type=a2a` (with the `surfaces[]` array populated) on each
 * heartbeat.
 *
 * Sync handler: return value → A2A v1.0 `Task` envelope with
 * `state=completed`; thrown exception → `state=failed`.
 *
 * The mesh dependency on `date_service` demonstrates DDDI inside an
 * A2A handler: at request time the framework resolves the `McpMeshTool`
 * proxy and supplies it under the `deps` argument keyed by capability
 * name — same wiring `mesh.route(...)` uses.
 *
 * Stack
 * =====
 *   1) Registry — `meshctl start --registry-only`
 *   2) System agent (Python) — provides `date_service` on port 9100
 *   3) This TS producer — exposes `get-date` via A2A on port 9090
 *
 * Run
 * ===
 *   cd examples/typescript/producer-date-agent
 *   npm install
 *   npm start
 *
 *   # test the agent card
 *   curl http://localhost:9090/agents/date/.well-known/agent.json | jq
 *
 *   # test the JSON-RPC tasks/send entry
 *   curl -X POST http://localhost:9090/agents/date \
 *        -H 'Content-Type: application/json' \
 *        -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
 *             "params":{"id":"t1","message":{"role":"user",
 *             "parts":[{"type":"text","text":"now"}]}}}'
 */

// Set MCP_MESH_HTTP_PORT BEFORE importing the SDK so the api-runtime
// picks up the same port we'll bind the Express listener to. Without
// this, the agent card's `url` field falls back to the framework
// default instead of the actual Express port.
// Validate the parsed value is a finite TCP port — parseInt("abc")
// returns NaN and parseInt("99999") returns an out-of-range value;
// either would break listen() with an opaque error. Fall back to the
// default 9090 and re-export it so the SDK observes the same string.
const DEFAULT_HTTP_PORT = 9090;
function resolveHttpPort(): number {
  const raw = process.env.MCP_MESH_HTTP_PORT;
  const parsed = raw === undefined ? NaN : parseInt(raw, 10);
  if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 65535) {
    return parsed;
  }
  process.env.MCP_MESH_HTTP_PORT = String(DEFAULT_HTTP_PORT);
  return DEFAULT_HTTP_PORT;
}
const HTTP_PORT = resolveHttpPort();
// MCP_MESH_AGENT_NAME drives the heartbeat envelope's `name` field and
// the agent card's top-level `name`. Default mirrors Python/Java port.
process.env.MCP_MESH_AGENT_NAME = process.env.MCP_MESH_AGENT_NAME ?? "date-a2a-agent";

import express from "express";
import { mesh, type McpMeshTool } from "@mcpmesh/sdk";

const app = express();
// `express.json()` is REQUIRED — the A2A dispatcher reads `req.body`
// to parse the JSON-RPC envelope. Without it `req.body` is `undefined`
// and every request would fall through to a `-32700 Parse error`.
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
    // The framework injects resolved McpMeshTool proxies keyed by
    // capability name — same shape `mesh.route(...)` provides. Until
    // the registry sees a matching provider the value is `null`; we
    // emit a local fallback so the example stays runnable solo
    // (matches Python/Java's defer-resolution behavior).
    const dateService = deps.date_service as McpMeshTool | null;
    if (dateService === null) {
      return {
        date: new Date().toISOString(),
        note: "date_service not yet resolved — returning local fallback",
      };
    }
    const result = await dateService.call({});
    return { date: result };
  },
);

app.listen(HTTP_PORT, () => {
  console.log(`🌐 Date A2A Producer (TS) on http://localhost:${HTTP_PORT}`);
  console.log(`    Card:     GET  http://localhost:${HTTP_PORT}/agents/date/.well-known/agent.json`);
  console.log(`    JSON-RPC: POST http://localhost:${HTTP_PORT}/agents/date`);
});
