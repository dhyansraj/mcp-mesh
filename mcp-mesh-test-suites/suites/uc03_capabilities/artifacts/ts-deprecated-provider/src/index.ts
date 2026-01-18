/**
 * Deprecated data provider - tags: api, deprecated
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-deprecated-provider",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-deprecated-provider",
  port: 9042,
});

agent.addTool({
  name: "get_data",
  capability: "data_service",
  description: "Get data (deprecated provider)",
  tags: ["api", "deprecated"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }) => {
    return `TS_DEPRECATED: ${query}`;
  },
});

console.log("ts-deprecated-provider defined. Waiting for auto-start...");
