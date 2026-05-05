#!/usr/bin/env npx tsx
/**
 * consumer-gemini-ts - MCP Mesh LLM Agent (Gemini)
 *
 * A MCP Mesh LLM agent that tests parallel tool execution using
 * mesh-delegated Gemini provider.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ConsumerGeminiTs Service",
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

  // LLM Configuration - mesh delegation to Gemini provider
  provider: { capability: "llm", tags: ["+gemini"] },
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
  name: "consumer-gemini-ts",
  version: "1.0.0",
  description: "Mesh-delegated LLM agent (Gemini) testing parallel tool execution",
  httpPort: 9000,
});

console.log("consumer-gemini-ts agent initialized. Waiting for mesh connections...");
