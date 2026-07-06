#!/usr/bin/env npx tsx
/**
 * ts-view-consumer — TYPESCRIPT service view consuming the JAVA producer
 * (RFC #1280 cross-runtime seam, uc37 tc11).
 *
 * `mesh.serviceView(...)` occupies ONE dependencies slot but expands into two
 * ordinary edges (name-sorted) binding java-view-producer's dotted svc.*
 * capabilities. `bravo` is required=true: a TS view is a TOOL-PARAMETER
 * surface, so the edge is an ordinary tool dependency slot and participates
 * in the issue #1273 pre-invoke guard — calling `ts_view_report` while
 * svc.bravo is unresolved is refused with the structured
 * `{"error":"dependency_unavailable","capability":"svc.bravo"}` result
 * BEFORE execute runs (envelope parity with the Java/Python tool-param
 * paths, tc06/tc10).
 *
 * The report mirrors the suite's flat shape: `<method>_agent`/`<method>_cap`
 * on success, `<method>_error`/`<method>_error_message` on failure.
 */

import { FastMCP, mesh, type MeshServiceFacade } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "TsViewConsumer Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-view-consumer",
  httpPort: 9401,
});

const SvcView = mesh.serviceView({
  name: "SvcView",
  methods: {
    alpha: "svc.alpha",
    bravo: { capability: "svc.bravo", required: true },
  },
});

agent.addTool({
  name: "ts_view_report",
  capability: "ts_view_report",
  description:
    "Call both SvcView methods (Java svc.* producer) and report which agent served each",
  dependencies: [SvcView],
  parameters: z.object({}),
  execute: async (
    _args,
    viewDep: unknown = null, // Positional: dependencies[0] (ONE slot, two edges)
  ) => {
    // The SDK's execute dep union is (McpMeshTool | MeshJob | null); facades
    // arrive through the same positional slot, so type via cast — the same
    // pattern the SDK's own service-view spec uses.
    const view = viewDep as MeshServiceFacade<typeof SvcView> | null;
    const out: Record<string, unknown> = {};
    if (!view) {
      return JSON.stringify({ error: "view not injected" });
    }
    for (const name of ["alpha", "bravo"] as const) {
      try {
        const payload = (await view[name]({})) as Record<string, unknown> | null;
        out[`${name}_agent`] = payload?.agent;
        out[`${name}_cap`] = payload?.cap;
      } catch (e) {
        out[`${name}_error`] = e instanceof Error ? e.name : "unknown";
        out[`${name}_error_message`] = e instanceof Error ? e.message : String(e);
      }
    }
    return JSON.stringify(out);
  },
});

console.log("ts-view-consumer agent defined. Waiting for auto-start...");
