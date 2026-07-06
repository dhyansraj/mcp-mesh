#!/usr/bin/env npx tsx
/**
 * ts-svc-producer — TYPESCRIPT producer sugar (RFC #1280 phase 3, uc37 tc12).
 *
 * `agent.addService("tssvc", {...})` publishes each entry (name-sorted) as an
 * ordinary mesh tool with a DOTTED capability (tssvc.alpha, tssvc.bravo)
 * through the existing addTool machinery — the TS twin of
 * java-view-producer's `@McpMeshService("svc")` and py-svc-producer's
 * `@mesh.service("pysvc")`.
 *
 * Payloads are self-identifying (agent + capability) so tc12's direct
 * `meshctl call tssvc.<m>` assertions prove serving + routing, not just
 * registration. Methods take no meaningful args (permissive default schema)
 * so `'{}'` calls work.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";

const server = new FastMCP({
  name: "TsSvcProducer Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-svc-producer",
  httpPort: 9402,
});

agent.addService("tssvc", {
  alpha: async () =>
    JSON.stringify({
      agent: "ts-svc-producer",
      cap: "tssvc.alpha",
      msg: "hello-from-tssvc-alpha",
    }),
  bravo: async () =>
    JSON.stringify({
      agent: "ts-svc-producer",
      cap: "tssvc.bravo",
      msg: "hello-from-tssvc-bravo",
    }),
});

console.log("ts-svc-producer agent defined. Waiting for auto-start...");
