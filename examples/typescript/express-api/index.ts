/**
 * Express API Example - Consumes MCP Mesh Capabilities
 *
 * This Express app demonstrates mesh.route() integration by exposing
 * REST endpoints that delegate to mesh agents (calculator, greeter).
 *
 * Run with:
 *   npm install
 *   npm start
 *
 * Requirements:
 *   - Registry running on port 8000
 *   - Calculator agent running (provides: add, subtract, multiply, divide)
 *   - Greeter agent running (provides: greet, greet-lucky, greet-age, greet-math)
 */

import express, { Request, Response } from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;

// ============================================================================
// Health & Info Endpoints
// ============================================================================

app.get("/", (req, res) => {
  res.json({
    name: "Express API with MCP Mesh",
    description: "REST API consuming mesh capabilities",
    endpoints: {
      calculator: {
        "POST /api/add": "Add two numbers",
        "POST /api/subtract": "Subtract two numbers",
        "POST /api/multiply": "Multiply two numbers",
        "POST /api/divide": "Divide two numbers",
      },
      greeter: {
        "POST /api/greet": "Simple greeting",
        "POST /api/greet/lucky": "Greeting with lucky number",
        "POST /api/greet/age": "Greeting with age calculation",
        "POST /api/greet/math": "Greeting with math facts",
      },
    },
  });
});

app.get("/health", (req, res) => {
  res.json({ status: "healthy", timestamp: new Date().toISOString() });
});

// ============================================================================
// Calculator Endpoints (consume: add, subtract, multiply, divide)
// ============================================================================

/**
 * POST /api/add
 * Body: { "a": number, "b": number }
 */
app.post(
  "/api/add",
  mesh.route([{ capability: "add" }], async (req, res, [add]) => {
    if (!add) {
      res.status(503).json({ error: "Calculator service unavailable" });
      return;
    }

    const { a, b } = req.body;
    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Parameters 'a' and 'b' must be numbers" });
      return;
    }

    try {
      const result = await add({ a, b });
      res.json({ operation: "add", a, b, result: parseFloat(String(result)) });
    } catch (err) {
      res.status(500).json({ error: `Calculation failed: ${err}` });
    }
  })
);

/**
 * POST /api/subtract
 * Body: { "a": number, "b": number }
 */
app.post(
  "/api/subtract",
  mesh.route([{ capability: "subtract" }], async (req, res, [subtract]) => {
    if (!subtract) {
      res.status(503).json({ error: "Calculator service unavailable" });
      return;
    }

    const { a, b } = req.body;
    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Parameters 'a' and 'b' must be numbers" });
      return;
    }

    try {
      const result = await subtract({ a, b });
      res.json({ operation: "subtract", a, b, result: parseFloat(String(result)) });
    } catch (err) {
      res.status(500).json({ error: `Calculation failed: ${err}` });
    }
  })
);

/**
 * POST /api/multiply
 * Body: { "a": number, "b": number }
 */
app.post(
  "/api/multiply",
  mesh.route([{ capability: "multiply" }], async (req, res, [multiply]) => {
    if (!multiply) {
      res.status(503).json({ error: "Calculator service unavailable" });
      return;
    }

    const { a, b } = req.body;
    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Parameters 'a' and 'b' must be numbers" });
      return;
    }

    try {
      const result = await multiply({ a, b });
      res.json({ operation: "multiply", a, b, result: parseFloat(String(result)) });
    } catch (err) {
      res.status(500).json({ error: `Calculation failed: ${err}` });
    }
  })
);

/**
 * POST /api/divide
 * Body: { "a": number, "b": number }
 */
app.post(
  "/api/divide",
  mesh.route([{ capability: "divide" }], async (req, res, [divide]) => {
    if (!divide) {
      res.status(503).json({ error: "Calculator service unavailable" });
      return;
    }

    const { a, b } = req.body;
    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Parameters 'a' and 'b' must be numbers" });
      return;
    }

    if (b === 0) {
      res.status(400).json({ error: "Division by zero" });
      return;
    }

    try {
      const result = await divide({ a, b });
      res.json({ operation: "divide", a, b, result: parseFloat(String(result)) });
    } catch (err) {
      res.status(500).json({ error: `Calculation failed: ${err}` });
    }
  })
);

