#!/usr/bin/env npx tsx
/**
 * gemini-provider-ts - MCP Mesh LLM Provider
 *
 * A MCP Mesh LLM provider generated using meshctl scaffold.
 *
 * This agent provides LLM access to other agents via the mesh network.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

// FastMCP server instance
const server = new FastMCP({
  name: "GeminiProviderTs",
  version: "1.0.0",
});

// ===== AGENT CONFIGURATION =====

/**
 * LLM Provider agent that exposes gemini/gemini-2.0-flash via mesh.
 *
 * Other agents can use this provider by specifying matching tags
 * in their mesh.llm() config:
 *   provider: { capability: "llm", tags: ["+claude"] }  // for Claude
 *   provider: { capability: "llm", tags: ["+openai"] }  // for OpenAI
 */
const agent = mesh(server, {
  name: "gemini-provider-ts",
  version: "1.0.0",
  description: "LLM Provider for gemini/gemini-2.0-flash",
  httpPort: 9006,
});

// ===== LLM PROVIDER =====

/**
 * Zero-code LLM provider.
 *
 * This provider will be discovered and called by other agents
 * via mesh delegation using the mesh.llm() config.
 *
 * The addLlmProvider() method automatically:
 * - Creates process_chat(request: MeshLlmRequest) handler
 * - Wraps Vercel AI SDK with error handling
 * - Registers with mesh network for dependency injection
 */
agent.addLlmProvider({
  model: "gemini/gemini-2.0-flash",
  capability: "llm",
  tags: ["llm", "gemini", "google", "provider"],
  version: "1.0.0",
  description: "LLM provider via gemini/gemini-2.0-flash",
  maxTokens: 4096,
});

// No server.start() needed!
// Mesh SDK automatically handles:
// - Vercel AI SDK provider setup
// - HTTP server configuration
// - Service registration with mesh registry

console.log("gemini-provider-ts provider starting...");
