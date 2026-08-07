/**
 * Mount the mesh-aware readiness and health routes (`GET|HEAD /ready` and
 * `GET|HEAD /health`) on the agent's HTTP server (issue #1478).
 *
 * Until this landed both URLs were FastMCP's own built-ins: `/ready`
 * answered a hardcoded 200 in stateless mode and `/health` returned the
 * literal `text/plain` string `✓ Ok`, so an operator who curled `/health`
 * learned nothing about the agent. Python (#1472) and Java (#1474) both
 * carry the verdict with detail; this is the TypeScript half of that
 * contract.
 *
 * ## What each endpoint reports (RFC #1502)
 *
 * `/ready` reports whether the **mesh runtime** is up, and nothing else.
 * `/health` reports the user's `healthCheck` verdict — 200 only while it
 * is `healthy` — and nothing probes it. The two therefore DIVERGE on
 * every agent type, deliberately.
 *
 * A failing check already withdraws the agent by pausing the heartbeat:
 * the registry ages it out and resolution stops selecting it. Adding
 * readiness on top is strictly worse rather than defence in depth,
 * because mesh traffic traverses the Kubernetes Service — `advertisedHost`
 * defaults to the per-agent Service DNS name. A 503 here empties the
 * Service endpoints while the registry may still be selecting the agent,
 * and the consumer gets a connection error instead of failing over.
 *
 * Readiness is not unconditional either. `startupCheck` defaults to
 * passing, so `/startupz` answers 200 before the runtime is up; without
 * the runtime floor a pod could go Ready with no mesh runtime behind it.
 * The floor is also the only probe that notices a runtime that dies while
 * the process lives, since `/livez` consults nothing.
 *
 * This matches `express.ts`, whose gateway `/ready` has always been
 * `this.handle !== null`, and Python's `runtime_state`.
 *
 * ## Why registering here shadows FastMCP
 *
 * `server.getApp()` returns FastMCP's Hono app, and FastMCP matches Hono
 * routes FIRST — its built-in health handling only runs after the
 * "Hono route not matched" catch. So a route registered here wins, which
 * is the same mechanism `/livez` (#1467) and the MeshJob cancel route
 * already rely on.
 *
 * ## Owning /ready also removes a latent trap
 *
 * FastMCP's built-in `/ready` returns **503 when `totalSessions === 0`**
 * in stateful mode. Mesh escapes that today only because `agent.ts`
 * starts FastMCP with `stateless: true`, where the built-in is hardcoded
 * 200 — flipping that flag would have silently made every TypeScript
 * agent unready in Kubernetes until the first session arrived. Owning
 * the route removes the dependency on that flag entirely.
 *
 * ## An agent with no health check is unaffected on /health
 *
 * A null verdict means "no `healthCheck` configured, or the seed run has
 * not finished yet" and is treated as HEALTHY, so `/health` answers 200.
 * Only a configured check that reports a non-healthy verdict can make it
 * 503. Java's `MeshHealthController.effectiveStatus` returns `HEALTHY`
 * outright when `latest` is null and the runtime is running, and Python's
 * startup seed stores a default healthy result for an agent with no
 * `health_check` at all.
 *
 * `/livez` is unchanged and stays in `livez-route.ts` — liveness must
 * never consult the verdict, or a vendor outage becomes a pod restart.
 */
import type { FastMCP } from "fastmcp";
import type { HealthVerdict } from "./health-check.js";

/** The latest verdict, or null when there is none. */
export type HealthVerdictSource = () => HealthVerdict | null;

/**
 * Whether the mesh runtime is up, and in what state.
 *
 * `up` once `startAgent()` has returned a napi handle; `shutting_down`
 * once shutdown has been requested; `starting` before either. The same
 * three states Python's `runtime_state` reports, minus `standalone` —
 * TypeScript has no standalone mode, `_autoStart` always calls
 * `startAgent`.
 */
export type RuntimeState = "up" | "starting" | "shutting_down";

/** Reads the runtime state at request time (see `snapshot` below). */
export type RuntimeStateSource = () => RuntimeState;

const NOT_READY_REASON: Record<string, string> = {
  starting: "Mesh runtime has not started yet",
  shutting_down: "Mesh runtime is shutting down",
};

/**
 * Only `healthy` answers 200 on `/health` — the same rule as Python's
 * `build_health_response` (`200 if status == "healthy" else 503`) and
 * Java's `MeshHealthController.serving`.
 *
 * So `degraded` answers 503 there while the agent keeps heartbeating and
 * stays in dependency resolution. Nothing probes `/health`, so the status
 * code is free to carry the verdict; `/ready`, which the kubelet does
 * read, is governed by the runtime state alone.
 */
function serving(status: string): boolean {
  return status === "healthy";
}

/**
 * `/health` body — the `{status, agent, checks, errors, timestamp}` shape
 * Python stores and returns for a configured `health_check`
 * (`fastapiserver_setup.py` builds exactly those five keys, and
 * `build_health_response` returns the stored dict verbatim).
 *
 * The three runtimes agree on that shape but not on what they OMIT when
 * there is no verdict to report: Python's check-less default result
 * carries only `status`/`agent`/`timestamp`, and Java's `/health` adds
 * `checks`/`errors`/`timestamp` only when a result exists. This always
 * emits all five, with `checks: {}` and `errors: []` — a superset, so a
 * reader written against any of the three still parses it.
 */
