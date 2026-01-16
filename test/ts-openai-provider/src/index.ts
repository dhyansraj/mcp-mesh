#!/usr/bin/env node
/**
 * ts-openai-provider - MCP Mesh LLM Provider (TypeScript)
 *
 * A MCP Mesh LLM provider using agent.addLlmProvider().
 *
 * This agent provides LLM access to other agents via the mesh network.
 * Since ts-smart-assistant uses +claude tag (preferred), this OpenAI provider
 * will be used as fallback when Claude provider is unavailable.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

// FastMCP server instance
const server = new FastMCP({
  name: "OpenAIProvider",
  version: "1.0.0",
});

// ===== AGENT CONFIGURATION =====

/**
 * LLM Provider agent that exposes openai/gpt-4o-mini via mesh.
 *
 * Other agents can use this provider by specifying matching tags
 * in their mesh.llm() config:
 *   provider: { capability: "llm", tags: ["+openai"] }
 *
 * Or as fallback when preferred provider (e.g., +claude) is unavailable.
 */
const agent = mesh(server, {
  name: "ts-openai-provider",
  version: "1.0.0",
  description: "TypeScript LLM Provider for openai/gpt-4o-mini",
  port: 9014, // Different port from Python version (9004)
});

// ===== LLM PROVIDER =====

/**
 * Zero-code LLM provider for OpenAI.
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
  model: "openai/gpt-4o-mini",
  capability: "llm",
  tags: ["llm", "openai", "gpt", "provider"],
  version: "1.0.0",
  description: "OpenAI LLM provider via OpenAI API",
  maxTokens: 4096,
});

// No server.start() or main function needed!
// Mesh auto-start handles:
// - Vercel AI SDK provider setup
// - HTTP server configuration
// - Service registration with mesh registry

console.log("TypeScript OpenAI Provider starting...");
