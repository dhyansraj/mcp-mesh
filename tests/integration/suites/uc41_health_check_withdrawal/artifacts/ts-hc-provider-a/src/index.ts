#!/usr/bin/env npx tsx
/**
 * ts-hc-provider-a — the provider whose health check the test drives (#1480).
 *
 * TypeScript twin of py-hc-provider-a. Same contract, same flag file, same
 * trace file: the three runtimes are meant to be behaviourally identical
 * here, and divergence is exactly what keeps getting found.
 *
 * ## File-toggled, not invocation-counting
 *
 * `healthCheck` re-reads `/workspace/health-flag` on every tick so the test
 * controls WHEN the transition happens and can poll for it:
 *
 *   ok (or file absent) -> healthy    heartbeats, stays resolvable
 *   fail                -> unhealthy  heartbeat suppressed -> registry withdraws
 *   throw               -> throws     must map to DEGRADED, must NOT withdraw
 *
 * ## Every invocation is traced
 *
 * One line is appended to `/workspace/hc-invocations.log` BEFORE the throw
 * branch throws. Without it the negative test would pass vacuously: a health
 * check that stopped running also fails to withdraw the agent, and "the
 * agent is still resolvable" cannot tell that apart from the behaviour we
 * actually want.
 *
 * Reads are sync on purpose. This is a test fixture: an async read would add
 * a scheduling hop between "the test wrote the flag" and "the check saw it",
 * for no coverage.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { appendFileSync, readFileSync } from "node:fs";
import { z } from "zod";

const AGENT_NAME = "hc-provider-a-ts";
const FLAG_FILE = process.env.HC_FLAG_FILE ?? "/workspace/health-flag";
const TRACE_FILE = process.env.HC_TRACE_FILE ?? "/workspace/hc-invocations.log";

const server = new FastMCP({
  name: "HC Provider A (typescript)",
  version: "1.0.0",
});

/** Current fault state. A missing file means healthy, so the agent boots green. */
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

const agent = mesh(server, {
  name: AGENT_NAME,
  version: "1.0.0",
  description:
    "Provider whose health check withdraws it from resolution (#1480)",
  httpPort: Number(process.env.MCP_MESH_HTTP_PORT ?? "3421"),
  healthCheck: () => {
    const flag = readFlag();

    if (flag === "fail") {
      trace(flag, "unhealthy");
      return {
        status: "unhealthy",
        checks: { vendor_api_reachable: false },
        errors: ["simulated vendor outage (health-flag=fail)"],
      };
    }

    if (flag === "throw") {
      // Traced BEFORE throwing — see the file header.
      trace(flag, "raised");
      throw new Error("simulated broken health check (health-flag=throw)");
    }

    trace(flag, "healthy");
    return {
      status: "healthy",
      checks: { vendor_api_reachable: true },
    };
  },
  // 2s so a withdrawal costs ~1 TTL + the registry staleness window rather
  // than the 15s default; the test's registry runs at a matching 5s/2s.
  healthCheckTtl: 2,
});

agent.addTool({
  name: "probe_a",
  capability: "hc_probe_ts",
  description: "Report which provider instance served this call",
  tags: ["hc-withdrawal"],
  parameters: z.object({}),
  // pid is self-reported from inside the process, so it cannot go stale the
  // way a pid FILE can. Baseline and post-recovery answers carrying the same
  // pid is the proof that recovery did not restart anything.
  execute: async () =>
    JSON.stringify({ served_by: AGENT_NAME, pid: process.pid }),
});

console.log(`${AGENT_NAME} defined. Waiting for auto-start...`);
