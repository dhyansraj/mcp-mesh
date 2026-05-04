/**
 * TypeScript streaming gateway for cross-runtime tests (issue #854 Phase A).
 *
 * Exposes POST /plan, which is wired to the "trip_planning" mesh capability
 * via mesh.route(). The injected proxy's `.stream()` returns an
 * AsyncIterable<string>; we hand it to mesh.sseStream(res, ...) which
 * frames each chunk as `data: <chunk>\n\n` and terminates with
 * `data: [DONE]\n\n`, matching the Python @mesh.route SSE adapter and
 * the Java MeshSse helper.
 *
 * GET /health is intentionally non-streaming so we can verify the route
 * coexists with the SSE endpoint.
 */
import express from "express";
import type { Request, Response } from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

app.post(
  "/plan",
  mesh.route(
    [{ capability: "trip_planning" }],
    async (req: Request, res: Response, { trip_planning }) => {
      if (!trip_planning) {
        res.status(503).json({ error: "trip_planning unavailable" });
        return;
      }
      try {
        await mesh.sseStream(res, trip_planning.stream(req.body));
      } catch (err) {
        if (!res.headersSent) {
          res.status(500).json({ error: String(err) });
        }
      }
    }
  )
);

const port = parseInt(process.env.PORT ?? "8090", 10);
app.listen(port, () => {
  console.log(`TS streaming gateway on :${port}`);
});
