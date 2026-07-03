#!/usr/bin/env npx tsx
/**
 * ts-empty-consumer - MCP Mesh Agent
 *
 * Probes empty/null round-trips through the injected mesh proxy (issue #1250).
 *
 * Contract under test: [] -> [], {} -> {}, "" -> "", null -> null.
 * The probe reports EXACTLY what arrived (value_json is compact JSON of the
 * received value) so [] collapsing to "" or null is surfaced, never hidden.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsEmptyConsumer Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-empty-consumer",
  httpPort: 9051,
});

function report(kind: string, value: unknown): string {
  return JSON.stringify({
    kind,
    is_null: value === null,
    is_undefined: value === undefined,
    value_type:
      value === null ? "null" : Array.isArray(value) ? "array" : typeof value,
    value_json: value === undefined ? "undefined" : JSON.stringify(value),
  });
}

agent.addTool({
  name: "probe_roundtrip",
  capability: "empty_probe",
  description: "Call empty_value_source(kind) and report exactly what came back",
  tags: ["empty", "roundtrip"],
  dependencies: ["empty_value_source"],
  parameters: z.object({
    kind: z
      .string()
      .describe(
        "One of: empty_list, empty_dict, empty_string, null_value, nonempty_list"
      ),
  }),
  execute: async (
    { kind },
    source: McpMeshTool | null = null // Positional: dependencies[0]
  ) => {
    if (!source) {
      return JSON.stringify({
        kind,
        error: "dependency empty_value_source not injected",
      });
    }
    const value = await source({ kind });
    return report(kind, value);
  },
});

console.log("ts-empty-consumer agent defined. Waiting for auto-start...");
