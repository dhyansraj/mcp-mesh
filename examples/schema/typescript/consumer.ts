/**
 * Schema-aware consumer (TypeScript).
 *
 * Depends on capability `employee_lookup` with subset-mode schema check
 * (expectedSchema=Employee). Producer-good wires; producer-bad (Hardware) is
 * evicted by the schema stage. Cross-runtime: also wires to Python/Java
 * producer-good because they declare the same canonical Employee hash.
 */

import { FastMCP } from "fastmcp";
import { mesh, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const Employee = z.object({
  name: z.string(),
  dept: z.string(),
  salary: z.number(),
});

const server = new FastMCP({ name: "Consumer (TS)", version: "1.0.0" });

const agent = mesh(server, {
  name: "consumer-ts",
  httpPort: 9112,
  description: "Schema-aware consumer (TypeScript) for issue #547 cross-runtime tests",
});

agent.addTool({
  name: "lookup_with_schema",
  capability: "schema_aware_lookup_ts",
  description: "Schema-aware consumer (subset mode) — TypeScript",
  parameters: z.object({ emp_id: z.string() }),
  dependencies: [
    {
      capability: "employee_lookup",
      expectedSchema: Employee,
      matchMode: "subset",
    },
  ],
  execute: async ({ emp_id }, lookup: McpMeshTool | null = null) => {
    if (!lookup) return `no compatible producer for ${emp_id}`;
    const result = await lookup({ employee_id: emp_id });
    return `got: ${JSON.stringify(result)}`;
  },
});
