#!/usr/bin/env npx tsx
/**
 * ts-schema-agent - Test agent for verifying MCP schema filtering.
 *
 * Tools have mesh-injected dependencies that should NOT appear in the external schema.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "TsSchemaAgent", version: "1.0.0" });
const agent = mesh(server, { name: "ts-schema-agent", httpPort: 9060 });

agent.addTool({
  name: "greet",
  capability: "schema.greet",
  description: "Simple greeting",
  parameters: z.object({
    name: z.string().describe("Name to greet"),
  }),
  execute: async ({ name }) => `Hello ${name}`,
});

agent.addTool({
  name: "with_dep",
  capability: "schema.with_dep",
  description: "Tool with dependency",
  dependencies: ["some_service"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }, svc: McpMeshTool) => `Result for ${query}`,
});

console.log("ts-schema-agent defined. Waiting for auto-start...");
