/**
 * TypeScript API Port Isolation Test App
 *
 * A minimal Express app with mesh.route but NO mesh() agent registration.
 * Used to verify MCP_MESH_HTTP_PORT does NOT override Express port
 * for API-type apps (apps with mesh.route but no mesh() agent).
 *
 * Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/658
 */

import express from "express";

const app = express();
app.use(express.json());

app.get("/ping", (req, res) => {
  res.json({ message: "pong" });
});

app.get("/health", (req, res) => {
  res.json({ status: "healthy" });
});

const port = 8080;
app.listen(port, () => {
  console.log(`API app listening on port ${port}`);
});
