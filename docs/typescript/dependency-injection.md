<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/dependency-injection/">Python Dependency Injection</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../java/dependency-injection/">Java Dependency Injection</a></span>
</div>

# Dependency Injection (TypeScript)

> Automatic wiring of capabilities between agents

MCP Mesh implements **[Distributed Dynamic Dependency Injection (DDDI)](../concepts/dddi.md)** — dependencies are discovered and injected at runtime across the mesh, not at compile time.

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a tool declares a dependency, the mesh automatically creates a callable proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Tool declares dependencies via `addTool()` options
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh creates proxy objects for each dependency
5. **Invocation**: Calling the proxy routes to the remote agent

## Declaring Dependencies

### Simple Dependencies

```typescript
import { z } from "zod";

agent.addTool({
  name: "greet",
  capability: "greeting",
  dependencies: ["date_service"], // Request by capability name
  parameters: z.object({
    name: z.string(),
  }),
  execute: async ({ name }, date_service: McpMeshTool | null = null) => {
    if (date_service) {
      const today = await date_service({});
      return `Hello ${name}! Today is ${today}`;
    }
    return `Hello ${name}!`;
  },
});
```

**Important**: Dependencies are injected **positionally** as parameters after the first `args` parameter, in declaration order (`dependencies[0]`, `dependencies[1]`, ...). They may be `null` if unavailable.

### Dependencies with Filters

Use the capability selector syntax (see `meshctl man capabilities --typescript`) to filter by tags or version:

```typescript
agent.addTool({
  name: "generate_report",
  capability: "report",
  dependencies: [
    { capability: "data_service", tags: ["+fast"] },
    { capability: "formatter", tags: ["-deprecated"] },
  ],
  parameters: z.object({}),
  execute: async (
    {},
    data_service: McpMeshTool | null = null, // dependencies[0]
    formatter: McpMeshTool | null = null,    // dependencies[1]
  ) => {
    if (!data_service || !formatter) {
      return "Required services unavailable";
    }
    const data = await data_service({ query: "sales" });
    return await formatter({ data });
  },
});
```

### OR Alternatives (Tag-Level)

Use nested arrays in tags to specify fallback providers:

```typescript
agent.addTool({
  name: "calculate",
  capability: "calculator",
  dependencies: [
    // Prefer python provider, fallback to typescript
    { capability: "math", tags: ["addition", ["python", "typescript"]] },
  ],
  parameters: z.object({
    a: z.number(),
    b: z.number(),
  }),
  execute: async ({ a, b }, math: McpMeshTool | null = null) => {
    if (!math) return "Math service unavailable";
    const result = await math({ a, b });
    return result;
  },
});
```

Resolution order:

1. Try to find provider with `addition` AND `python` tags
2. If not found, try provider with `addition` AND `typescript` tags
3. If neither found, dependency is injected as `null`

This is useful when you have multiple implementations of the same capability
and want to prefer one but fallback to another if unavailable.

## Injection Types

### McpMeshTool

Callable proxy for tool invocations:

```typescript
// dependencies: ["helper"] → helper is dependencies[0]
execute: async ({}, helper: McpMeshTool | null = null) => {
  if (helper) {
    // Direct call (calls default tool)
    const result = await helper({ arg1: "value" });

    // Named tool call
    const result2 = await helper.callTool("tool_name", { arg: "value" });
  }
};
```

### LLM Injection

For LLM agent injection in `mesh.llm()` decorated tools:

```typescript
agent.addTool({
  name: "smart_tool",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] },
    systemPrompt: "You are a helpful assistant.",
  }),
  capability: "smart",
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, { llm }) => {
    return llm("Process this request: " + query);
  },
});
```

## Graceful Degradation

