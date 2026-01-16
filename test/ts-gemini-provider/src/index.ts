#!/usr/bin/env node
/**
 * ts-gemini-provider - MCP Mesh LLM Provider (TypeScript)
 *
 * A MCP Mesh LLM provider for Google Gemini models using agent.addLlmProvider().
 *
 * This agent provides LLM access to other agents via the mesh network.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

// FastMCP server instance
const server = new FastMCP({
  name: "GeminiProvider",
  version: "1.0.0",
});

// ===== AGENT CONFIGURATION =====

/**
 * LLM Provider agent that exposes gemini/gemini-2.0-flash via mesh.
 *
 * Other agents can use this provider by specifying matching tags
 * in their mesh.llm() config:
 *   provider: { capability: "llm", tags: ["+gemini"] }
 *
 * Or as fallback when preferred provider is unavailable.
 */
const agent = mesh(server, {
  name: "ts-gemini-provider",
  version: "1.0.0",
  description: "TypeScript LLM Provider for gemini/gemini-2.0-flash",
  port: 9015, // Different port from Python version (9012)
});

// ===== LLM PROVIDER =====

/**
 * Zero-code LLM provider for Gemini.
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
  description: "Gemini LLM provider via Google AI API",
  maxOutputTokens: 4096,
});

// No server.start() or main function needed!
// Mesh auto-start handles:
// - Vercel AI SDK provider setup
// - HTTP server configuration
// - Service registration with mesh registry

console.log("TypeScript Gemini Provider starting...");
