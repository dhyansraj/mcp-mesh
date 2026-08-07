/**
 * Mount the Kubernetes startup route (`GET|HEAD /startupz`) on the agent's
 * HTTP server (RFC #1502).
 *
 * Mirrors `livez-route.ts` in mechanism — the route is registered on FastMCP's
 * underlying Hono app, which FastMCP consults before its own built-in health
 * handling — and Python's `/startupz` in `mesh/decorators.py` in semantics.
 *
 * It is a NEW endpoint rather than a reuse of `/livez` because the chart points
 * both `startupProbe` and `livenessProbe` at `/livez`, and an endpoint cannot
 * tell which probe called it. Sharing one would mean a failing startup check
 * kills a running pod every ten seconds.
 *
 * `/livez` is unchanged and stays unconditional. Nothing here may make it
 * consult anything.
 */
import type { FastMCP } from "fastmcp";
import type { MeshStartupCheck } from "./startup-check.js";
import {
  buildStartupBody,
  runStartupCheck,
  startupStatusCodeFor,
} from "./startup-check.js";

/** The configured `startupCheck`, or undefined when there is none. */
export type StartupCheckSource = () => MeshStartupCheck | undefined;

/**
 * Register `GET|HEAD /startupz` on the FastMCP server's Hono app. Returns
 * `true` iff the route was registered. `server.getApp()` throws before the
 * server has started, so this must be called after `server.start()`.
 *
 * Each failure branch logs the CAUSE only. The consequence — that startup is
 * aborted — is stated once, by the caller that throws (see `agent.ts`).
 *
 * `getCheck` is a callback rather than a value for the same reason
 * `registerHealthRoutes` takes one: the route is mounted during startup, and
 * reading the config lazily keeps the two in step.
 */
export function registerStartupzRoute(
  server: FastMCP,
  agentName: string,
  getCheck: StartupCheckSource,
): boolean {
  let app: ReturnType<FastMCP["getApp"]> | null = null;
  try {
    app = server.getApp();
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /startupz route NOT registered — FastMCP.getApp() ` +
        `unavailable: ${reason}`,
    );
    return false;
  }
  if (!app) {
    console.error(
      `[mesh] /startupz route NOT registered — FastMCP.getApp() returned null`,
    );
    return false;
  }

  try {
    app.on(["GET", "HEAD"], "/startupz", async (c) => {
      // Reading the check can throw if `getCheck` reaches into a
      // half-constructed config. That is an indeterminate answer, and an
      // indeterminate answer at boot fails — same rule as a check that
      // throws, and the opposite of `/ready`, which falls back to "no check
      // configured" rather than pulling a working pod out of its Service.
      let check: MeshStartupCheck | undefined;
      try {
        check = getCheck();
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        console.warn(
          `[mesh-startup] reading startupCheck for agent '${agentName}' ` +
            `threw — failing the startup probe: ${reason}`,
        );
        return c.json(
          {
            started: false,
            agent: agentName,
            reason: "Startup check failed",
            errors: [`Startup check could not be read: ${reason}`],
            timestamp: new Date().toISOString(),
          },
          503,
        );
      }

      const verdict = await runStartupCheck(check, agentName);
      return c.json(
        buildStartupBody(agentName, verdict),
        startupStatusCodeFor(verdict),
      );
    });
    return true;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(
      `[mesh] /startupz route NOT registered — app.on() raised: ${reason}`,
    );
    return false;
  }
}