Dependencies may be unavailable. Always handle `null`:

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["helper"],
  parameters: z.object({}),
  execute: async ({}, helper: McpMeshTool | null = null) => {
    if (helper === null) {
      return "Service temporarily unavailable";
    }
    return await helper({});
  },
});
```

Or use default values:

```typescript
agent.addTool({
  name: "get_time",
  capability: "time_service",
  dependencies: ["date_service"],
  parameters: z.object({}),
  execute: async ({}, date_service: McpMeshTool | null = null) => {
    if (date_service) {
      return await date_service({});
    }
    return new Date().toISOString(); // Fallback
  },
});
```

## Required Dependencies

Graceful degradation is the default — an unresolved dependency injects `null` and your agent keeps serving. When a capability is useless without a particular dependency, mark that edge `required` instead of null-checking it everywhere:

```typescript
agent.addTool({
  name: "generate_report",
  capability: "report",
  dependencies: [
    { capability: "data_service", required: true },
    { capability: "formatter" }, // optional (default)
  ],
  parameters: z.object({}),
  // Tool deps inject POSITIONALLY as McpMeshTool params after args
  // (dependencies[0], dependencies[1], ...).
  execute: async (
    {},
    data_service: McpMeshTool | null = null, // dependencies[0] — required, guaranteed live
    formatter: McpMeshTool | null = null,    // dependencies[1] — optional
  ) => {
    const data = await data_service!({ query: "sales" }); // guaranteed live
    return formatter ? await formatter({ data }) : JSON.stringify(data);
  },
});
```

`required` defaults to `false` and combines with the other selector fields (`tags`, `version`, `expectedSchema`).

**What it changes.** The registry now computes a capability as **available** only when its owning agent is healthy _and_ every one of its `required` dependencies resolves to an available provider. This is transitive — in a chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. An unavailable capability drops out of resolution exactly like an unhealthy provider, so any consumer's proxy for it flips to `null` automatically, with no code change. Optional edges never propagate, so soft-fail stays the default everywhere you don't opt in.

**HTTP routes get an automatic 503.** External callers to a `mesh.route()` handler don't go through proxies, so when a route declares a required dependency that is unavailable at request time, the framework returns `503` before your handler runs (after the settle window):

```json
{ "error": "dependency_unavailable", "capability": "data_service" }
```

**Cycles are rejected.** A cycle of required edges could never converge (both ends stay unavailable forever), so the registry rejects the registration that closes one and logs, on the rejected agent, a `required dependency cycle: analyst → enricher → analyst` registration failure. Cycles that route through an optional edge remain legal — that's the bootstrapping path.

**Inspecting availability.** Each capability in the agents/capabilities API carries `available` (boolean) and, when false, `unavailable_reason` naming the first broken edge — e.g. `required dep 'data_service' unavailable (provider agent-7 unhealthy)` or `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`. The capability stays visible in the registry, UI, and `meshctl`; availability is distinct from presence.

## Service Views (RFC #1280)

A **service view** aggregates several capability dependencies behind one typed facade. `mesh.serviceView({ methods })` returns a branded value you place as **one** entry in a tool's `dependencies` array; it expands into N ordinary edges (one per method, name-sorted) and the framework injects a single facade argument. Each method delegates to its own resolved proxy, so different methods can bind different provider agents and rebind independently.

```ts
const Media = mesh.serviceView({
  methods: {
    caption: { capability: "media.caption", required: true, tags: ["+fast"] },
    thumbnail: "media.thumbnail",
    transcribe: "media.transcribe",
  },
  // minAvailable: 2,
});

agent.addTool({
  name: "process_media",
  dependencies: ["audit_log", Media],
  execute: async (args, auditLog, media) => {
    // dep params are inferred; cast the view slot to type its methods
    const svc = media as MeshServiceFacade<typeof Media>;
    const caption = await svc.caption({ text: args.text });
    let thumb: unknown = null;
    try {
      thumb = await svc.thumbnail({ id: args.id });
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;               // optional method unresolved
    }
    return { caption, thumb };
  },
});
```

The view slot expands **in place** (name-sorted), so its edges keep contiguous indices and a view over N capabilities shows as **N dependencies** in `meshctl list`. A method spec is a capability string or an object (`capability`, `tags`, `version`, `required`, `expectedSchema`, `matchMode`). Leave the `execute` dependency params un-annotated (they're inferred) and cast the view slot at point of use — `const svc = view as MeshServiceFacade<typeof View>` — to type its method keys; a direct parameter annotation doesn't compile under `strictFunctionTypes`. Capability names are dot-namespaced (see the [naming rules](capabilities-tags.md#capability-naming-conventions)).

- A `required` method joins the tool's pre-invoke guard: an unresolved required edge makes the tool refuse with a `UserError` carrying the structured `dependency_unavailable` payload before the handler runs (direct and claim paths). An unresolved **optional** method rejects with a `TypeError` (the null-proxy passthrough) on its own call only.
- `minAvailable` adds a consumer-local floor: below it every facade call throws `MeshServiceUnavailableError` (settle-aware).
- A view **forces inline execution** — per-tool worker isolation is disabled for a view-bearing tool, with a warning logged at registration when `MCP_MESH_TOOL_WORKERS>1`.
- Views are a **tool-parameter** surface only: a `mesh.serviceView(...)` in `mesh.route(...)` or `mesh.a2a.mount(...)` dependencies is rejected.

### Publishing the dotted capabilities a view binds

A view is consumer-side only — it aggregates capabilities, it does not publish them. The dotted capabilities it binds are ordinary tools, each declared explicitly on its provider with a dot-namespaced `capability`:

```ts
agent.addTool({
  name: "caption",
  capability: "media.caption",
  parameters: z.object({ text: z.string() }),
  execute: async ({ text }) => ({ caption: `a scene: ${text}` }),
});

