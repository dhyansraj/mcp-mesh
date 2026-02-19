/**
 * Beta provider - schedule lookup capability.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-beta-provider",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-beta-provider",
  httpPort: 9064,
});

agent.addTool({
  name: "get_schedule",
  capability: "schedule_lookup",
  description: "Look up class schedule",
  tags: ["schedule"],
  parameters: z.object({
    id: z.string().describe("Student ID"),
  }),
  execute: async ({ id }) => {
    return [
      { day: "Monday", class: "Math" },
      { day: "Wednesday", class: "Art" },
    ];
  },
});

console.log("ts-beta-provider defined. Waiting for auto-start...");
