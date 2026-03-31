#!/usr/bin/env npx tsx
/**
 * parallel-consumer-ts - MCP Mesh LLM Agent
 *
 * A MCP Mesh LLM agent that tests parallel tool execution.
 * Uses parallelToolCalls: true to enable simultaneous tool calls.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ParallelConsumerTs Service",
  version: "1.0.0",
});

// ===== CONTEXT SCHEMA =====

const AnalysisContext = z.object({
  query: z.string().describe("The analysis query"),
  ticker: z.string().optional().describe("Optional ticker symbol hint"),
});

// ===== RESPONSE SCHEMA =====

const StockAnalysis = z.object({
  summary: z.string().describe("Analysis summary"),
  insights: z.array(z.string()).describe("List of insights"),
  ticker: z.string().describe("Ticker symbol analyzed"),
  data_sources: z.array(z.string()).describe("Data sources used"),
});

// ===== LLM TOOL =====

const llmTool = mesh.llm({
  name: "parallel_analyze",
  capability: "parallel_analyze",
  description: "AI-powered stock analysis with parallel tool execution",
  tags: ["analysis", "llm", "parallel-test"],

  // LLM Configuration
  provider: { capability: "llm" },
  maxIterations: 5,
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

  returns: StockAnalysis,

  // Handler
  execute: async ({ ctx }, { llm }) => {
    return await llm(ctx.query);
  },
});

server.addTool(llmTool);

// ===== AGENT CONFIGURATION =====

const agent = mesh(server, {
  name: "parallel-consumer-ts",
  version: "1.0.0",
  description: "LLM agent testing parallel tool execution",
  httpPort: 9000,
});

console.log("parallel-consumer-ts agent initialized. Waiting for mesh connections...");
