#!/usr/bin/env npx tsx
/**
 * Typed Caller - sends typed arguments to provider via dependency injection.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Typed Caller", version: "1.0.0" });
const agent = mesh(server, { name: "typed-caller", httpPort: 0 });

agent.addTool({
  name: "run_task",
  capability: "run_task",
  description: "Send typed arguments to provider",
  dependencies: ["execute_task"],
  parameters: z.object({
    task: z.string().default("greet"),
    name: z.string().default("World"),
    count: z.number().default(1),
  }),
  execute: async (args, execute_task: McpMeshTool | null) => {
    if (!execute_task) return "degraded: execute_task not available";
    return await execute_task({ task: args.task, name: args.name, count: args.count });
  },
});
