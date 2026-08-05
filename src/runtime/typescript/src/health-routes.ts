/**
 * Mount the mesh-aware readiness and health routes (`GET|HEAD /ready` and
 * `GET|HEAD /health`) on the agent's HTTP server (issue #1478).
 *
 * Until this landed both URLs were FastMCP's own built-ins: `/ready`
 * answered a hardcoded 200 in stateless mode and `/health` returned the
 * literal `text/plain` string `✓ Ok`. A TypeScript provider whose vendor
 * was down therefore kept receiving direct Kubernetes Service traffic
 * long after mesh consumers had failed over (#1468 made `/ready` gate
 * Service endpoints), and an operator who curled `/health` learned
 * nothing. Python (#1472) and Java (#1474) both answer 503 with detail;
 * this is the TypeScript half of that contract.
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
 * ## An agent with no health check is unaffected
 *
 * A null verdict means "no `healthCheck` configured, or the seed run has
 * not finished yet" and is treated as HEALTHY. Only a configured check
 * that reports a non-healthy verdict can make an agent unready.
 *
 * This MATCHES the other two runtimes; it is not a divergence from them:
 *
 *   - Java's `MeshHealthController.effectiveStatus` returns `HEALTHY`
 *     outright when `latest` is null and the runtime is running;
 *   - Python reaches the same answer one step earlier. Its startup seed
 *     stores a default result for an agent with no `health_check` at all
 *     (`{"status": "healthy", ...}` in `fastapiserver_setup.py`), so
 *     `build_ready_response` / `build_health_response` see a stored
 *     healthy status and answer 200. Its no-stored-result branch is
 *     `# No health check configured - assume ready` → 200 as well.
 *
 * Python's `"starting"` 503 in `build_health_response` is NOT the
 * check-less case: it is the window before the seed has stored anything,
 * i.e. an agent that is genuinely still starting. Do not read it as a
 * runtime disagreement and "fix" this branch to match it — that would
 * make every check-less agent, on every runtime, unready.
 *
 * `/livez` is unchanged and stays in `livez-route.ts` — liveness must
 * never consult the verdict, or a vendor outage becomes a pod restart.
 */
import type { FastMCP } from "fastmcp";
import type { HealthVerdict } from "./health-check.js";

/** The latest verdict, or null when there is none. */
export type HealthVerdictSource = () => HealthVerdict | null;

/**
 * Only `healthy` answers 200 — the same rule as Python's
 * `build_health_response` / `build_ready_response` (`200 if status ==
 * "healthy" else 503`) and Java's `MeshHealthController.serving`.
 *
 * So `degraded` answers 503 here while the agent keeps heartbeating and
 * stays in dependency resolution. That asymmetry is deliberate on all
 * three runtimes: readiness is a load-balancer decision about NEW
 * external traffic, while the heartbeat states whether this agent is
 * still a valid provider for the mesh. An impaired agent can honestly
 * say "stop adding load" without withdrawing itself from a mesh that may
 * have no other provider.
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
 * `/ready` body — Python's `build_ready_response` keys.
 *
 * Python varies them per branch: `{ready, agent, status, mcp_wrappers,
 * timestamp}` when ready, `{ready, agent, status, reason, errors}` when
 * not (no `timestamp`), and no `status` at all in its no-stored-result
 * branch. This emits the common keys unconditionally and adds
 * `reason`/`errors` when not ready — again a superset, so nothing a
 * Python-shaped reader looks for is missing.
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
  verdict: HealthVerdict | null,
): Record<string, unknown> {
  const status = verdict ? verdict.status : "healthy";
  const ready = serving(status);
  const body: Record<string, unknown> = {
    ready,
    agent: agentName,
    status,
    mcp_wrappers: 1,
    timestamp: new Date().toISOString(),
  };
  if (!ready) {
    body.reason = `Service is ${status}`;
    body.errors = verdict ? verdict.errors : [];
  }
  return body;
}

/** HTTP status for a verdict: 200 healthy, 503 otherwise. */
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
 * `getVerdict` is a callback rather than a value because the routes are
 * mounted during startup, before the health-check loop has produced (or
 * even been started with) anything.
 */
export function registerHealthRoutes(
  server: FastMCP,
  agentName: string,
  getVerdict: HealthVerdictSource,
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
  // A verdict source that THROWS must not take the endpoint down with
  // it: a probe that cannot answer is not evidence the agent is broken,
  // and a 500 here would fail the readiness probe and pull a working pod
  // out of the Service. Falling back to null answers exactly as an agent
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

  try {
    app.on(["GET", "HEAD"], "/ready", (c) => {
      const verdict = snapshot();
      return c.json(buildReadyBody(agentName, verdict), statusCodeFor(verdict));
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
