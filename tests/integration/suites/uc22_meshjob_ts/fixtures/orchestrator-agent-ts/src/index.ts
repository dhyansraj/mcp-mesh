/**
 * Orchestrator agent (uc22 TS) — TS port of orchestrator-agent.
 *
 * Has NO task=true tools and NO mesh deps. Used by tc14 to prove the
 * three framework helper tools (`__mesh_job_status` /
 * `__mesh_job_result` / `__mesh_job_cancel`) auto-register on every TS
 * mesh agent regardless of whether that agent participates in the job
 * lifecycle. Also reused by tc15 + tc19 (cross-runtime status read).
 */
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9113", 10);

const server = new FastMCP({
  name: "Orchestrator (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "orchestrator-agent-ts",
  httpPort: HTTP_PORT,
  description:
    "Agent with no task tools and no mesh deps — verifies helper-tool auto-registration is universal (TS).",
});

agent.addTool({
  name: "orchestrator_ping",
  capability: "orchestrator_ping",
  description:
    "Trivial tool — only purpose is to keep the agent alive in the registry.",
  parameters: z.object({}),
  execute: async () => {
    return { ok: true, agent: "orchestrator-agent-ts" };
  },
});

console.log(
  `orchestrator-agent-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
