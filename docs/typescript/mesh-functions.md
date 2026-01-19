<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/decorators/">Python Decorators</a></span>
</div>

# MCP Mesh Functions (TypeScript)

> Core functions for building distributed agent systems

## Overview

MCP Mesh provides core functions that transform regular TypeScript functions into mesh-aware distributed services. These functions handle registration, dependency injection, and communication automatically.

| Function             | Purpose                            |
| -------------------- | ---------------------------------- |
| `mesh()`             | Create mesh agent wrapping FastMCP |
| `agent.addTool()`    | Register capability with DI        |
| `mesh.llm()`         | Enable LLM-powered tools           |
| `mesh.llmProvider()` | Create LLM provider (zero-code)    |
| `mesh.route()`       | Express route with mesh DI         |

## mesh() Function

Creates a MeshAgent that wraps a FastMCP server with mesh capabilities.

```typescript
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";

const server = new FastMCP({
  name: "My Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "my-service", // Required: unique agent identifier
  version: "1.0.0", // Semantic version
  description: "Service desc", // Human-readable description
  port: 8080, // HTTP server port (0 = auto-assign)
  host: "localhost", // Host announced to registry
  namespace: "default", // Namespace for isolation
  heartbeatInterval: 30, // Heartbeat interval in seconds
});
```

## agent.addTool()

Registers a function as a mesh capability with dependency injection.

```typescript
import { z } from "zod";

agent.addTool({
  name: "greet",
  capability: "greeting", // Capability name for discovery
  description: "Greets users", // Human-readable description
  version: "1.0.0", // Capability version
  tags: ["greeting", "utility"], // Tags for filtering
  dependencies: ["date_service"], // Required capabilities
  parameters: z.object({
    name: z.string(),
  }),
  execute: async (
    { name }, // Input parameters
    { date_service }, // Injected dependencies (nullable)
  ) => {
    if (date_service) {
      const today = await date_service({});
      return `Hello ${name}! Today is ${today}`;
    }
    return `Hello ${name}!`; // Graceful degradation
  },
});
```

**Note**: Dependencies are injected as the second parameter object, keyed by capability name. They may be `null` if unavailable.

### Dependency Injection Types

| Type           | Use Case               |
| -------------- | ---------------------- |
| `McpMeshTool` | Tool calls via proxy   |
| `null`         | Dependency unavailable |

## mesh.llm()

Creates an LLM-powered tool with automatic tool discovery.

```typescript
import { z } from "zod";

agent.addTool({
  name: "assist",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] }, // LLM provider selector
    maxIterations: 5, // Max agentic loop iterations
    systemPrompt: "file://prompts/agent.hbs", // Handlebars template
    contextParam: "ctx", // Parameter name for context
    filter: [{ tags: ["tools"] }], // Tool filter for discovery
    filterMode: "all", // "all", "best_match", or "*"
  }),
  capability: "smart_assistant",
  description: "LLM-powered assistant",
  parameters: z.object({
    ctx: z.object({
      query: z.string(),
    }),
  }),
  execute: async ({ ctx }, { llm }) => {
    return llm("Help the user with their request");
  },
});
```

### Filter Modes

| Mode         | Description                              |
| ------------ | ---------------------------------------- |
| `all`        | Include all tools matching any filter    |
| `best_match` | One tool per capability (best tag match) |
| `*`          | All available tools (wildcard)           |

## mesh.llmProvider()

Creates a zero-code LLM provider wrapping LiteLLM-compatible APIs.

```typescript
agent.addTool({
  name: "claude_chat",
  ...mesh.llmProvider({
    model: "anthropic/claude-sonnet-4-5", // LiteLLM model string
    capability: "llm", // Capability name
    tags: ["llm", "claude", "provider"], // Discovery tags
    version: "1.0.0", // Provider version
  }),
});
```

## mesh.route()

Enables mesh dependency injection in Express route handlers. Use this when building REST APIs that consume mesh capabilities.

```typescript
import express from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

app.post(
  "/chat",
  mesh.route(
    [{ capability: "avatar_chat" }], // Dependencies
    async (req, res, { avatar_chat }) => {
      if (!avatar_chat) {
        return res.status(503).json({ error: "Service unavailable" });
      }
      const result = await avatar_chat({
        message: req.body.message,
        user_email: "user@example.com",
      });
      res.json({ response: result.message });
    },
  ),
);

app.listen(3000);
```

**Note**: `mesh.route()` is for Express backends that _consume_ mesh capabilities. Use `agent.addTool()` for MCP agents that _provide_ capabilities.

See `meshctl man express` for complete Express integration guide.

## Environment Variable Overrides

All configuration can be overridden via environment variables:

```bash
export MCP_MESH_AGENT_NAME=custom-name
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_NAMESPACE=production
export MCP_MESH_REGISTRY_URL=http://registry:8000
```

## Complete Example

```typescript
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Calculator Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "calculator",
  port: 9000,
});

// Basic tool
agent.addTool({
  name: "add",
  capability: "calculator_add",
  description: "Add two numbers",
  tags: ["math", "calculator"],
  parameters: z.object({
    a: z.number(),
    b: z.number(),
  }),
  execute: async ({ a, b }) => String(a + b),
});

// Tool with dependency
agent.addTool({
  name: "calculate_with_logging",
  capability: "calculator_logged",
  description: "Calculate with audit logging",
  dependencies: ["audit_log"],
  parameters: z.object({
    operation: z.string(),
    a: z.number(),
    b: z.number(),
  }),
  execute: async ({ operation, a, b }, { audit_log }) => {
    const result = operation === "add" ? a + b : a - b;
    if (audit_log) {
      await audit_log({ operation, a, b, result });
    }
    return String(result);
  },
});

// Agent auto-starts - no explicit run() call needed!
```

## See Also

- `meshctl man dependency-injection` - DI details
- `meshctl man llm --typescript` - LLM integration guide
- `meshctl man tags` - Tag matching system
- `meshctl man capabilities` - Capabilities system
- `meshctl man express` - Express integration with mesh.route()
