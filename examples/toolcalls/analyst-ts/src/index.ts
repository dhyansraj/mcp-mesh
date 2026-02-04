#!/usr/bin/env npx tsx
/**
 * analyst-ts - MCP Mesh LLM Agent
 *
 * A MCP Mesh LLM agent generated using meshctl scaffold.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "AnalystTs Service",
  version: "1.0.0",
});

// ===== CONTEXT SCHEMA =====

const AnalysisContext = z.object({
  query: z.string().describe("The analysis query"),
  dataSource: z.string().optional().describe("Data source hint"),
  parameters: z.record(z.unknown()).optional().describe("Optional parameters"),
});


// ===== RESPONSE SCHEMA =====

const AnalysisResult = z.object({
  summary: z.string().describe("Analysis summary"),
  insights: z.array(z.string()).describe("List of insights"),
  confidence: z.number().min(0).max(1).describe("Confidence score (0.0 to 1.0)"),
  source: z.string().describe("Data source used"),
});


// ===== LLM TOOL =====

/**
 * LLM-powered tool configuration.
 *
 * This tool uses mesh.llm() to:
 * - Discover LLM provider via mesh (capability: "llm")
 * - Access tools matching the filter (e.g., tags: ["weather", "data"])
 * - Run an agentic loop with up to 5 iterations
 * - Use a Handlebars template for the system prompt
 */
const llmTool = mesh.llm({
  name: "analyze",
  capability: "analyze",
  description: "AI-powered data analysis with agentic tool use",
  tags: ["analysis", "llm", "typescript"],

  // LLM Configuration
  provider: { capability: "llm" },
  maxIterations: 5,
  systemPrompt: "file://prompts/analyst-ts.hbs",
  contextParam: "ctx",

  // Tool filtering - which mesh tools the LLM can access
  filter: [{"tags":["weather","data"]}],
  filterMode: "all",

  // Input/output schemas
  parameters: z.object({
    ctx: AnalysisContext,
  }),

  returns: AnalysisResult,


  // Handler receives injected LLM agent
  execute: async ({ ctx }, { llm }) => {
    return await llm(ctx.query);
  },
});

// Add LLM tool to server
server.addTool(llmTool);

// ===== AGENT CONFIGURATION =====

/**
 * Create the mesh agent.
 *
 * The mesh agent will:
 * 1. Start the FastMCP HTTP server on port 9000
 * 2. Register capabilities with the mesh registry
 * 3. Handle LLM tool resolution (llm_tools_updated events)
 * 4. Handle LLM provider resolution (llm_provider_available events)
 */
const agent = mesh(server, {
  name: "analyst-ts",
  version: "1.0.0",
  description: "MCP Mesh LLM agent",
  httpPort: 9000,
});

// No explicit start needed - auto-starts via process.nextTick()!
// Mesh processor automatically handles:
// - FastMCP server startup
// - LLM provider discovery and injection
// - Tool discovery and injection
// - Service registration with mesh registry

console.log("analyst-ts agent initialized. Waiting for mesh connections...");
