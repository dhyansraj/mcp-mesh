#!/usr/bin/env npx tsx
/**
 * ts-llm-consumer - MCP Mesh LLM Consumer Agent
 *
 * An LLM agent that uses mesh delegation and has a tool dependency
 * on the "add" capability. Used for UC06 observability tracing tests.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Ts LLM Consumer Service",
  version: "1.0.0",
});

// LLM-powered tool with mesh delegation and tool dependency
const llmTool = mesh.llm({
  name: "analyze",
  capability: "qa",
  description: "Analyze a question using mesh-delegated LLM with tool access",
  tags: ["qa", "llm"],
  version: "1.0.0",

  // LLM Configuration - mesh delegation to LLM provider
  provider: { capability: "llm", tags: ["+claude"] },
  maxIterations: 5,
  systemPrompt: "You are a helpful math assistant. When asked math questions, ALWAYS use the available add tool to compute the answer. Return the numeric result clearly.",

  // Tool filtering - access to add capability
  filter: [{ capability: "add" }],
  filterMode: "all",

  // Input schema
  parameters: z.object({
    question: z.string().describe("The question to analyze"),
  }),

  // Handler
  execute: async ({ question }, { llm }) => {
    return await llm(question);
  },
});

server.addTool(llmTool);

const agent = mesh(server, {
  name: "ts-llm-consumer",
  version: "1.0.0",
  description: "TypeScript LLM Consumer for observability testing",
  httpPort: 9034,
});

console.log("ts-llm-consumer agent initialized. Waiting for mesh connections...");
