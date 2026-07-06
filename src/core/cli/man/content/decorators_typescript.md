# MCP Mesh Functions (TypeScript)

> Core functions for building distributed agent systems

## Overview

MCP Mesh provides core functions that transform regular TypeScript functions into mesh-aware distributed services. These functions handle registration, dependency injection, and communication automatically.

| Function           | Purpose                            |
| ------------------ | ---------------------------------- |
| `mesh()`           | Create mesh agent wrapping FastMCP |
| `agent.addTool()`  | Register capability with DI        |
| `mesh.llm()`       | Enable LLM-powered tools           |
| `mesh.llmProvider()` | Create LLM provider (zero-code)  |
| `mesh.route()`     | Express route with mesh DI         |
| `addTool({ a2aConfig })` | Bridge an external A2A skill as a mesh capability |

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
  name: "my-service",           // Required: unique agent identifier
  version: "1.0.0",             // Semantic version
  description: "Service desc",  // Human-readable description
  httpPort: 8080,                   // HTTP server port (0 = auto-assign)
  host: "localhost",            // Host announced to registry
  namespace: "default",         // Namespace for isolation
  heartbeatInterval: 30,        // Heartbeat interval in seconds
});
```

## agent.addTool()

Registers a function as a mesh capability with dependency injection.

```typescript
import { z } from "zod";

agent.addTool({
  name: "greet",
  capability: "greeting",              // Capability name for discovery
  description: "Greets users",         // Human-readable description
  version: "1.0.0",                    // Capability version
  tags: ["greeting", "utility"],       // Tags for filtering
  dependencies: ["date_service"],      // Required capabilities
  parameters: z.object({
    name: z.string(),
  }),
  execute: async (
    { name },                          // Input parameters
    { date_service }                   // Injected dependencies (nullable)
  ) => {
    if (date_service) {
      const today = await date_service({});
      return `Hello ${name}! Today is ${today}`;
    }
    return `Hello ${name}!`;  // Graceful degradation
  },
});
```

**Note**: Dependencies are injected as the second parameter object, keyed by capability name. They may be `null` if unavailable.

### Dependency Injection Types

| Type            | Use Case                               |
| --------------- | -------------------------------------- |
| `McpMeshTool`  | Tool calls via proxy                   |
| `null`          | Dependency unavailable                 |

### Schema-aware capabilities (issue #547)

The mesh can match producers and consumers by their canonical response schemas, not just by capability name. This is opt-in per dependency.

**Producer side** — pass a Zod schema as `outputSchema`:

```typescript
import { z } from "zod";

const EmployeeSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  department: z.string(),
});

agent.addTool({
  name: "lookup_employee",
  capability: "lookup_employee",
  parameters: z.object({ id: z.number().int() }),
  outputSchema: EmployeeSchema,
  execute: async ({ id }) => ({ id, name: "Ada", department: "Engineering" }),
});
```

**Consumer side** — `expectedSchema` + `matchMode` on the dependency:

```typescript
agent.addTool({
  name: "hr_report",
  capability: "hr_report",
  dependencies: [
    {
      capability: "lookup_employee",
      expectedSchema: EmployeeSchema,
      matchMode: "subset",  // or "strict"; defaults to "subset" if expectedSchema is set
    },
  ],
  parameters: z.object({}),
  execute: async ({}, { lookup_employee }) => { /* ... */ },
});
```

**Per-tool strict knob** — set `outputSchemaStrict: false` on a producer tool to demote a BLOCK schema verdict to a WARN for that one tool. Wins even when the cluster-wide `MCP_MESH_SCHEMA_STRICT=true` env var promotes WARN→BLOCK.

```typescript
agent.addTool({
  name: "experimental",
  capability: "experimental_thing",
  outputSchema: SomeRecursiveSchema,
  outputSchemaStrict: false,
  // ...
});
```

See `meshctl man schema-matching` for modes, the cross-language convention table, and verdict tiers. See `meshctl man dependency-injection --typescript` for the full filter pipeline.

## mesh.serviceView() / agent.addService()

Service views aggregate capabilities behind one typed facade, or publish a group of tools under a dotted prefix (RFC #1280).

**Consumer** — one `dependencies` entry expanding to N edges, injected as a facade argument:

```ts
const Media = mesh.serviceView({
  methods: {
    caption: { capability: "media.caption", required: true },
    thumbnail: "media.thumbnail",
  },
});

