/**
 * Fast data provider - tags: api, fast
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-fast-provider",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-fast-provider",
  port: 9040,
});

agent.addTool({
  name: "get_data",
  capability: "data_service",
  description: "Get data quickly (fast provider)",
  tags: ["api", "fast"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }) => {
    return `TS_FAST: ${query}`;
  },
});

console.log("ts-fast-provider defined. Waiting for auto-start...");
