#!/usr/bin/env npx tsx
/**
 * openai-provider-ts - MCP Mesh LLM Provider
 *
 * A MCP Mesh LLM provider generated using meshctl scaffold.
 *
 * This agent provides LLM access to other agents via the mesh network.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

// FastMCP server instance
const server = new FastMCP({
  name: "OpenaiProviderTs",
  version: "1.0.0",
});

// ===== AGENT CONFIGURATION =====

/**
 * LLM Provider agent that exposes openai/gpt-4o via mesh.
 *
 * Other agents can use this provider by specifying matching tags
 * in their mesh.llm() config:
 *   provider: { capability: "llm", tags: ["+claude"] }  // for Claude
 *   provider: { capability: "llm", tags: ["+openai"] }  // for OpenAI
 */
const agent = mesh(server, {
  name: "openai-provider-ts",
  version: "1.0.0",
  description: "LLM Provider for openai/gpt-4o",
  httpPort: 9000,
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
  model: "openai/gpt-4o",
  capability: "llm",
  tags: ["llm", "openai", "ts", "provider"],
  version: "1.0.0",
  description: "LLM provider via openai/gpt-4o",
  maxTokens: 4096,
});

// No server.start() needed!
// Mesh SDK automatically handles:
// - Vercel AI SDK provider setup
// - HTTP server configuration
// - Service registration with mesh registry

console.log("openai-provider-ts provider starting...");
