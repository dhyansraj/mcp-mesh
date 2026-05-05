#!/usr/bin/env npx tsx
/**
 * consumer-openai-ts - MCP Mesh LLM Agent (OpenAI)
 *
 * A MCP Mesh LLM agent that tests parallel tool execution using
 * mesh-delegated OpenAI provider.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ConsumerOpenaiTs Service",
  version: "1.0.0",
});

// ===== CONTEXT SCHEMA =====

const AnalysisContext = z.object({
  query: z.string().describe("The analysis query"),
  ticker: z.string().optional().describe("Optional ticker symbol hint"),
});

// ===== LLM TOOL =====

const llmTool = mesh.llm({
  name: "parallel_analyze",
  capability: "parallel_analyze",
  description: "AI-powered stock analysis with parallel tool execution",
  tags: ["analysis", "llm", "parallel-test"],

  // LLM Configuration - mesh delegation to OpenAI provider
  provider: { capability: "llm", tags: ["+openai"] },
  maxIterations: 10,
  parallelToolCalls: true,
  systemPrompt: "file://prompts/system.hbs",
  contextParam: "ctx",

  // Tool filtering
  filter: [{ tags: ["financial", "slow-tool"] }],
  filterMode: "all",

  // Input/output schemas
  parameters: z.object({
    ctx: AnalysisContext,
  }),

  // Handler
  execute: async ({ ctx }, { llm }) => {
    return await llm(ctx.query);
  },
});

server.addTool(llmTool);

// ===== AGENT CONFIGURATION =====

const agent = mesh(server, {
  name: "consumer-openai-ts",
  version: "1.0.0",
  description: "Mesh-delegated LLM agent (OpenAI) testing parallel tool execution",
  httpPort: 9000,
});

console.log("consumer-openai-ts agent initialized. Waiting for mesh connections...");
