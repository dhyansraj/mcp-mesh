#!/usr/bin/env npx tsx
/**
 * ts-hc-consumer — reports which provider the mesh routed it to (#1480).
 *
 * `who_served` injects `hc_probe_ts` positionally and returns the provider's
 * payload verbatim. Started ONCE and never restarted, so the only way its
 * answer can move from provider A to provider B and back is a genuine
 * re-resolution — the withdrawal / recovery chain under test.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "HC Consumer (typescript)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "hc-consumer-ts",
  version: "1.0.0",
  description: "Consumer that must fail over when provider A withdraws (#1480)",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "3423"),
});

agent.addTool({
  name: "who_served",
  capability: "who_served_ts",
  description: "Call hc_probe_ts and report which provider answered",
  tags: ["hc-withdrawal"],
  dependencies: ["hc_probe_ts"],
  parameters: z.object({}),
  execute: async (
    _args,
    probe: McpMeshTool | null = null, // positional: dependencies[0]
  ) => {
    if (!probe) {
      return JSON.stringify({ error: "hc_probe_ts dependency not injected" });
    }
    return JSON.stringify(await probe({}));
  },
});

console.log("hc-consumer-ts defined. Waiting for auto-start...");
