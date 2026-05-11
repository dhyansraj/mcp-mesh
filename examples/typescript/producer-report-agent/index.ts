/**
 * TypeScript A2A producer example for LONG-RUNNING tasks (issue #933) —
 * port of `examples/a2a/report_a2a_agent.py` and
 * `examples/java/producer-report-agent`.
 *
 * Exposes a `generate-report` skill via the A2A v1.0 protocol surface,
 * demonstrating long-running task lifecycle:
 *
 * - `tasks/send` returns immediately with `state=working` + a task id
 * - `tasks/get` polls the parked task and returns the current state +
 *   progress
 * - `tasks/cancel` cancels the underlying mesh job mid-flight
 * - `tasks/sendSubscribe` opens an SSE stream of
 *   `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` envelopes per
 *   A2A v1.0
 * - `tasks/resubscribe` re-attaches an SSE stream to an in-flight task
 *
 * The framework introspects the user handler's return value: when it's
 * a `JobProxy` (the type marker imported from `@mcpmesh/sdk`), the A2A
 * surface routes the task lifecycle through `JobProxy.{status, cancel,
 * wait}`. When it's a plain object/string, the surface treats the task
 * as sync (`state=completed` inline).
 *
 * `MeshJobSubmitter` wiring
 * =========================
 *
 * The Java analog autowires `MeshRuntime` to read `registryUrl` and
 * `agentId` for hand-constructing a `MeshJobSubmitter` inside the
 * `@MeshA2A` handler (a framework gap — `@MeshA2A` injects
 * `McpMeshTool` proxies but NOT `MeshJobSubmitter` for `task=true`
 * deps).
 *
 * The TS equivalent is `getApiRuntime().getServiceId()` for the agent
 * id + `process.env.MCP_MESH_REGISTRY_URL` for the registry URL (the
 * same env var the SDK's `resolveConfig("registry_url", ...)` reads).
 * Cheap to construct (no I/O until `.submit(...)` fires) and stateless
 * after construction.
 *
 * Stack
 * =====
 *   1) Registry — `meshctl start --registry-only`
 *   2) Long-task provider (Python) — provides `generate_report`
 *      (`task=true`) on port 9100
 *   3) This TS producer — exposes `generate-report` via A2A on port 9091
 *
 * Run
 * ===
 *   cd examples/typescript/producer-report-agent
 *   npm install
 *   npm start
 *
 *   # submit + poll
 *   TASK_ID=$(curl -s -X POST http://localhost:9091/agents/report \
 *     -H 'Content-Type: application/json' \
 *     -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
 *          "params":{"id":"r1","message":{"role":"user",
 *          "parts":[{"type":"text",
 *          "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}' \
 *     | jq -r '.result.id')
 *
 *   curl -s -X POST http://localhost:9091/agents/report \
 *     -H 'Content-Type: application/json' \
 *     -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tasks/get\",\"params\":{\"id\":\"$TASK_ID\"}}"
 *
 *   # stream via SSE
 *   curl -N -X POST http://localhost:9091/agents/report \
 *     -H 'Accept: text/event-stream' \
 *     -H 'Content-Type: application/json' \
 *     -d '{"jsonrpc":"2.0","id":3,"method":"tasks/sendSubscribe",
 *          "params":{"id":"s1","message":{"role":"user",
 *          "parts":[{"type":"text",
 *          "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}'
 */

// Set MCP_MESH_HTTP_PORT BEFORE importing the SDK so the api-runtime
// picks up the same port we'll bind the Express listener to.
const HTTP_PORT = parseInt(
  (process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9091"),
  10,
);
process.env.MCP_MESH_AGENT_NAME =
  process.env.MCP_MESH_AGENT_NAME ?? "report-a2a-agent";

import express from "express";
import { getApiRuntime, mesh, MeshJobSubmitter } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

mesh.a2a.mount(
  app,
  {
    path: "/agents/report",
    skillId: "generate-report",
    skillName: "Generate Report",
    description: "Generate a long-form report via A2A (task=True streaming)",
    tags: ["reports", "long-running"],
  },
  async (_deps, payload) => {
    // The A2A request message carries the user payload as a text part
    // with JSON-encoded args. Real-world clients can use any parts
    // shape; for this example we parse parts[0].text as JSON.
    let userId = "anon";
    let sections: string[] = ["overview"];
    const parts = (payload?.parts as Array<{ type?: string; text?: string }> | undefined) ?? [];
    if (parts.length > 0 && parts[0]?.type === "text" && parts[0].text) {
      try {
        const args = JSON.parse(parts[0].text) as {
          user_id?: string;
          sections?: string[];
        };
        if (typeof args.user_id === "string" && args.user_id.length > 0) {
          userId = args.user_id;
        }
        if (Array.isArray(args.sections) && args.sections.length > 0) {
          sections = args.sections.map(String);
        }
      } catch {
        // Tolerant: keep defaults on parse failure — the A2A protocol
        // does not mandate any particular payload shape.
      }
    }

    // Construct a MeshJobSubmitter bound to the long-task-provider's
    // generate_report capability. `@MeshA2A`-style auto-wiring of
    // `MeshJobSubmitter` for `task=true` deps inside A2A handlers is
    // not implemented today — the dispatcher only injects
    // `McpMeshTool` proxies. We wire by hand from the api-runtime
    // singleton (same pattern Java's example uses with autowired
    // MeshRuntime).
    //
    // Cheap to construct — no I/O until submit() fires; stateless
    // after construction.
    const agentId = getApiRuntime().getServiceId();
    if (!agentId) {
      throw new Error(
        "api-runtime not yet started — cannot resolve agentId. " +
        "Wait for the first heartbeat before calling tasks/send.",
      );
    }
    const registryUrl =
      process.env.MCP_MESH_REGISTRY_URL ?? "http://localhost:8000";
    const submitter = new MeshJobSubmitter(
      "generate_report",
      agentId,
      registryUrl,
    );

    const proxy = await submitter.submit({
      user_id: userId,
      sections,
    });

    // Returning the JobProxy switches the framework into long-running
    // mode: state=working response, task parked in the A2A task store
    // for tasks/get / tasks/cancel / tasks/sendSubscribe /
    // tasks/resubscribe.
    return proxy;
  },
);

app.listen(HTTP_PORT, () => {
  console.log(`📊 Report A2A Producer (TS) on http://localhost:${HTTP_PORT}`);
  console.log(`    Card:        GET  http://localhost:${HTTP_PORT}/agents/report/.well-known/agent.json`);
  console.log(`    JSON-RPC:    POST http://localhost:${HTTP_PORT}/agents/report`);
  console.log(`    SSE stream:  POST http://localhost:${HTTP_PORT}/agents/report  (method: tasks/sendSubscribe)`);
});
