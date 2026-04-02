#!/usr/bin/env npx tsx
/**
 * svc-b - MCP Mesh Agent
 *
 * Chain service B - receives from A, calls C
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SvcB Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "svc-b",
  httpPort: 8080,
});

agent.addTool({
  name: "process_b",
  capability: "process_b",
  description: "Intermediate chain service B",
  tags: ["benchmark", "chain", "intermediate"],
  dependencies: ["process_c"],
  parameters: z.object({
    mode: z.string().default("baseline"),
    payload: z.string().default(""),
    payload_size: z.string().default("1kb"),
  }),
  execute: async (args, process_c: McpMeshTool | null) => {
    if (!process_c) {
      return "degraded: process_c dependency not available";
    }
    return await process_c({ mode: args.mode, payload: args.payload, payload_size: args.payload_size });
  },
});

console.log("svc-b agent defined. Waiting for auto-start...");
