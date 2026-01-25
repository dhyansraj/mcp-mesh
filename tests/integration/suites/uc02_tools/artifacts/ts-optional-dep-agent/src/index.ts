#!/usr/bin/env npx tsx
/**
 * ts-optional-dep-agent - MCP Mesh Agent
 *
 * Agent with optional dependency that handles unavailable tools gracefully
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsOptionalDepAgent Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-optional-dep-agent",
  httpPort: 9023,
});

// ===== TOOLS =====

agent.addTool({
  name: "smart_add",
  capability: "smart_math",
  description: "Add numbers, using calc_add tool if available",
  tags: ["math", "smart"],
  dependencies: ["calc_add"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async (
    { a, b },
    calc_add: McpMeshTool | null = null  // Positional: dependencies[0]
  ) => {
    if (calc_add) {
      try {
        const result = await calc_add({ a, b });
        return `Calculator result: ${result}`;
      } catch (e: any) {
        return `Calculator failed (${e.message}), local result: ${a + b}`;
      }
    } else {
      return `Local result (no calculator): ${a + b}`;
    }
  },
});

agent.addTool({
  name: "check_calculator",
  capability: "smart_math",
  description: "Check if calc_add tool is available",
  tags: ["math", "status"],
  dependencies: ["calc_add"],
  parameters: z.object({}),
  execute: async (
    {},
    calc_add: McpMeshTool | null = null  // Positional: dependencies[0]
  ) => {
    if (calc_add) {
      return "Calculator is available";
    } else {
      return "Calculator is not available";
    }
  },
});

console.log("ts-optional-dep-agent agent defined. Waiting for auto-start...");