// ============================================================================
// Greeter Endpoints (consume: greet, greet-lucky, greet-age, greet-math)
// ============================================================================

/**
 * POST /api/greet
 * Body: { "name": string }
 */
app.post(
  "/api/greet",
  mesh.route([{ capability: "greet" }], async (req, res, [greet]) => {
    if (!greet) {
      res.status(503).json({ error: "Greeter service unavailable" });
      return;
    }

    const { name } = req.body;
    if (typeof name !== "string") {
      res.status(400).json({ error: "Parameter 'name' must be a string" });
      return;
    }

    try {
      const result = await greet({ name });
      res.json({ greeting: result });
    } catch (err) {
      res.status(500).json({ error: `Greeting failed: ${err}` });
    }
  })
);

/**
 * POST /api/greet/lucky
 * Body: { "name": string, "birthYear": number, "birthMonth": number }
 */
app.post(
  "/api/greet/lucky",
  mesh.route([{ capability: "greet-lucky" }], async (req, res, [greetLucky]) => {
    if (!greetLucky) {
      res.status(503).json({ error: "Greeter service unavailable" });
      return;
    }

    const { name, birthYear, birthMonth } = req.body;
    if (typeof name !== "string") {
      res.status(400).json({ error: "Parameter 'name' must be a string" });
      return;
    }
    if (typeof birthYear !== "number" || typeof birthMonth !== "number") {
      res
        .status(400)
        .json({ error: "Parameters 'birthYear' and 'birthMonth' must be numbers" });
      return;
    }

    try {
      const result = await greetLucky({ name, birthYear, birthMonth });
      res.json({ greeting: result });
    } catch (err) {
      res.status(500).json({ error: `Greeting failed: ${err}` });
    }
  })
);

/**
 * POST /api/greet/age
 * Body: { "name": string, "birthYear": number }
 */
app.post(
  "/api/greet/age",
  mesh.route([{ capability: "greet-age" }], async (req, res, [greetAge]) => {
    if (!greetAge) {
      res.status(503).json({ error: "Greeter service unavailable" });
      return;
    }

    const { name, birthYear } = req.body;
    if (typeof name !== "string") {
      res.status(400).json({ error: "Parameter 'name' must be a string" });
      return;
    }
    if (typeof birthYear !== "number") {
      res.status(400).json({ error: "Parameter 'birthYear' must be a number" });
      return;
    }

    try {
      const result = await greetAge({ name, birthYear });
      res.json({ greeting: result });
    } catch (err) {
      res.status(500).json({ error: `Greeting failed: ${err}` });
    }
  })
);

/**
 * POST /api/greet/math
 * Body: { "name": string, "a": number, "b": number }
 */
app.post(
  "/api/greet/math",
  mesh.route([{ capability: "greet-math" }], async (req, res, [greetMath]) => {
    if (!greetMath) {
      res.status(503).json({ error: "Greeter service unavailable" });
      return;
    }

    const { name, a, b } = req.body;
    if (typeof name !== "string") {
      res.status(400).json({ error: "Parameter 'name' must be a string" });
      return;
    }
    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Parameters 'a' and 'b' must be numbers" });
      return;
    }

    try {
      const result = await greetMath({ name, a, b });
      res.json({ greeting: result });
    } catch (err) {
      res.status(500).json({ error: `Greeting failed: ${err}` });
    }
  })
);

// ============================================================================
// Start Server
// ============================================================================

app.listen(PORT, () => {
  console.log(`Express API listening on http://localhost:${PORT}`);
  console.log(`\nEndpoints:`);
  console.log(`  GET  /           - API info`);
  console.log(`  GET  /health     - Health check`);
  console.log(`  POST /api/add    - Add two numbers`);
  console.log(`  POST /api/subtract - Subtract two numbers`);
  console.log(`  POST /api/multiply - Multiply two numbers`);
  console.log(`  POST /api/divide - Divide two numbers`);
  console.log(`  POST /api/greet  - Simple greeting`);
  console.log(`  POST /api/greet/lucky - Greeting with lucky number`);
  console.log(`  POST /api/greet/age - Greeting with age`);
  console.log(`  POST /api/greet/math - Greeting with math facts`);
});
