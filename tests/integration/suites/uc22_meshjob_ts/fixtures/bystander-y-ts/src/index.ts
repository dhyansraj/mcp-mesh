/**
 * Bystander Y (uc22 TS) — used by tc16 to verify third-party status reads.
 *
 * Mirror of bystander-x-ts in every way except agent name; deployed
 * alongside X so the test can prove BOTH agents (each with no involvement
 * in the job) can read its state via the framework's helper tools.
 */
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9115", 10);

const server = new FastMCP({
  name: "Bystander Y (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "bystander-y-ts",
  httpPort: HTTP_PORT,
  description: "Bystander agent Y (TS) — verifies third-party status reads (tc16).",
});

agent.addTool({
  name: "bystander_y_ping",
  capability: "bystander_y_ping",
  description: "Trivial tool — keeps bystander Y alive in the registry.",
  parameters: z.object({}),
  execute: async () => ({ ok: true, agent: "bystander-y-ts" }),
});

console.log(
  `bystander-y-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