agent.addTool({
  name: "process_media",
  dependencies: [Media],
  execute: async (args, media) =>
    // dep params are inferred; cast the view slot to type its methods
    (media as MeshServiceFacade<typeof Media>).caption({ text: args.text }),
});
```

**Producer** — publish methods as `prefix.<method>` tools:

```ts
agent.addService("media", {
  caption: async (args) => ({ caption: `a scene: ${args.text}` }),
  thumbnail: async (args) => ({ uri: `thumb://${args.id}` }),
});
```

`required` view edges get the pre-invoke `dependency_unavailable` refusal (a `UserError`); `minAvailable` (consumer-only) adds a floor; a view forces inline execution and is rejected in `mesh.route(...)` / `mesh.a2a.mount(...)`. For the full semantics see `meshctl man dependency-injection --typescript`.

## mesh.llm()

Creates an LLM-powered tool with automatic tool discovery.

```typescript
import { z } from "zod";

agent.addTool({
  name: "assist",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] },  // LLM provider selector
    maxIterations: 5,                    // Max agentic loop iterations
    systemPrompt: "file://prompts/agent.hbs",  // Handlebars template
    contextParam: "ctx",                 // Parameter name for context
    filter: [{ tags: ["tools"] }],       // Tool filter for discovery
    filterMode: "all",                   // "all", "best_match", or "*"
    responseModel: AnalystOutput,        // Optional: schema the LLM must emit (drives structured output)
    returns: RunDailyResult,             // Optional: schema for what execute returns to callers
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

`responseModel` is the schema the LLM is required to emit and is validated against (and types the injected `llm` callable); `returns` types what `execute` returns to callers. When `responseModel` is omitted, the LLM schema falls back to `returns`. See `meshctl man llm --typescript` for a combined-fields example.

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
    model: "anthropic/claude-sonnet-4-5",  // LiteLLM model string
    capability: "llm",                      // Capability name
    tags: ["llm", "claude", "provider"],    // Discovery tags
    version: "1.0.0",                       // Provider version
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

app.post("/chat", mesh.route(
  [{ capability: "avatar_chat" }],  // Dependencies
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

**Note**: `mesh.route()` is for Express backends that _consume_ mesh capabilities. Use `agent.addTool()` for MCP agents that _provide_ capabilities.

See `meshctl man express` for complete Express integration guide.

## A2A Consumer (`a2aConfig` on `addTool`)

Bridge an external A2A v1.0 skill into the mesh as a regular mesh capability. The framework injects an `A2AClient` into the tool's execute callback.

```typescript
import { FastMCP, mesh, type A2AClient } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Date Consumer Bridge", version: "1.0.0" });
const agent = mesh(server, { name: "date-consumer-ts", httpPort: 9201 });

agent.addTool({
  name: "current_date",
  capability: "current-date",
  parameters: z.object({}),
  a2aConfig: {
    url: "http://localhost:9090/agents/date",
    skillId: "get-date",
  },
  execute: async (_args, ..._injected) => {
    const a2a = _injected[0] as A2AClient;
    const r = await a2a.send({
      role: "user",
      parts: [{ type: "text", text: "now" }],
    });
    return r.artifactText ? JSON.parse(r.artifactText) : "";
  },
});
```

Bearer auth is wired via `a2aConfig.auth = { tokenEnv: "UPSTREAM_TOKEN" }` when the upstream card requires it.

A2A producer support in TypeScript is future work — only consumer is available today.

See `meshctl man a2a` for the full A2A protocol bridge guide.

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
  httpPort: 8080,
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
