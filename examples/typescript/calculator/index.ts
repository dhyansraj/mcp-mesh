/**
 * Calculator Agent Example
 *
 * This example shows how to create a simple MCP Mesh agent using @mcpmesh/sdk.
 *
 * Setup:
 *   cd examples/typescript/calculator
 *   npm install
 *
 * Run with:
 *   npx tsx index.ts
 */

import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// Create the FastMCP server
const server = new FastMCP({
  name: "Calculator Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "calculator",
  httpPort: 9002,
  description: "A simple calculator agent",
});

// Add tools
agent.addTool({
  name: "add",
  capability: "add",
  tags: ["tools", "math"],
  description: "Add two numbers together",
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => String(a + b),
});

agent.addTool({
  name: "subtract",
  capability: "subtract",
  tags: ["tools", "math"],
  description: "Subtract two numbers",
  parameters: z.object({
    a: z.number().describe("Number to subtract from"),
    b: z.number().describe("Number to subtract"),
  }),
  execute: async ({ a, b }) => String(a - b),
});

agent.addTool({
  name: "multiply",
  capability: "multiply",
  tags: ["tools", "math"],
  description: "Multiply two numbers",
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => String(a * b),
});

agent.addTool({
  name: "divide",
  capability: "divide",
  tags: ["tools", "math"],
  description: "Divide two numbers",
  parameters: z.object({
    a: z.number().describe("Dividend"),
    b: z.number().describe("Divisor"),
  }),
  execute: async ({ a, b }) => {
    if (b === 0) {
      throw new Error("Division by zero");
    }
    return String(a / b);
  },
});

// No server.start() or main function needed!
// The SDK auto-starts after module loading completes

console.log("Calculator agent defined. Waiting for auto-start...");
