#!/usr/bin/env npx tsx
/**
 * svc-a - MCP Mesh Agent
 *
 * Entry service - receives request, calls svc-b
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SvcA Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "svc-a",
  httpPort: 8080,
});

agent.addTool({
  name: "call_chain",
  capability: "call_chain",
  description: "Entry point for benchmark chain",
  tags: ["benchmark", "chain", "entry"],
  dependencies: ["process_b"],
  parameters: z.object({
    mode: z.string().default("baseline"),
    payload: z.string().default(""),
    payload_size: z.string().default("1kb"),
  }),
  execute: async (args, process_b: McpMeshTool | null) => {
    if (!process_b) {
      return "degraded: process_b dependency not available";
    }
    return await process_b({ mode: args.mode, payload: args.payload, payload_size: args.payload_size });
  },
});

console.log("svc-a agent defined. Waiting for auto-start...");
