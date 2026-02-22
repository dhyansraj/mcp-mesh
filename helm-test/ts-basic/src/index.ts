#!/usr/bin/env npx tsx
/**
 * ts-basic - MCP Mesh Agent
 *
 * A MCP Mesh agent generated using meshctl scaffold.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsBasic Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-basic",
  httpPort: 8080,
});

// ===== TOOLS =====

agent.addTool({
  name: "hello",
  capability: "hello",
  description: "A sample tool",
  tags: ["tools"],
  parameters: z.object({
    // TODO: Define your input parameters using Zod schemas
    //
    // Example parameter types:
    // name: z.string().describe("User name"),
    // count: z.number().int().default(1).describe("Repeat count"),
    // threshold: z.number().default(0.5).describe("Score threshold"),
    // verbose: z.boolean().optional().describe("Enable verbose output"),
    // mode: z.enum(["fast", "accurate"]).default("fast").describe("Processing mode"),
  }),
  execute: async (args) => {
    // TODO: Implement tool logic
    return "Not implemented";
  },
});

// ===== DEPENDENCY INJECTION EXAMPLE (uncomment and adapt) =====
//
// Declare dependencies to call tools on other agents in the mesh.
// The mesh runtime injects McpMeshTool instances positionally into execute.
//
// agent.addTool({
//   name: "orchestrate",
//   capability: "orchestrate",
//   description: "Calls another agent's tool",
//   tags: ["tools"],
//   dependencies: ["calculator"],           // declare dependency on "calculator" capability
//   parameters: z.object({
//     expression: z.string().describe("Math expression"),
//   }),
//   execute: async (args, calculator: McpMeshTool | null) => {
//     if (!calculator) {
//       return "calculator dependency not available";
//     }
//     const result = await calculator({ expression: args.expression });
//     return `Calculator says: ${result}`;
//   },
// });

console.log("ts-basic agent defined. Waiting for auto-start...");
