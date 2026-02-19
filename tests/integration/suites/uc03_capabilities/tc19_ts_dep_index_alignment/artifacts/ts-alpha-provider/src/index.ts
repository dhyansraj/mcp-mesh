/**
 * Alpha provider - student lookup capability.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-alpha-provider",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-alpha-provider",
  httpPort: 9063,
});

agent.addTool({
  name: "get_student",
  capability: "student_lookup",
  description: "Look up student information",
  tags: ["student"],
  parameters: z.object({
    id: z.string().describe("Student ID"),
  }),
  execute: async ({ id }) => {
    return { name: "Alice", grade: "A", source: "alpha-provider" };
  },
});

console.log("ts-alpha-provider defined. Waiting for auto-start...");
