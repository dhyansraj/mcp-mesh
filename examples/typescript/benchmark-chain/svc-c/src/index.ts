#!/usr/bin/env npx tsx
/**
 * svc-c - MCP Mesh Agent
 *
 * Chain service C - receives from B, calls D
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SvcC Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "svc-c",
  httpPort: 8080,
});

agent.addTool({
  name: "process_c",
  capability: "process_c",
  description: "Intermediate chain service C",
  tags: ["benchmark", "chain", "intermediate"],
  dependencies: ["process_d"],
  parameters: z.object({
    mode: z.string().default("baseline"),
    payload: z.string().default(""),
    payload_size: z.string().default("1kb"),
  }),
  execute: async (args, process_d: McpMeshTool | null) => {
    if (!process_d) {
      return "degraded: process_d dependency not available";
    }
    return await process_d({ mode: args.mode, payload: args.payload, payload_size: args.payload_size });
  },
});

console.log("svc-c agent defined. Waiting for auto-start...");
