#!/usr/bin/env npx tsx
/**
 * ts-required-consumer - MCP Mesh Agent (uc34, issue #1249)
 *
 * Declares ts-req-cap with a REQUIRED dependency on the Python base-cap via
 * the object DependencySpec form { capability, required: true }.
 *
 * Contract under test: the TS SDK must carry required=true on the wire so the
 * registry factors the edge into transitive availability — when base-cap's
 * provider dies, /agents must show ts-req-cap available==false with an
 * unavailable_reason naming base-cap, and flip back once the provider
 * returns. The tool body itself is a trivial probe; tc05's assertions are
 * entirely registry-API driven.
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

// FastMCP server instance
const server = new FastMCP({
  name: "TsRequiredConsumer Service",
  version: "1.0.0",
});

// Wrap with MCP Mesh
const agent = mesh(server, {
  name: "ts-required-consumer",
  httpPort: 9051,
});

agent.addTool({
  name: "ts_required_probe",
  capability: "ts-req-cap",
  description: "Call the required base-cap dependency and report what it said",
  tags: ["required", "probe"],
  dependencies: [{ capability: "base-cap", required: true }],
  parameters: z.object({}),
  execute: async (
    _args,
    baseCap: McpMeshTool | null = null // Positional: dependencies[0]
  ) => {
    if (!baseCap) {
      return JSON.stringify({ error: "base-cap not injected" });
    }
    const result = await baseCap({});
    return JSON.stringify({ status: "ok", base: result });
  },
});

console.log("ts-required-consumer agent defined. Waiting for auto-start...");
