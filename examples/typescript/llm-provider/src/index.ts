#!/usr/bin/env npx tsx
/**
 * ts-llm-provider - MCP Mesh LLM Provider Agent
 *
 * A zero-code LLM provider that exposes Claude via mesh delegation.
 * Used for UC06 observability tracing tests.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

const server = new FastMCP({
  name: "Ts LLM Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-llm-provider",
  version: "1.0.0",
  description: "TypeScript LLM Provider for observability testing",
  httpPort: 9033,
});

agent.addLlmProvider({
  model: "anthropic/claude-sonnet-4-5",
  capability: "llm",
  tags: ["claude", "sonnet"],
  version: "1.0.0",
});

console.log("ts-llm-provider agent initialized. Waiting for mesh connections...");
