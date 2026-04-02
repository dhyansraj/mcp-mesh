#!/usr/bin/env npx tsx
/**
 * Typed Provider - receives typed arguments and executes tasks.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Typed Provider", version: "1.0.0" });
const agent = mesh(server, { name: "typed-provider", httpPort: 0 });

agent.addTool({
  name: "execute_task",
  capability: "execute_task",
  description: "Execute a task from typed arguments",
  parameters: z.object({
    task: z.string().default("greet"),
    name: z.string().default("World"),
    count: z.number().default(1),
  }),
  execute: async (args) => {
    if (args.task === "greet") {
      return Array(args.count).fill(`Hello ${args.name}!`).join("");
    }
    return `unknown task: ${args.task}`;
  },
});
