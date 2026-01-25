#!/usr/bin/env npx tsx
/**
 * ts-math-agent - MCP Mesh Agent
 *
 * Math agent with add, subtract, multiply, divide tools
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
  httpPort: 9011,
});

// ===== TOOLS =====

agent.addTool({
  name: "add",
  capability: "math_operations",
  description: "Add two numbers",
  tags: ["math", "addition"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return a + b;
  },
});

agent.addTool({
  name: "subtract",
  capability: "math_operations",
  description: "Subtract two numbers",
  tags: ["math", "subtraction"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return a - b;
  },
});

agent.addTool({
  name: "multiply",
  capability: "math_operations",
  description: "Multiply two numbers",
  tags: ["math", "multiplication"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return a * b;
  },
});

agent.addTool({
  name: "divide",
  capability: "math_operations",
  description: "Divide two numbers",
  tags: ["math", "division"],
  parameters: z.object({
    a: z.number().describe("First number (dividend)"),
    b: z.number().describe("Second number (divisor)"),
  }),
  execute: async ({ a, b }) => {
    if (b === 0) {
      throw new Error("Cannot divide by zero");
    }
    return a / b;
  },
});

console.log("ts-math-agent agent defined. Waiting for auto-start...");
