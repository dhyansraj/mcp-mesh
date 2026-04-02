#!/usr/bin/env npx tsx
/**
 * svc-d - MCP Mesh Agent
 *
 * Chain service D - receives from C, calls E
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SvcD Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "svc-d",
  httpPort: 8080,
});

agent.addTool({
  name: "process_d",
  capability: "process_d",
  description: "Intermediate chain service D",
  tags: ["benchmark", "chain", "intermediate"],
  dependencies: ["generate_response"],
  parameters: z.object({
    mode: z.string().default("baseline"),
    payload: z.string().default(""),
    payload_size: z.string().default("1kb"),
  }),
  execute: async (args, generate_response: McpMeshTool | null) => {
    if (!generate_response) {
      return "degraded: generate_response dependency not available";
    }
    return await generate_response({ mode: args.mode, payload: args.payload, payload_size: args.payload_size });
  },
});

console.log("svc-d agent defined. Waiting for auto-start...");
