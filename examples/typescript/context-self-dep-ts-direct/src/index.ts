#!/usr/bin/env npx tsx
/**
 * context-self-dep-ts-direct - MCP Mesh LLM Agent
 *
 * A MCP Mesh LLM agent generated using meshctl scaffold.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "ContextSelfDepTsDirect Service",
  version: "1.0.0",
});

// ===== CONTEXT SCHEMA =====

const ContextSelfDepTsDirectContext = z.object({
  inputText: z.string().describe("Input text to process"),
  // Add your context fields here
  // userId: z.string().describe("User identifier"),
  // metadata: z.record(z.any()).optional().describe("Additional metadata"),
});



// ===== LLM TOOL =====

/**
 * LLM-powered tool configuration.
 *
 * This tool uses mesh.llm() to:
 * - Call LLM directly via LiteLLM (provider: "claude")
 * - Run an agentic loop with up to 1 iterations
 * - Use a Handlebars template for the system prompt
 */
const llmTool = mesh.llm({
  name: "context_self_dep_ts_direct",
  capability: "context_self_dep_ts_direct",
  description: "Process input using LLM with direct LiteLLM",
  tags: ["llm", "direct"],

  // LLM Configuration - Direct LiteLLM (no mesh delegation)
  provider: "claude",
  maxIterations: 1,
  systemPrompt: "file://prompts/context-self-dep-ts-direct.hbs",
  contextParam: "ctx",

  // Tool filtering - which mesh tools the LLM can access
  filter: [],
  filterMode: "all",

  // Input/output schemas
  parameters: z.object({
    ctx: ContextSelfDepTsDirectContext,
  }),


  // Handler receives injected LLM agent
  execute: async ({ ctx }, { llm }) => {
    return await llm("Process the input based on the context provided");
  },
});

// Add LLM tool to server
server.addTool(llmTool);

// ===== AGENT CONFIGURATION =====

/**
 * Create the mesh agent.
 *
 * The mesh agent will:
 * 1. Start the FastMCP HTTP server on port 9020
 * 2. Register capabilities with the mesh registry
 * 3. Handle LLM tool resolution (llm_tools_updated events)
 * 4. Handle LLM provider resolution (llm_provider_available events)
 */
const agent = mesh(server, {
  name: "context-self-dep-ts-direct",
  version: "1.0.0",
  description: "MCP Mesh LLM agent with direct LiteLLM",
  httpPort: 9030,
});

// No explicit start needed - auto-starts via process.nextTick()!
// Mesh processor automatically handles:
// - FastMCP server startup
// - LLM provider discovery and injection
// - Tool discovery and injection
// - Service registration with mesh registry

console.log("context-self-dep-ts-direct agent initialized. Waiting for mesh connections...");
