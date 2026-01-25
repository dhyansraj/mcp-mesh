#!/usr/bin/env npx tsx
/**
 * ts-auto-port-agent - MCP Mesh Agent
 *
 * TypeScript agent with auto-port assignment for testing
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsAutoPortAgent Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-auto-port-agent",
  httpPort: 9000,  // Default port - will be overridden by MCP_MESH_HTTP_PORT=0
  enableHttp: true,  // Enable HTTP mode
});

// ===== TOOLS =====

agent.addTool({
  name: "echo",
  capability: "echo",
  description: "Echo back the input",
  tags: ["echo", "test", "typescript"],
  parameters: z.object({
    message: z.string().default("test").describe("Message to echo back"),
  }),
  execute: async (args) => {
    return `Echo: ${args.message} at ${new Date().toISOString()}`;
  },
});

console.log("ts-auto-port-agent agent defined. Waiting for auto-start...");
