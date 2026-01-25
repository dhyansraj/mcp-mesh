#!/usr/bin/env npx tsx
/**
 * ts-calculator-agent - MCP Mesh Agent
 *
 * Calculator agent demonstrating tag-level OR alternatives:
 * tags: ["addition", ["python", "typescript"]] = addition AND (python OR typescript)
 * Prefers python provider, falls back to typescript if unavailable.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsCalculatorAgent Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-calculator-agent",
  httpPort: 9025,
});

// ===== LOCAL TOOLS (for backward compatibility) =====

agent.addTool({
  name: "calc_add",
  capability: "calculator",
  description: "Add two numbers",
  tags: ["math", "calculator"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return a + b;
  },
});

agent.addTool({
  name: "calc_multiply",
  capability: "calculator",
  description: "Multiply two numbers",
  tags: ["math", "calculator"],
  parameters: z.object({
    a: z.number().describe("First number"),
    b: z.number().describe("Second number"),
  }),
  execute: async ({ a, b }) => {
    return a * b;
  },
});

// ===== MULTI-DEPENDENCY TOOL =====

interface CalculateResult {
  a: number;
  b: number;
  operator: string;
  result: number | null;
  source: string | null;
  error: string | null;
}

agent.addTool({
  name: "calculate",
  capability: "calculator",
  description: "Calculate result using operator (+, -, *, /)",
  tags: ["math", "calculator", "multi-dep", "or-tags"],
  dependencies: [
    { capability: "math_operations", tags: ["addition", ["python", "typescript"]] },
    { capability: "math_operations", tags: ["subtraction", ["python", "typescript"]] },
    { capability: "math_operations", tags: ["multiplication", ["python", "typescript"]] },
    { capability: "math_operations", tags: ["division", ["python", "typescript"]] },
  ],
  parameters: z.object({
    a: z.number().describe("First operand"),
    b: z.number().describe("Second operand"),
    operator: z.string().describe("Operator: +, -, *, /"),
  }),
  execute: async (
    { a, b, operator },
    add: McpMeshTool | null = null,       // Positional: dependencies[0] - addition
    subtract: McpMeshTool | null = null,  // Positional: dependencies[1] - subtraction
    multiply: McpMeshTool | null = null,  // Positional: dependencies[2] - multiplication
    divide: McpMeshTool | null = null     // Positional: dependencies[3] - division
  ) => {
    const result: CalculateResult = {
      a,
      b,
      operator,
      result: null,
      source: null,
      error: null,
    };

    try {
      switch (operator) {
        case "+":
          if (add) {
            result.result = await add({ a, b });
            result.source = "ts-math-agent";
          } else {
            result.result = a + b;
            result.source = "local";
          }
          break;

        case "-":
          if (subtract) {
            result.result = await subtract({ a, b });
            result.source = "ts-math-agent";
          } else {
            result.result = a - b;
            result.source = "local";
          }
          break;

        case "*":
          if (multiply) {
            result.result = await multiply({ a, b });
            result.source = "ts-math-agent";
          } else {
            result.result = a * b;
            result.source = "local";
          }
          break;

        case "/":
          if (b === 0) {
            result.error = "Cannot divide by zero";
          } else if (divide) {
            result.result = await divide({ a, b });
            result.source = "ts-math-agent";
          } else {
            result.result = a / b;
            result.source = "local";
          }
          break;

        default:
          result.error = `Unknown operator: ${operator}. Use +, -, *, /`;
      }
    } catch (e: any) {
      result.error = e.message;
    }

    return result;
  },
});

console.log("ts-calculator-agent agent defined. Waiting for auto-start...");
