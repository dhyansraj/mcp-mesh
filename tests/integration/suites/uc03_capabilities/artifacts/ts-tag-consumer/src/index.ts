/**
 * Consumer agent that uses tag selectors for dependencies.
 */

import { FastMCP, mesh, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-tag-consumer",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-tag-consumer",
  httpPort: 9045,
});

// Tool that requires "api" tag
agent.addTool({
  name: "fetch_required",
  capability: "consumer",
  description: "Fetch data requiring api tag",
  tags: ["consumer"],
  dependencies: [
    { capability: "data_service", tags: ["api"] },
  ],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async (
    { query },
    data_service: McpMeshTool | null = null
  ) => {
    if (!data_service) {
      return "NO_PROVIDER";
    }
    const result = await data_service({ query });
    return `Required: ${result}`;
  },
});

// Tool that prefers "fast" tag
agent.addTool({
  name: "fetch_prefer_fast",
  capability: "consumer",
  description: "Fetch data preferring fast provider",
  tags: ["consumer"],
  dependencies: [
    { capability: "data_service", tags: ["+fast"] },
  ],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async (
    { query },
    data_service: McpMeshTool | null = null
  ) => {
    if (!data_service) {
      return "NO_PROVIDER";
    }
    const result = await data_service({ query });
    return `PreferFast: ${result}`;
  },
});

// Tool that excludes "deprecated" tag
agent.addTool({
  name: "fetch_exclude_deprecated",
  capability: "consumer",
  description: "Fetch data excluding deprecated provider",
  tags: ["consumer"],
  dependencies: [
    { capability: "data_service", tags: ["-deprecated"] },
  ],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async (
    { query },
    data_service: McpMeshTool | null = null
  ) => {
    if (!data_service) {
      return "NO_PROVIDER";
    }
    const result = await data_service({ query });
    return `ExcludeDeprecated: ${result}`;
  },
});

// Tool with combined filters
agent.addTool({
  name: "fetch_combined",
  capability: "consumer",
  description: "Fetch data with combined filters",
  tags: ["consumer"],
  dependencies: [
    { capability: "data_service", tags: ["api", "+accurate", "-deprecated"] },
  ],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async (
    { query },
    data_service: McpMeshTool | null = null
  ) => {
    if (!data_service) {
      return "NO_PROVIDER";
    }
    const result = await data_service({ query });
    return `Combined: ${result}`;
  },
});

console.log("ts-tag-consumer defined. Waiting for auto-start...");
