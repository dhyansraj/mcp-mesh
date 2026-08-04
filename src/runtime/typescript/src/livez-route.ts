/**
 * Mount the Kubernetes liveness route (`GET|HEAD /livez`) on the agent's
 * HTTP server (issue #1467).
 *
 * Mirrors Python's `/livez` in `mesh/decorators.py`, which is served by
 * the framework loop and returns 200 for as long as the process is up.
 *
 * Liveness must be a DIFFERENT signal from readiness: a probe that
 * consults anything the agent depends on (an upstream vendor, the
 * registry, a user health check) turns a dependency outage into a pod
 * restart, which cannot fix the dependency and erases the evidence that
 * the agent was failing. `/livez` therefore answers 200 unconditionally
 * — reaching the handler at all proves the event loop is alive, which is
 * the only thing a restart can repair.
 *
 * FastMCP already serves `/health` and `/ready`; only `/livez` is
 * missing, and it is registered on FastMCP's underlying Hono app (the
 * same mechanism as the MeshJob cancel route — FastMCP consults the Hono
 * router before its own built-in health handling, and there is no path
 * overlap).
 */
import type { FastMCP } from "fastmcp";

/**
 * Register `GET|HEAD /livez` on the FastMCP server's Hono app. Returns
 * `true` iff the route was registered. `server.getApp()` throws before
 * the server has started, so this must be called after
 * `server.start()`.
 *
 * A failure here is loud: with the chart's liveness probe pointing at
 * `/livez`, a missing route 404s and Kubernetes restarts a perfectly
 * healthy agent.
 */
export function registerLivezRoute(server: FastMCP, agentName: string): boolean {
  let app: ReturnType<FastMCP["getApp"]> | null = null;
  try {
    app = server.getApp();
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /livez route NOT registered — FastMCP.getApp() ` +
        `unavailable: ${reason}. A Kubernetes liveness probe pointed at ` +
        `/livez will 404 and restart this agent.`,
    );
    return false;
  }
  if (!app) {
    console.error(
      `[mesh] /livez route NOT registered — FastMCP.getApp() returned ` +
        `null. A Kubernetes liveness probe pointed at /livez will 404 ` +
        `and restart this agent.`,
    );
    return false;
  }

  try {
    app.on(["GET", "HEAD"], "/livez", (c) =>
      c.json({
        alive: true,
        agent: agentName,
        timestamp: new Date().toISOString(),
      }),
    );
    return true;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /livez route NOT registered — app.on() raised: ${reason}. ` +
        `A Kubernetes liveness probe pointed at /livez will 404 and ` +
        `restart this agent.`,
    );
    return false;
  }
}
