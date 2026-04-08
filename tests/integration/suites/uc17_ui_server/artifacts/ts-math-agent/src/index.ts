#!/usr/bin/env npx tsx
/**
 * ts-math-agent - MCP Mesh Agent
 *
 * A MCP Mesh agent generated using meshctl scaffold.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsMathAgent Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-math-agent",
  httpPort: 9013,  // Auto-assign port
});

// ===== TOOLS =====

agent.addTool({
  name: "multiply",
  capability: "multiply",
  description: "Multiply two numbers together",
  tags: ["math", "multiply"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return String(a * b);
  },
});

agent.addTool({
  name: "add",
  capability: "add",
  description: "Add two numbers together",
  tags: ["math", "add"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    console.log(`[add] Adding ${a} + ${b} = ${a + b}`);
    return String(a + b);
  },
});

console.log("ts-math-agent agent defined. Waiting for auto-start...");
