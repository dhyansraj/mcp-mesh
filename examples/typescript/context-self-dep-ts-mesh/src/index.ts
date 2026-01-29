#!/usr/bin/env npx tsx
/**
 * context-self-dep-ts-mesh - MCP Mesh LLM Agent
 *
 * A MCP Mesh LLM agent generated using meshctl scaffold.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "ContextSelfDepTsMesh Service",
  version: "1.0.0",
});

// ===== CONTEXT SCHEMA =====

const ContextSelfDepTsMeshContext = z.object({
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
 * - Discover LLM provider via mesh (capability: "llm")
 * - Access tools matching the filter (e.g., tags: ["math"])
 * - Run an agentic loop with up to 1 iterations
 * - Use a Handlebars template for the system prompt
 */
const llmTool = mesh.llm({
  name: "context_self_dep_ts_mesh",
  capability: "context_self_dep_ts_mesh",
  description: "Process input using LLM",
  tags: ["llm"],

  // LLM Configuration - mesh delegation to LLM provider (prefer claude)
  provider: { capability: "llm", tags: ["+claude"] },
  maxIterations: 1,
  systemPrompt: "file://prompts/context-self-dep-ts-mesh.hbs",
  contextParam: "ctx",

  // Tool filtering - no tools for this test
  filter: [],
  filterMode: "all",

  // Input/output schemas
  parameters: z.object({
    ctx: ContextSelfDepTsMeshContext,
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
 * 1. Start the FastMCP HTTP server on port 9021
 * 2. Register capabilities with the mesh registry
 * 3. Handle LLM tool resolution (llm_tools_updated events)
 * 4. Handle LLM provider resolution (llm_provider_available events)
 */
const agent = mesh(server, {
  name: "context-self-dep-ts-mesh",
  version: "1.0.0",
  description: "MCP Mesh LLM agent",
  httpPort: 9031,
});

// No explicit start needed - auto-starts via process.nextTick()!
// Mesh processor automatically handles:
// - FastMCP server startup
// - LLM provider discovery and injection
// - Tool discovery and injection
// - Service registration with mesh registry

console.log("context-self-dep-ts-mesh agent initialized. Waiting for mesh connections...");
