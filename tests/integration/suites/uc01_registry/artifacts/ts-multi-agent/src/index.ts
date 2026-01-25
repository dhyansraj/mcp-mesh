#!/usr/bin/env npx tsx
/**
 * ts-multi-agent - MCP Mesh Agent for registry tests.
 *
 * Multi-file TypeScript agent with multiple tools.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-multi-agent",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-multi-agent",
  httpPort: 9003,
});

// ===== TOOLS =====

agent.addTool({
  name: "greet",
  capability: "greeting",
  description: "Greet someone by name",
  tags: ["greeting", "typescript"],
  parameters: z.object({
    name: z.string().default("World").describe("Name to greet"),
  }),
  execute: async ({ name }) => {
    return `Hello, ${name}! From ts-multi-agent at ${new Date().toISOString()}`;
  },
});

agent.addTool({
  name: "echo",
  capability: "echo",
  description: "Echo a message back",
  tags: ["utility", "typescript"],
  parameters: z.object({
    message: z.string().describe("Message to echo"),
  }),
  execute: async ({ message }) => {
    return `Echo: ${message}`;
  },
});

agent.addTool({
  name: "get_info",
  capability: "info",
  description: "Get agent info",
  tags: ["info", "typescript"],
  parameters: z.object({}),
  execute: async () => {
    return {
      name: "ts-multi-agent",
      version: "1.0.0",
      language: "typescript",
      timestamp: new Date().toISOString(),
    };
  },
});

console.log("ts-multi-agent defined. Waiting for auto-start...");
