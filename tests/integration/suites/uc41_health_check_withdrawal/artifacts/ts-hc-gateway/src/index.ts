#!/usr/bin/env npx tsx
/**
 * ts-hc-gateway — a ROUTE (api) agent whose health check withdraws it from
 * discovery (RFC #1502 step 3).
 *
 * Every other artifact in uc41 is a plain MCP provider, which is the whole
 * gap this one fills: a gateway used to be exempt from the health check
 * entirely — TypeScript printed "healthCheck is IGNORED on MeshExpress" and
 * did nothing — on the grounds that withdrawing a fan-out point takes the
 * application down. Step 2 removed that harm, so the exemption is gone.
 *
 * ## What this agent has to prove
 *
 * A withdrawn gateway stops being DISCOVERED and nothing else:
 *
 *   - the registry marks it unhealthy (the heartbeat stopped),
 *   - `/livez` and `/ready` keep answering 200, so Kubernetes keeps it in its
 *     Service endpoints,
 *   - `GET /ingress` keeps answering, in the SAME process, throughout.
 *
 * The ingress route is a plain Express handler with no mesh dependencies, on
 * purpose. `mesh.route([...deps])` auto-starts the singleton `ApiRuntime` in
 * addition to `meshExpress`, which would register a SECOND agent from this one
 * process and leave the test asserting against an ambiguous registry. What is
 * under test here is the gateway's own heartbeat, and `meshExpress` is the only
 * TypeScript surface that can carry a `healthCheck` at all.
 *
 * ## File-toggled, not invocation-counting
 *
 * Same contract as the provider artifacts, so the two are comparable:
 *
 *   ok (or file absent) -> healthy    heartbeats, stays discoverable
 *   fail                -> unhealthy  heartbeat suppressed -> registry withdraws
 *   throw               -> throws     must map to DEGRADED, must NOT withdraw
 *
 * Its own flag and trace files: this gateway may run alongside the provider
 * artifacts, and sharing a flag would make one test's fault another's.
 */

import express, { type Request, type Response } from "express";
import { meshExpress } from "@mcpmesh/sdk";
import { appendFileSync, readFileSync } from "node:fs";

const AGENT_NAME = "hc-gateway-ts";
const FLAG_FILE = process.env.HC_FLAG_FILE ?? "/workspace/gateway-health-flag";
const TRACE_FILE =
  process.env.HC_TRACE_FILE ?? "/workspace/hc-gateway-invocations.log";

/** Current fault state. A missing file means healthy, so the gateway boots green. */
function readFlag(): string {
  try {
    return readFileSync(FLAG_FILE, "utf8").trim().toLowerCase() || "ok";
  } catch {
    return "ok";
  }
}

/** Best-effort: a trace write that fails must not change the verdict. */
function trace(flag: string, verdict: string): void {
  try {
    appendFileSync(
      TRACE_FILE,
      `${new Date().toISOString()} agent=${AGENT_NAME} flag=${flag} verdict=${verdict}\n`,
    );
  } catch {
    /* ignore */
  }
}

const app = express();
app.use(express.json());

// The ingress. pid is self-reported from inside the process, so an answer
// during the outage proves the SAME process is still serving — withdrawn is
// not dead, and for a gateway that is the entire point.
app.get("/ingress", (_req: Request, res: Response) => {
  res.json({ served_by: AGENT_NAME, pid: process.pid });
});

const meshApp = meshExpress(app, {
  name: AGENT_NAME,
  version: "1.0.0",
  description: "Route gateway whose health check withdraws it (RFC #1502)",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "3431"),
  healthCheck: () => {
    const flag = readFlag();

    if (flag === "fail") {
      trace(flag, "unhealthy");
      return {
        status: "unhealthy",
        checks: { upstream_reachable: false },
        errors: ["simulated upstream outage (health-flag=fail)"],
      };
    }

    if (flag === "throw") {
      // Traced BEFORE throwing — see the provider artifacts' header.
      trace(flag, "raised");
      throw new Error("simulated broken health check (health-flag=throw)");
    }

    trace(flag, "healthy");
    return {
      status: "healthy",
      checks: { upstream_reachable: true },
    };
  },
  // 2s so a withdrawal costs ~1 TTL + the registry staleness window rather
  // than the 15s default; the test's registry runs at a matching 5s/2s.
  healthCheckTtl: 2,
});

meshApp.start().catch((err) => {
  console.error(`${AGENT_NAME} failed to start:`, err);
  process.exit(1);
});

console.log(`${AGENT_NAME} starting...`);
