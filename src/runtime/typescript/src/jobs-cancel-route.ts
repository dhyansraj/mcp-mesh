/**
 * Mount the cancel HTTP route on the agent's HTTP server (Phase 1 —
 * MeshJob substrate).
 *
 * Mirrors Python's
 * `_mcp_mesh.pipeline.mcp_startup.jobs_cancel_route.JobsCancelRouteStep`.
 *
 * Per `MESHJOB_DESIGN.org` "Wire Protocol / New endpoints" /
 * "Cancellation": when the registry receives a cancel request for a
 * job whose owner is alive, it forwards the call to the owner
 * replica's `POST /jobs/{job_id}/cancel` HTTP route. That route fires
 * the in-process cancel token registered by the inbound tool wrapper
 * (or the claim worker) so any outbound HTTP calls under the active
 * `with_job_async` scope abort.
 *
 * The route is registered on FastMCP's underlying Hono app. FastMCP
 * exposes the Hono instance via `server.getApp()` after the server has
 * started; calling that BEFORE start would throw. We register at the
 * front of the routes table so the explicit `/jobs/:job_id/cancel`
 * matches before any catch-all FastMCP routes (Hono matches routes in
 * registration order by default, so calling `app.post(...)` after the
 * server starts is sufficient — Hono inserts at the end, but the
 * FastMCP catch-alls only match the configured `endpoint` path which
 * defaults to `/mcp` — there's no overlap).
 */
import type { FastMCP } from "fastmcp";
import { cancelActiveJob } from "@mcpmesh/core";

/**
 * Register `POST /jobs/:job_id/cancel` on the FastMCP server's Hono
 * app. Returns `true` iff the route was registered (i.e. the FastMCP
 * server exposes a Hono instance). Logs a warning and returns `false`
 * on any failure — cancel is a best-effort signal; missing the route
 * just means the registry's forward attempt 404s and the cancel
 * falls back to lease-expiry.
 */
export function registerCancelRoute(server: FastMCP): boolean {
  let app: ReturnType<FastMCP["getApp"]> | null = null;
  try {
    app = server.getApp();
  } catch (err) {
    console.warn(
      "[mesh-jobs] FastMCP.getApp() unavailable — cancel route not registered:",
      err,
    );
    return false;
  }
  if (!app) {
    console.warn(
      "[mesh-jobs] FastMCP.getApp() returned null — cancel route not registered",
    );
    return false;
  }

  try {
    app.post("/jobs/:job_id/cancel", async (c) => {
      const jobId = c.req.param("job_id");
      let cancelled = false;
      try {
        cancelled = Boolean(cancelActiveJob(jobId));
      } catch (err) {
        // The napi binding shouldn't throw under normal conditions;
        // log + report cancelled=false so the registry's forwarder
        // gets a deterministic answer.
        console.warn(
          `[mesh-jobs] cancelActiveJob napi raised for job=${jobId}:`,
          err,
        );
      }
      console.log(
        `[mesh-jobs] cancel route: job_id=${jobId} cancelled=${cancelled}`,
      );
      return c.json({ cancelled, job_id: jobId });
    });
    return true;
  } catch (err) {
    console.warn("[mesh-jobs] failed to register cancel route:", err);
    return false;
  }
}
