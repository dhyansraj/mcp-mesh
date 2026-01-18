/**
 * Accurate data provider - tags: api, accurate
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-accurate-provider",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-accurate-provider",
  port: 9041,
});

agent.addTool({
  name: "get_data",
  capability: "data_service",
  description: "Get data accurately (accurate provider)",
  tags: ["api", "accurate"],
  parameters: z.object({
    query: z.string().describe("Query string"),
  }),
  execute: async ({ query }) => {
    return `TS_ACCURATE: ${query}`;
  },
});

console.log("ts-accurate-provider defined. Waiting for auto-start...");
