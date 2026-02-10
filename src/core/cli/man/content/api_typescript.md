# API Integration (TypeScript/Express)

> Add mesh capabilities to your Express routes with mesh.route()

## Why Use This

- You have an Express app (or are building one) and want your routes to call mesh agent capabilities (LLMs, data services, etc.)
- `mesh.route()` middleware gives you automatic dependency injection -- declare what you need, mesh provides it
- Your API registers as a consumer (Type: API) -- no MCP protocol needed on your side
- Dependencies auto-rewire when agents come and go

## Install

```bash
npm install @mcpmesh/sdk express
npm install -D @types/express tsx
```

## Quick Start (Add to Existing App)

**Before** -- a normal Express endpoint:

```typescript
app.post("/chat", async (req, res) => {
  // How do I call the LLM agent from here?
  res.json({ response: "..." });
});
```

**After** -- same endpoint with mesh dependency injection:

```typescript
import { mesh } from "@mcpmesh/sdk";

app.post(
  "/chat",
  mesh.route(
    [{ capability: "avatar_chat" }],
    async (req, res, { avatar_chat }) => {
      const result = await avatar_chat({
        message: req.body.message,
        user_email: "user@example.com",
      });
      res.json({ response: result.message });
    },
  ),
);
```

The third argument to your handler is a dependencies object -- mesh resolves and injects the proxies by **position**. The first dependency maps to the first key in the destructured object, and so on.

## Starting Fresh

A minimal complete app:

```typescript
import express from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

app.post(
  "/greet",
  mesh.route(["greeting"], async (req, res, { greeting }) => {
    const result = await greeting({ name: req.body.name });
    res.json({ message: result.text || "" });
  }),
);

app.listen(3000);
```

## Dependency Declaration

### Simple (by capability name)

```typescript
app.post(
  "/users",
  mesh.route(
    ["user_service", "notification_service"],
    async (req, res, { user_service, notification_service }) => {
      // Dependencies are keyed by capability name
    },
  ),
);
```

### With Tag Filtering

```typescript
app.post(
  "/analyze",
  mesh.route(
    [
      { capability: "llm", tags: ["+claude"] },
      { capability: "storage", tags: ["-deprecated"] },
    ],
    async (req, res, { llm, storage }) => {
      // Use filtered dependencies
    },
  ),
);
```

## Running

```bash
# 1. Start the mesh registry
meshctl start --registry-only

# 2. Start your Express app (not through meshctl)
export MCP_MESH_REGISTRY_URL=http://localhost:8000
npx tsx src/server.ts
```

**Note**: Express backends are NOT started with `meshctl start` -- run them your normal way. The registry must be running so `mesh.route()` can resolve dependencies.

## How It Works

1. Auto-initializes mesh connection on first `mesh.route()` call
2. Connects to the mesh registry
3. Resolves dependencies declared in `mesh.route()`
4. Injects proxies into your route handler as the `deps` object
5. Re-resolves on topology changes (auto-rewiring)

## Advanced: Explicit Control

For cases where you need to configure the mesh connection explicitly:

```typescript
import express from "express";
import { meshExpress, mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

// Explicit mesh configuration
const meshApp = meshExpress(app, {
  name: "my-api",
  httpPort: 3000,
});

app.post(
  "/compute",
  mesh.route(
    [{ capability: "calculator" }],
    async (req, res, { calculator }) => {
      res.json({ result: await calculator(req.body) });
    },
  ),
);

// Explicitly start the mesh connection
meshApp.start();
```

## Graceful Degradation

If a dependency might not be available, check for null:

```typescript
app.post(
  "/greet",
  mesh.route([{ capability: "greeting" }], async (req, res, { greeting }) => {
    if (!greeting) {
      return res.status(503).json({ error: "Service unavailable" });
    }
    const result = await greeting({ name: req.body.name });
    res.json({ message: result.text });
  }),
);
```

## See Also

- `meshctl man decorators` - All mesh decorators and functions
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration
