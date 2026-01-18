/**
 * Simple TypeScript agent for registry tests.
 * Minimal agent with one tool.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-simple-agent",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-simple-agent",
  port: 9001,
});

agent.addTool({
  name: "greet",
  capability: "simple_greeting",
  description: "Returns a simple greeting",
  tags: ["greeting", "simple", "typescript"],
  parameters: z.object({
    name: z.string().default("World").describe("Name to greet"),
  }),
  execute: async ({ name }) => {
    return `Hello, ${name}! From TypeScript agent at ${new Date().toISOString()}`;
  },
});

console.log("ts-simple-agent defined. Waiting for auto-start...");