export function buildHealthBody(
  agentName: string,
  verdict: HealthVerdict | null,
): Record<string, unknown> {
  return {
    status: verdict ? verdict.status : "healthy",
    agent: agentName,
    checks: verdict ? verdict.checks : {},
    errors: verdict ? verdict.errors : [],
    timestamp: new Date().toISOString(),
  };
}

/**
 * `/ready` body — Python's `build_ready_response` keys: `{ready, agent,
 * runtime, mcp_wrappers, timestamp}`, plus `reason` when not ready.
 *
 * There is deliberately no `status` key carrying the health verdict. It
 * used to be here, and beside a 200 it now reads as a contradiction
 * rather than as two separate facts — exactly the conflation RFC #1502
 * exists to undo. The verdict is on `/health`.
 *
 * `mcp_wrappers` counts the MCP servers this agent fronts. A TypeScript
 * agent wraps exactly one FastMCP server, so the honest constant is 1.
 * Python's helper takes an `mcp_wrappers_count` parameter, but its only
 * wired call site (`mesh/decorators.py`) passes none, so Python reports
 * 0 in practice — do NOT treat that 0 as a contract to copy. The field
 * is kept rather than dropped because operators and dashboards read one
 * key set across the runtimes.
 */
export function buildReadyBody(
  agentName: string,
  state: RuntimeState,
): Record<string, unknown> {
  const ready = state === "up";
  const body: Record<string, unknown> = {
    ready,
    agent: agentName,
    runtime: state,
    mcp_wrappers: 1,
    timestamp: new Date().toISOString(),
  };
  if (!ready) {
    body.reason = NOT_READY_REASON[state] ?? `Mesh runtime is ${state}`;
  }
  return body;
}

/** HTTP status for `/ready`: 200 once the mesh runtime is up. */
export function readyStatusCodeFor(state: RuntimeState): 200 | 503 {
  return state === "up" ? 200 : 503;
}

/** HTTP status for `/health`: 200 healthy, 503 otherwise. */
export function statusCodeFor(verdict: HealthVerdict | null): 200 | 503 {
  return serving(verdict ? verdict.status : "healthy") ? 200 : 503;
}

/**
 * Register `GET|HEAD /ready` and `GET|HEAD /health` on the FastMCP
 * server's Hono app. Returns `true` iff BOTH routes were registered.
 * `server.getApp()` throws before the server has started, so this must
 * be called after `server.start()`.
 *
 * Each failure branch logs the CAUSE only. The consequence is stated
 * once, by the caller that throws (see `agent.ts`).
 *
 * `getVerdict` and `getRuntimeState` are callbacks rather than values
 * because the routes are mounted during startup — before the health-check
 * loop has produced anything, and before `startAgent()` has returned a
 * handle. A `/ready` that captured either at registration would answer the
 * boot value forever.
 */
export function registerHealthRoutes(
  server: FastMCP,
  agentName: string,
  getVerdict: HealthVerdictSource,
  getRuntimeState: RuntimeStateSource,
): boolean {
  let app: ReturnType<FastMCP["getApp"]> | null = null;
  try {
    app = server.getApp();
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /ready and /health routes NOT registered — FastMCP.getApp() ` +
        `unavailable: ${reason}`,
    );
    return false;
  }
  if (!app) {
    console.error(
      `[mesh] /ready and /health routes NOT registered — FastMCP.getApp() ` +
        `returned null`,
    );
    return false;
  }

  // ONE snapshot per request. `getVerdict()` is rewritten by the
  // health-check loop between calls, so reading it twice while building a
  // response can mix two verdicts — a body whose `status` came from one
  // and whose `errors` came from the next, or a 200 status line over an
  // unhealthy body. Java's `latestResult()` exists for the same reason.
  //
  // A verdict source that THROWS must not take `/health` down with it: a
  // diagnostic endpoint that 500s tells an operator less than one that
  // says "no verdict". Falling back to null answers exactly as an agent
  // with no health check does.
  const snapshot = (): HealthVerdict | null => {
    try {
      return getVerdict();
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      console.warn(
        `[mesh-health] reading the health verdict for agent '${agentName}' ` +
          `threw — answering as if no health check were configured: ${reason}`,
      );
      return null;
    }
  };

  // Same containment as `snapshot`, for the same reason: a runtime-state
  // source that throws must not 500 the readiness probe. `starting` is the
  // conservative answer — it 503s, which is what an agent whose state
  // cannot be determined should report to a load balancer, and unlike the
  // verdict path there is no "as if unconfigured" reading that is safe.
  const runtimeSnapshot = (): RuntimeState => {
    try {
      return getRuntimeState();
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      console.warn(
        `[mesh-health] reading the mesh runtime state for agent ` +
          `'${agentName}' threw — reporting not ready: ${reason}`,
      );
      return "starting";
    }
  };

  try {
    app.on(["GET", "HEAD"], "/ready", (c) => {
      // RFC #1502: the mesh runtime, NOT the health verdict. See the module
      // comment for why adding the verdict here is worse than leaving it out.
      const state = runtimeSnapshot();
      return c.json(buildReadyBody(agentName, state), readyStatusCodeFor(state));
    });
    app.on(["GET", "HEAD"], "/health", (c) => {
      const verdict = snapshot();
      return c.json(buildHealthBody(agentName, verdict), statusCodeFor(verdict));
    });
    return true;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /ready and /health routes NOT registered — app.on() raised: ` +
        `${reason}`,
    );
    return false;
  }
}
