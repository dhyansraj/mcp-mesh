/**
 * Schema-test producer (TypeScript) — Employee shape that matches the consumer.
 *
 * Capability: employee_lookup, tags=["good"]
 * Outputs Employee {name, dept, salary} — the canonical cross-runtime shape
 * (sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732).
 */

import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const Employee = z.object({
  name: z.string(),
  dept: z.string(),
  salary: z.number(),
});

const server = new FastMCP({ name: "Producer Good (TS)", version: "1.0.0" });

const agent = mesh(server, {
  name: "producer-good-ts",
  httpPort: 9110,
  description: "Schema-test producer (TypeScript) with matching Employee shape",
});

agent.addTool({
  name: "get_employee",
  capability: "employee_lookup",
  tags: ["good"],
  description: "Return an Employee record (matching shape)",
  parameters: z.object({ employee_id: z.string() }),
  outputSchema: Employee,
  execute: async ({ employee_id: _id }) =>
    JSON.stringify({ name: "Alice", dept: "Engineering", salary: 120000 }),
});
