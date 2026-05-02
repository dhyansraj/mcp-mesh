/**
 * Rogue schema-test producer (TypeScript) — same capability, different shape.
 *
 * Capability: employee_lookup, tags=["bad"]
 * Outputs Hardware {sku, model, price} — schema-aware consumer should evict this
 * (canonical hash sha256:5f1ac9c41f432516a62aebef8841df800fba29342d114eb3813788d16cfa690c).
 */

import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const Hardware = z.object({
  sku: z.string(),
  model: z.string(),
  price: z.number(),
});

const server = new FastMCP({ name: "Producer Bad (TS)", version: "1.0.0" });

const agent = mesh(server, {
  name: "producer-bad-ts",
  httpPort: 9111,
  description: "Schema-test rogue producer (TypeScript) with mismatched Hardware shape",
});

agent.addTool({
  name: "get_hardware",
  capability: "employee_lookup",
  tags: ["bad"],
  description: "Returns Hardware (rogue, mis-registered as employee_lookup)",
  parameters: z.object({ item_id: z.string() }),
  outputSchema: Hardware,
  execute: async ({ item_id: _id }) =>
    JSON.stringify({ sku: "H123", model: "X1 Carbon", price: 1500 }),
});
