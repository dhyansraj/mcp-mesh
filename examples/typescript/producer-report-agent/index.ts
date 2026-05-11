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
 * `MeshJobSubmitter` wiring (issue #936)
 * ======================================
 *
 * The framework auto-injects a `MeshJobSubmitter` as the third positional
 * argument of the handler. The submitter is bound to the producer's task
 * capability — derived from the first declared dependency or, when none
 * are declared, from the `skillId` with `-` replaced by `_` (so
 * `"generate-report"` resolves to the `generate_report` task capability).
 * No more hand-construction from `getApiRuntime().getServiceId()` and
 * `MCP_MESH_REGISTRY_URL` — the framework owns this plumbing now.
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
// Validate the parsed value is a finite TCP port — parseInt("abc")
// returns NaN and parseInt("99999") returns an out-of-range value;
// either would break listen() with an opaque error. Fall back to the
// default 9091 and re-export it so the SDK observes the same string.
const DEFAULT_HTTP_PORT = 9091;
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
process.env.MCP_MESH_AGENT_NAME =
  process.env.MCP_MESH_AGENT_NAME ?? "report-a2a-agent";

import express from "express";
import { mesh } from "@mcpmesh/sdk";

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
  async (_deps, payload, jobSubmitter) => {
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

    if (!jobSubmitter) {
      // The framework injects a MeshJobSubmitter bound to the
      // generate_report capability (derived from skillId per issue
      // #936). Null only when the api-runtime hasn't finished
      // initialising; surface a clear error so the client knows to
      // retry rather than hang.
      throw new Error(
        "MeshJobSubmitter not yet available — mesh runtime is still " +
          "initialising. Retry tasks/send shortly."
      );
    }

    const proxy = await jobSubmitter.submit({
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
