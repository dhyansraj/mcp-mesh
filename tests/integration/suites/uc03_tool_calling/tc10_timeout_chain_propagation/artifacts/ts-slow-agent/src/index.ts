#!/usr/bin/env npx tsx
/**
 * ts-slow-agent - Sleeps 70s then calls Java agent.
 *
 * Middle link in the timeout chain propagation test: py -> ts -> java.
 * Each hop sleeps 70s; without X-Mesh-Timeout propagation the default
 * 60s proxy timeout would kill the chain.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Slow TypeScript Agent", version: "1.0.0" });
const agent = mesh(server, { name: "ts-slow-agent", httpPort: 0 });

agent.addTool({
  name: "slow_chain_ts",
  capability: "slow_ts",
  description: "Sleeps 70s then calls the Java agent",
  dependencies: ["slow_java"],
  parameters: z.object({
    message: z.string(),
  }),
  execute: async (args, slow_java_svc: McpMeshTool | null) => {
    await new Promise((resolve) => setTimeout(resolve, 70000));
    if (slow_java_svc) {
      const result = await slow_java_svc({ message: `${args.message} -> ts` });
      return { chain: `ts -> ${result.chain || "?"}`, data: result.data || "" };
    }
    return { chain: "ts (no java)", data: "chain broken" };
  },
});