agent.addTool({
  name: "thumbnail",
  capability: "media.thumbnail",
  tags: ["fast"],
  parameters: z.object({ id: z.string() }),
  execute: async ({ id }) => ({ uri: `thumb://${id}` }),
});
```

Each dotted `capability` is segment-validated against the dotted-capability grammar and resolves independently, so `media.caption` and `media.thumbnail` can live on the same agent or on separate ones. `meshctl list --services` groups them for display by the segments before the last dot.

## Proxy Configuration

Configure proxy behavior via `dependencyKwargs` — an array indexed by dependency position (aligned with `dependencies`):

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["slow_service"],
  dependencyKwargs: [
    {
      // Config for dependencies[0] (slow_service)
      timeout: 60, // Request timeout in seconds (default 30)
      maxAttempts: 3, // Total attempts incl. the first try (default 1)
      streaming: true, // Enable streaming (uses streamTimeout)
      sessionRequired: true, // Require session affinity
    },
  ],
  parameters: z.object({ data: z.string() }),
  execute: async ({ data }, slow_service: McpMeshTool | null = null) => {
    if (slow_service) {
      return await slow_service({ data });
    }
    return "Service unavailable";
  },
});
```

## Proxy Types (Auto-Selected)

The mesh uses a unified proxy system:

| Proxy Type                | Use Case                                        |
| ------------------------- | ----------------------------------------------- |
| `SelfDependencyProxy`     | Same agent (direct call, no network overhead)   |
| `EnhancedUnifiedMCPProxy` | Cross-agent calls (auto-configured from kwargs) |

## Function vs Capability Names

- **Capability name**: Used for dependency resolution (`date_service`)
- **Function name**: Used in MCP tool calls (`get_current_time`)

The mesh maps capabilities to their implementing functions automatically.

## Auto-Rewiring

When topology changes (agents join/leave), the mesh:

1. Detects change via heartbeat response
2. Refreshes dependency proxies
3. Routes to new providers automatically

No code changes needed - happens transparently.

## TypeScript Type Safety

Dependencies are typed based on the capability name:

```typescript
// dependencies: ["date_service", "weather_service"]
// Each dependency is McpMeshTool | null, injected positionally in
// declaration order after the first args parameter.
execute: async (
  params,
  date_service: McpMeshTool | null = null,    // dependencies[0]
  weather_service: McpMeshTool | null = null, // dependencies[1]
) => {
  if (date_service) {
    // TypeScript knows this is McpMeshTool
    const result = await date_service({});
  }
};
```

## Complete Example

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Report Service", version: "1.0.0" });
const agent = mesh(server, { name: "report-service", httpPort: 8080 });

// Tool with multiple dependencies
agent.addTool({
  name: "generate_sales_report",
  capability: "sales_report",
  description: "Generate a sales report with formatting",
  dependencies: [
    { capability: "data_service", tags: ["+fast"] },
    { capability: "formatter" },
    "audit_log", // Simple string form
  ],
  parameters: z.object({
    quarter: z.enum(["Q1", "Q2", "Q3", "Q4"]),
    year: z.number(),
  }),
  execute: async (
    { quarter, year },
    data_service: McpMeshTool | null = null, // dependencies[0]
    formatter: McpMeshTool | null = null,    // dependencies[1]
    audit_log: McpMeshTool | null = null,    // dependencies[2] (string form)
  ) => {
    // Graceful degradation for each dependency
    if (!data_service) {
      return "Data service unavailable";
    }

    const data = await data_service({ quarter, year });

    // Format if available, otherwise return raw
    const result = formatter
      ? await formatter({ data, format: "markdown" })
      : JSON.stringify(data);

    // Log if audit service is available
    if (audit_log) {
      await audit_log({ action: "report_generated", quarter, year });
    }

    return result;
  },
});
```

## See Also

- `meshctl man capabilities --typescript` - Declaring capabilities
- `meshctl man tags --typescript` - Tag-based selection
- `meshctl man health --typescript` - Health monitoring
- `meshctl man proxies --typescript` - Proxy details
