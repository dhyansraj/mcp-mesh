#!/usr/bin/env node
/**
 * ts-claude-provider - MCP Mesh LLM Provider (TypeScript)
 *
 * A MCP Mesh LLM provider using agent.addLlmProviderTool().
 *
 * This agent provides LLM access to other agents via the mesh network.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

// FastMCP server instance
const server = new FastMCP({
  name: "ClaudeProvider",
  version: "1.0.0",
});

// ===== AGENT CONFIGURATION =====

/**
 * LLM Provider agent that exposes anthropic/claude-sonnet-4-5 via mesh.
 *
 * Other agents can use this provider by specifying matching tags
 * in their mesh.llm() config:
 *   provider: { capability: "llm", tags: ["+claude"] }
 */
const agent = mesh(server, {
  name: "ts-claude-provider",
  version: "1.0.0",
  description: "TypeScript LLM Provider for anthropic/claude-sonnet-4-5",
  port: 9012, // Different port from Python version (9011)
});

// ===== LLM PROVIDER =====

/**
 * Zero-code LLM provider for Claude.
 *
 * This provider will be discovered and called by other agents
 * via mesh delegation using the mesh.llm() config.
 *
 * The addLlmProviderTool() method automatically:
 * - Creates process_chat(request: MeshLlmRequest) handler
 * - Wraps Vercel AI SDK with error handling
 * - Registers with mesh network for dependency injection
 */
agent.addLlmProviderTool({
  model: "anthropic/claude-sonnet-4-5",
  capability: "llm",
  tags: ["llm", "claude", "anthropic", "provider"],
  version: "1.0.0",
  description: "Claude LLM provider via Anthropic API",
  maxTokens: 4096,
});

// No server.start() or main function needed!
// Mesh auto-start handles:
// - Vercel AI SDK provider setup
// - HTTP server configuration
// - Service registration with mesh registry

console.log("TypeScript Claude Provider starting...");
