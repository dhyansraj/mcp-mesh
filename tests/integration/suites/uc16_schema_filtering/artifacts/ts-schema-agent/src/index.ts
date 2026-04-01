#!/usr/bin/env npx tsx
/**
 * ts-schema-agent - Test agent for verifying MCP schema filtering.
 *
 * 9 tools covering the parameter matrix (cases 1-9):
 *   t01: no params           -> empty schema
 *   t02: one param           -> name visible
 *   t03: multi params        -> a, b, c visible
 *   t04: with defaults       -> a, b visible
 *   t05: dependency only     -> empty schema (dep separate from Zod)
 *   t06: normal then dep     -> query visible
 *   t07: dep order test      -> query visible
 *   t08: multi deps          -> q visible
 *   t09: mixed with defaults -> q, n visible
 *
 * In TypeScript, McpMeshTool dependencies are declared in the dependencies
 * array and passed as extra positional args after the Zod params object.
 * They never appear in the Zod schema by design.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "TsSchemaAgent", version: "1.0.0" });
const agent = mesh(server, { name: "ts-schema-agent", httpPort: 9060 });

// Case 1: No params
agent.addTool({
  name: "t01_no_params",
  capability: "schema.t01",
  description: "No parameters",
  parameters: z.object({}),
  execute: async () => "ok",
});

// Case 2: One param
agent.addTool({
  name: "t02_one_param",
  capability: "schema.t02",
  description: "Single parameter",
  parameters: z.object({
    name: z.string().describe("Name to greet"),
  }),
  execute: async ({ name }) => `Hello ${name}`,
});

// Case 3: Multiple params
agent.addTool({
  name: "t03_multi_params",
  capability: "schema.t03",
  description: "Multiple parameters",
  parameters: z.object({
    a: z.string().describe("String param"),
    b: z.number().describe("Number param"),
    c: z.boolean().describe("Boolean param"),
  }),
  execute: async ({ a, b, c }) => `${a} ${b} ${c}`,
});

// Case 4: With defaults
agent.addTool({
  name: "t04_with_defaults",
  capability: "schema.t04",
  description: "Parameters with defaults",
  parameters: z.object({
    a: z.string().describe("Required param"),
    b: z.number().default(5).describe("Optional with default"),
  }),
  execute: async ({ a, b }) => `${a} ${b}`,
});

// Case 5: Dependency only (no user params)
agent.addTool({
  name: "t05_dep_only",
  capability: "schema.t05",
  description: "Dependency only",
  dependencies: ["dep_a"],
  parameters: z.object({}),
  execute: async (args: {}, svc: McpMeshTool) => "ok",
});

// Case 6: Normal then dependency
agent.addTool({
  name: "t06_normal_then_dep",
  capability: "schema.t06",
  description: "Normal then dependency",
  dependencies: ["dep_a"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }, svc: McpMeshTool) => `Result for ${query}`,
});

// Case 7: Same as 6 (TS doesn't have order issue - deps are always after args)
agent.addTool({
  name: "t07_dep_order",
  capability: "schema.t07",
  description: "Dependency order test",
  dependencies: ["dep_a"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }, svc: McpMeshTool) => `Result for ${query}`,
});

// Case 8: Multiple dependencies
agent.addTool({
  name: "t08_multi_dep",
  capability: "schema.t08",
  description: "Multiple dependencies",
  dependencies: ["dep_a", "dep_b"],
  parameters: z.object({
    q: z.string().describe("Query"),
  }),
  execute: async ({ q }, a: McpMeshTool, b: McpMeshTool) => `Result for ${q}`,
});

// Case 9: Normal + dependency + defaults
agent.addTool({
  name: "t09_mixed_defaults",
  capability: "schema.t09",
  description: "Mixed with defaults",
  dependencies: ["dep_a"],
  parameters: z.object({
    q: z.string().describe("Query"),
    n: z.number().default(5).describe("Count with default"),
  }),
  execute: async ({ q, n }, svc: McpMeshTool) => `${q} ${n}`,
});

console.log("ts-schema-agent defined. Waiting for auto-start...");
