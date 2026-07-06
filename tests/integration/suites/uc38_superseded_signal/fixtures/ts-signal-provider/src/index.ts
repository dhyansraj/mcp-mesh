#!/usr/bin/env npx tsx
/**
 * uc38 ts-signal-provider — emits the typed supersession signal (issue #1278).
 *
 * The TypeScript counterpart of py-signal-provider: it proves the EMIT half of
 * the emit->wire->recognize plumbing over the REAL napi/HTTP transport. Three
 * capabilities:
 *
 *   - reject-superseded: UNCONDITIONALLY throws MeshSupersededError. It extends
 *     fastmcp's UserError, so the existing tool-error path emits an isError
 *     result whose text is the reserved envelope
 *     {"error":"claim_superseded","detail":...}. Increments an in-process
 *     counter BEFORE throwing so the caller can assert single-invoke.
 *   - reject-generic: the CONTROL — throws a plain UserError whose message is
 *     NOT the reserved envelope.
 *   - superseded-call-count: reports how many times reject-superseded ran.
 *
 * Rejects unconditionally on purpose: this proves the framework plumbing, not
 * the epoch-supersession app logic.
 */

import { FastMCP, mesh, MeshSupersededError } from "@mcpmesh/sdk";
import { UserError } from "fastmcp";
import { z } from "zod";

const server = new FastMCP({
  name: "TsSignalProvider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-signal-provider",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "9203"),
});

// In-process invocation counter. A double-invoke on the real transport would
// push this past 1.
let rejectSupersededCalls = 0;

agent.addTool({
  name: "reject_superseded",
  capability: "reject-superseded",
  description: "Unconditionally rejects the caller as superseded (issue #1278)",
  parameters: z.object({}),
  execute: async () => {
    rejectSupersededCalls += 1;
    throw new MeshSupersededError("stale epoch: caller superseded");
  },
});

agent.addTool({
  name: "reject_generic",
  capability: "reject-generic",
  description: "Control: fails with a generic (non-superseded) error",
  parameters: z.object({}),
  execute: async () => {
    // Plain UserError whose message is NOT the reserved envelope.
    throw new UserError("generic-provider-failure: this is NOT a supersession");
  },
});

agent.addTool({
  name: "get_reject_count",
  capability: "superseded-call-count",
  description: "Reports how many times reject-superseded was invoked",
  parameters: z.object({}),
  execute: async () => {
    return JSON.stringify({ count: rejectSupersededCalls });
  },
});

console.log("ts-signal-provider agent defined. Waiting for auto-start...");
