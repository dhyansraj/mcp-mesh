# Express Integration

> Use mesh dependency injection in Express backends with mesh.route()

**Note:** This page covers TypeScript/Express integration. For Python/FastAPI, see `meshctl man fastapi`.

## Overview

MCP Mesh provides `mesh.route()` middleware for Express applications that need to consume mesh capabilities without being MCP agents themselves. This enables traditional REST APIs to leverage the mesh service layer.

**Important**: This is for integrating MCP Mesh into your EXISTING Express app. There is no `meshctl scaffold` command for Express backends. To create a new MCP agent, use `meshctl scaffold --lang typescript` instead.

## Installation

```bash
npm install @mcpmesh/sdk express
npm install -D @types/express tsx
```

## Two Architectures

| Pattern         | Function                     | Use Case                              |
| --------------- | ---------------------------- | ------------------------------------- |
| MCP Agent       | `mesh()` + auto-run          | Service that _provides_ capabilities  |
| Express Backend | `mesh.route()`               | REST API that _consumes_ capabilities |

```
[Frontend] → [Express Backend] → [MCP Mesh] → [Agents]
                   ↑
            mesh.route()
```

## mesh.route() Function

```typescript
import express from "express";
import { mesh } from "@mcpmesh/sdk";
import type { McpMeshAgent } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

app.post("/chat", mesh.route(
  [{ capability: "avatar_chat" }],
  async (req, res, { avatar_chat }) => {
    if (!avatar_chat) {
      return res.status(503).json({ error: "Service unavailable" });
    }
    const result = await avatar_chat({
      message: req.body.message,
      user_email: "user@example.com",
    });
    res.json({ response: result.message });
  }
));

app.listen(3000);
```

## Dependency Declaration

### Simple (by capability name)

```typescript
app.post("/users", mesh.route(
  ["user_service", "notification_service"],
  async (req, res, { user_service, notification_service }) => {
    // Dependencies are keyed by capability name
  }
));
```

### With Tag Filtering

```typescript
app.post("/analyze", mesh.route(
  [
    { capability: "llm", tags: ["+claude"] },
    { capability: "storage", tags: ["-deprecated"] },
  ],
  async (req, res, { llm, storage }) => {
    // Use filtered dependencies
  }
));
```

## Complete Example

```typescript
import express, { Request, Response } from "express";
import { mesh } from "@mcpmesh/sdk";
import type { McpMeshAgent } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

interface ChatRequest {
  message: string;
  avatarId?: string;
}

interface ChatResponse {
  response: string;
  avatarId: string;
}

// Chat endpoint that delegates to mesh avatar agent
app.post("/api/chat", mesh.route(
  [{ capability: "avatar_chat" }],
  async (req: Request<{}, ChatResponse, ChatRequest>, res: Response<ChatResponse>, { avatar_chat }) => {
    if (!avatar_chat) {
      return res.status(503).json({
        response: "Avatar service unavailable",
        avatarId: ""
      });
    }

    const result = await avatar_chat({
      message: req.body.message,
      avatar_id: req.body.avatarId || "default",
      user_email: "user@example.com",
    });

    res.json({
      response: result.message || "",
      avatarId: req.body.avatarId || "default",
    });
  }
));

// History endpoint using mesh agent
app.get("/api/history", mesh.route(
  [{ capability: "conversation_history_get" }],
  async (req, res, { conversation_history_get }) => {
    const result = await conversation_history_get({
      avatar_id: req.query.avatarId || "default",
      limit: parseInt(req.query.limit as string) || 50,
    });
    res.json({ messages: result.messages || [] });
  }
));

app.listen(3000, () => {
  console.log("Express server listening on port 3000");
});
```

## Running Your Express App

Run your existing Express application as you normally would:

```bash
export MCP_MESH_REGISTRY_URL=http://localhost:8000
npx tsx src/server.ts
```

**Note**: Unlike MCP agents, Express backends are NOT started with `meshctl start`.

The backend will:

1. Auto-initialize mesh connection on first `mesh.route()` call
2. Connect to the mesh registry
3. Resolve dependencies declared in `mesh.route()`
4. Inject proxies into route handlers as the `deps` object
5. Re-resolve on topology changes (auto-rewiring)

## Advanced: Explicit Control

For cases where you need more control over initialization:

```typescript
import express from "express";
import { meshExpress, mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

// Explicit mesh configuration
const meshApp = meshExpress(app, {
  name: "my-api",
  port: 3000,
  registryUrl: "http://localhost:8000",
});

// Define routes with mesh.route()
app.post("/compute", mesh.route(
  [{ capability: "calculator" }],
  async (req, res, { calculator }) => {
    res.json({ result: await calculator(req.body) });
  }
));

// Explicitly start the mesh connection
meshApp.start();
```

## Key Differences from mesh()

| Aspect                | mesh() (MCP Agent)   | mesh.route() (Express)              |
| --------------------- | -------------------- | ----------------------------------- |
| Registers with mesh   | Yes                  | No                                  |
| Provides capabilities | Yes                  | No                                  |
| Consumes capabilities | Yes                  | Yes                                 |
| Has heartbeat         | Yes                  | Yes (for dependency resolution)     |
| Protocol              | MCP JSON-RPC         | REST/HTTP                           |
| Use case              | Microservice         | API Gateway/Backend                 |

## When to Use mesh.route()

- Building a REST API that fronts mesh services
- API gateway pattern
- Backend-for-Frontend (BFF) services
- Adding REST endpoints to existing Express apps
- When you need traditional HTTP semantics (REST, OpenAPI docs)

## When to Use mesh() Instead

- Building reusable mesh capabilities
- Service-to-service communication
- LLM tool providers
- When other agents need to discover and call your service

## See Also

- `meshctl man decorators` - All mesh decorators and functions
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration
- `meshctl man fastapi` - Python/FastAPI equivalent
