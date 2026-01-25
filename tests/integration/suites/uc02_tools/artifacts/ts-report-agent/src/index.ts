#!/usr/bin/env npx tsx
/**
 * ts-report-agent - MCP Mesh Agent
 *
 * Report agent that uses calculator tools for computations
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsReportAgent Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-report-agent",
  httpPort: 9024,
});

// ===== TOOLS =====

agent.addTool({
  name: "sum_report",
  capability: "reporting",
  description: "Generate a sum report by calling calculator",
  tags: ["report", "summary"],
  dependencies: ["calc_add"],
  parameters: z.object({
    numbers: z.array(z.number()).describe("List of numbers to sum"),
  }),
  execute: async (
    { numbers },
    calc_add: McpMeshTool | null = null  // Positional: dependencies[0]
  ) => {
    if (!numbers || numbers.length === 0) {
      return "No numbers provided";
    }

    if (!calc_add) {
      // Fallback to local calculation
      const total = numbers.reduce((acc, num) => acc + num, 0);
      return `Sum of [${numbers.join(", ")}] = ${total} (local)`;
    }

    // Use the injected calc_add tool
    let total = numbers[0];
    for (let i = 1; i < numbers.length; i++) {
      total = await calc_add({ a: total, b: numbers[i] });
    }

    return `Sum of [${numbers.join(", ")}] = ${total}`;
  },
});

agent.addTool({
  name: "product_report",
  capability: "reporting",
  description: "Generate a product report by calling calculator",
  tags: ["report", "summary"],
  dependencies: ["calc_multiply"],
  parameters: z.object({
    numbers: z.array(z.number()).describe("List of numbers to multiply"),
  }),
  execute: async (
    { numbers },
    calc_multiply: McpMeshTool | null = null  // Positional: dependencies[0]
  ) => {
    if (!numbers || numbers.length === 0) {
      return "No numbers provided";
    }

    if (!calc_multiply) {
      // Fallback to local calculation
      const total = numbers.reduce((acc, num) => acc * num, 1);
      return `Product of [${numbers.join(", ")}] = ${total} (local)`;
    }

    // Use the injected calc_multiply tool
    let total = numbers[0];
    for (let i = 1; i < numbers.length; i++) {
      total = await calc_multiply({ a: total, b: numbers[i] });
    }

    return `Product of [${numbers.join(", ")}] = ${total}`;
  },
});

console.log("ts-report-agent agent defined. Waiting for auto-start...");
