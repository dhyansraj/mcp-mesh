/**
 * Greeter Agent - Demonstrates Dependency Injection
 *
 * This agent depends on the calculator agent's capabilities.
 * Dependencies are injected positionally, just like Python SDK.
 *
 * Run with:
 *   npm start
 *
 * Requirements:
 *   - Registry running on port 8000
 *   - Calculator agent running (for full functionality)
 */

import { FastMCP } from "fastmcp";
import { mesh, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Greeter", version: "1.0.0" });

const agent = mesh(server, {
  name: "greeter",
  port: 9005,
  description: "Greeter agent with dependency injection example",
});

// Simple greeting - no dependencies
agent.addTool({
  name: "greet",
  capability: "greet",
  tags: ["greeting"],
  description: "Greet someone by name",
  parameters: z.object({
    name: z.string().describe("Name to greet"),
  }),
  execute: async ({ name }) => {
    return `Hello, ${name}! Welcome to MCP Mesh.`;
  },
});

// Greeting with lucky number - depends on calculator's add capability
agent.addTool({
  name: "greet_with_lucky_number",
  capability: "greet-lucky",
  tags: ["greeting", "math"],
  description: "Greet someone with their lucky number (birth year + birth month)",
  dependencies: ["add"], // dependencies[0] -> add param
  parameters: z.object({
    name: z.string().describe("Name to greet"),
    birthYear: z.number().describe("Birth year"),
    birthMonth: z.number().describe("Birth month (1-12)"),
  }),
  execute: async (
    { name, birthYear, birthMonth },
    add: McpMeshTool | null = null // Positional injection!
  ) => {
    if (!add) {
      // Graceful degradation when calculator is unavailable
      return `Hello, ${name}! (Lucky number calculation unavailable - calculator not connected)`;
    }

    try {
      // Call the calculator's add function
      const luckyNumber = await add({ a: birthYear, b: birthMonth });
      return `Hello, ${name}! Your lucky number is ${luckyNumber}.`;
    } catch (err) {
      return `Hello, ${name}! (Error calculating lucky number: ${err})`;
    }
  },
});

// Greeting with age - multiple dependencies
agent.addTool({
  name: "greet_with_age",
  capability: "greet-age",
  tags: ["greeting", "math"],
  description: "Greet someone with their age",
  dependencies: ["subtract"], // dependencies[0] -> subtract param
  parameters: z.object({
    name: z.string().describe("Name to greet"),
    birthYear: z.number().describe("Birth year"),
  }),
  execute: async (
    { name, birthYear },
    subtract: McpMeshTool | null = null // Positional injection!
  ) => {
    if (!subtract) {
      return `Hello, ${name}! (Age calculation unavailable - calculator not connected)`;
    }

    try {
      const currentYear = new Date().getFullYear();
      const age = await subtract({ a: currentYear, b: birthYear });
      return `Hello, ${name}! You are approximately ${age} years old.`;
    } catch (err) {
      return `Hello, ${name}! (Error calculating age: ${err})`;
    }
  },
});

// Example with multiple dependencies
agent.addTool({
  name: "math_greeting",
  capability: "greet-math",
  tags: ["greeting", "math"],
  description: "Greet with a math fact using multiple operations",
  dependencies: ["add", "multiply"], // Two dependencies
  parameters: z.object({
    name: z.string().describe("Name to greet"),
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  Execute: async (
    { name, a, b },
    add: McpMeshTool | null = null,      // dependencies[0]
    multiply: McpMeshTool | null = null  // dependencies[1]
  ) => {
    const results: string[] = [`Hello, ${name}!`];

    if (add) {
      try {
        const sum = await add({ a, b });
        results.push(`${a} + ${b} = ${sum}`);
      } catch {
        results.push(`(add failed)`);
      }
    }

    if (multiply) {
      try {
        const product = await multiply({ a, b });
        results.push(`${a} × ${b} = ${product}`);
      } catch {
        results.push(`(multiply failed)`);
      }
    }

    if (!add && !multiply) {
      results.push("(calculator not available)");
    }

    return results.join(" ");
  },
});

console.log("Greeter agent defined. Waiting for auto-start...");
console.log("Dependencies: add, subtract, multiply (from calculator agent)");
