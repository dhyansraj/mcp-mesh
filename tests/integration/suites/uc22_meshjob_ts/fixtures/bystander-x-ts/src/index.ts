/**
 * Bystander X (uc22 TS) — used by tc16 to verify third-party status reads.
 *
 * Has no MeshJob deps and no task=true tools. The framework still
 * auto-registers `__mesh_job_status` / `__mesh_job_result` /
 * `__mesh_job_cancel` on every mesh agent, so the test can read job
 * state from this agent for a job_id it did not submit.
 *
 * Distinct fixture file (separate from bystander-y-ts) so meshctl's
 * "is this agent already running" check (which keys off the
 * `mesh(server, { name })` decorator) doesn't conflate the two
 * instances.
 */
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = (() => {
  const parsed = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "", 10);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535
    ? parsed
    : 9114;
})();

const server = new FastMCP({
  name: "Bystander X (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "bystander-x-ts",
  httpPort: HTTP_PORT,
  description: "Bystander agent X (TS) — verifies third-party status reads (tc16).",
});

agent.addTool({
  name: "bystander_x_ping",
  capability: "bystander_x_ping",
  description: "Trivial tool — keeps bystander X alive in the registry.",
  parameters: z.object({}),
  execute: async () => ({ ok: true, agent: "bystander-x-ts" }),
});

console.log(
  `bystander-x-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
