#!/usr/bin/env npx tsx
/**
 * uc38 ts-signal-consumer — RECOGNIZES the typed supersession signal (#1278).
 *
 * The TypeScript counterpart of py-signal-consumer. Each probe tool calls the
 * provider through an INJECTED McpMeshTool proxy (the real napi/HTTP transport)
 * and classifies the outcome:
 *
 *   - probe_superseded calls reject-superseded. The injected proxy must
 *     recognize the reserved claim_superseded envelope and re-throw the typed
 *     MeshSupersededError, so `e instanceof MeshSupersededError` is true and the
 *     handler reports outcome=superseded. That marker is ONLY reachable if the
 *     typed error was raised.
 *   - probe_generic calls reject-generic (the control). The plain error is NOT
 *     the reserved envelope, so the proxy must NOT re-throw MeshSupersededError;
 *     the handler falls through to the generic branch (outcome=generic).
 *
 * Every probe returns a JSON STRING so the caller parses it uniformly via
 * `content[0].text | fromjson`.
 */

import { FastMCP, mesh, McpMeshTool, MeshSupersededError } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "TsSignalConsumer Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-signal-consumer",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "9204"),
});

agent.addTool({
  name: "probe_superseded",
  capability: "probe-superseded",
  description: "Calls reject-superseded via injected proxy and classifies it",
  dependencies: ["reject-superseded"],
  parameters: z.object({}),
  execute: async (_args, dep: McpMeshTool | null = null) => {
    if (!dep) {
      return JSON.stringify({ outcome: "no_dep" });
    }
    try {
      await dep({});
      return JSON.stringify({ outcome: "no_error" });
    } catch (e) {
      if (e instanceof MeshSupersededError) {
        // Reachable ONLY when the injected proxy recognized the reserved
        // claim_superseded envelope and re-threw the typed error.
        return JSON.stringify({ outcome: "superseded", detail: e.detail });
      }
      return JSON.stringify({
        outcome: "generic",
        error_type: e instanceof Error ? e.name : typeof e,
      });
    }
  },
});

agent.addTool({
  name: "probe_generic",
  capability: "probe-generic",
  description: "Control: calls reject-generic via injected proxy and classifies it",
  dependencies: ["reject-generic"],
  parameters: z.object({}),
  execute: async (_args, dep: McpMeshTool | null = null) => {
    if (!dep) {
      return JSON.stringify({ outcome: "no_dep" });
    }
    try {
      await dep({});
      return JSON.stringify({ outcome: "no_error" });
    } catch (e) {
      if (e instanceof MeshSupersededError) {
        return JSON.stringify({ outcome: "superseded", detail: e.detail });
      }
      // A generic error MUST land here.
      return JSON.stringify({
        outcome: "generic",
        error_type: e instanceof Error ? e.name : typeof e,
      });
    }
  },
});

console.log("ts-signal-consumer agent defined. Waiting for auto-start...");
