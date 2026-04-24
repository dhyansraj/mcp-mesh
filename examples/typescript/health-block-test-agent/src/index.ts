/**
 * health-block-test-agent (TypeScript)
 *
 * Reproducer for the TS-runtime equivalent of the Python health-block bug:
 * Express health endpoints (/health, /ready) and the FastMCP HTTP handler
 * share Node's single event loop. A tool that blocks the loop should stall
 * health probes for as long as it runs.
 */

import { execSync } from "node:child_process";
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Health Block Test Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "health-block-test-agent",
  httpPort: 9098,
  description: "Reproducer for /health and /ready blocking during long tool calls",
});

agent.addTool({
  name: "busyTool",
  capability: "busy_tool",
  tags: ["test", "blocking"],
  description: "Blocks the Node event loop via execSync('sleep N')",
  parameters: z.object({
    seconds: z.number().int().default(35).describe("Seconds to block the loop"),
  }),
  execute: async ({ seconds }) => {
    execSync(`sleep ${seconds}`);
    return `slept ${seconds}s (blocking)`;
  },
});

agent.addTool({
  name: "quickTool",
  capability: "quick_tool",
  tags: ["test", "quick"],
  description: "Returns immediately — sanity check that MCP endpoint works",
  parameters: z.object({}),
  execute: async () => "ok",
});

console.log("health-block-test-agent defined. Waiting for auto-start...");
