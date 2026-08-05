#!/usr/bin/env npx tsx
/**
 * ts-hc-provider-b — the survivor (issue #1480).
 *
 * Second provider of `hc_probe_ts`. Deliberately has NO `healthCheck`: it is
 * the control. It must keep heartbeating throughout, so a run where BOTH
 * providers go unhealthy (dead registry, stalled sweep, container-wide
 * stall) is distinguishable from a genuine withdrawal of A.
 *
 * Loses the resolver tiebreak to A while A is healthy — equal tag score,
 * equal version, then agent ID ASC, and `hc-provider-a-ts-<uuid>` sorts
 * before `hc-provider-b-ts-<uuid>`. So the consumer deterministically starts
 * on A and any answer naming B is a real re-resolution.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const AGENT_NAME = "hc-provider-b-ts";

const server = new FastMCP({
  name: "HC Provider B (typescript)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: AGENT_NAME,
  version: "1.0.0",
  description: "Survivor provider that the consumer fails over to (#1480)",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "3422"),
});

agent.addTool({
  name: "probe_b",
  capability: "hc_probe_ts",
  description: "Report which provider instance served this call",
  tags: ["hc-withdrawal"],
  parameters: z.object({}),
  execute: async () =>
    JSON.stringify({ served_by: AGENT_NAME, pid: process.pid }),
});

console.log(`${AGENT_NAME} defined. Waiting for auto-start...`);
