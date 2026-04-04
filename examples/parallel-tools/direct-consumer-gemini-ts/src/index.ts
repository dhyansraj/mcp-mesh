#!/usr/bin/env npx tsx
/**
 * direct-consumer-gemini-ts - MCP Mesh Direct LLM Agent (Gemini)
 *
 * A MCP Mesh LLM agent that tests parallel tool execution using
 * direct mode with Google Gemini.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "DirectConsumerGeminiTs Service",
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

  // LLM Configuration
  provider: "google/gemini-2.0-flash",
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
  name: "direct-consumer-gemini-ts",
  version: "1.0.0",
  description: "Direct LLM agent (Gemini) testing parallel tool execution",
  httpPort: 9000,
});

console.log("direct-consumer-gemini-ts agent initialized. Waiting for mesh connections...");
