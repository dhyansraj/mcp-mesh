#!/usr/bin/env npx tsx
/**
 * header-api - Express API that forwards headers to mesh agents via mesh.route()
 */

import express from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;

app.get("/health", (req, res) => {
  res.json({ status: "healthy" });
});

/**
 * GET /api/echo-headers
 * Uses mesh.route() to call the echo_headers capability.
 * Headers from the incoming HTTP request should propagate through
 * to the downstream agent via the mesh.
 */
app.get(
  "/api/echo-headers",
  mesh.route([{ capability: "echo_headers" }], async (req, res, { echo_headers }) => {
    if (!echo_headers) {
      return res.status(503).json({ error: "echo_headers capability unavailable" });
    }

    try {
      const result = await echo_headers({});
      res.json({ source: "mesh-route", headers: result });
    } catch (err) {
      res.status(500).json({ error: `Call failed: ${err}` });
    }
  })
);

app.listen(PORT, () => {
  console.log(`header-api listening on http://localhost:${PORT}`);
});
