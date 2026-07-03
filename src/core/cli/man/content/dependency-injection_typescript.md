# Dependency Injection (TypeScript)

> Automatic wiring of capabilities between agents

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a tool declares a dependency, the mesh automatically creates a callable proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Tool declares dependencies via `addTool()` options
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh creates proxy objects for each dependency
5. **Invocation**: Calling the proxy routes to the remote agent

## Resolution Pipeline

When the registry resolves one of your dependencies, candidate providers flow through a fixed sequence of filter stages:

```
health → capability_match → tags → version → schema → tiebreaker
```

| Stage              | What it filters on                                                          |
| ------------------ | --------------------------------------------------------------------------- |
| `health`           | Drops unhealthy / deregistering candidates first                            |
| `capability_match` | Indexed query on the capability name                                        |
| `tags`             | Required / preferred / excluded tag filter (with scoring)                   |
| `version`          | Semver constraint (bare `4.6.0` = exact; `>=2.0.0`, `^1.4`, ...)            |
| `schema`           | Opt-in schema check (issue #547) — see below                                |
| `tiebreaker`       | Highest tag-match score, then **highest version**, then agent ID            |

Every decision the registry makes is recorded as a `dependency_resolved` (or `dependency_unresolved`) event. Use `meshctl audit <agent>` to read them back — see `meshctl man audit`.

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

### Schema-Aware Filtering (issue #547)

Add `expectedSchema` (and optionally `matchMode`) to opt the dependency into the schema stage of the pipeline. Producers whose published `outputSchema` doesn't satisfy your expected shape are evicted with `SchemaIncompatible`.

```typescript
import { z } from "zod";

const EmployeeSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  department: z.string(),
});

agent.addTool({
  name: "hr_report",
  capability: "hr_report",
  dependencies: [
    {
      capability: "lookup_employee",
      expectedSchema: EmployeeSchema,
      matchMode: "subset",  // default opt-in; or "strict"
    },
  ],
  parameters: z.object({}),
  execute: async ({}, lookup_employee: McpMeshTool | null = null) => { /* ... */ },
});
```

`matchMode` defaults to `"subset"` when `expectedSchema` is set. See `meshctl man schema-matching` for `subset` vs `strict` semantics, the cross-language convention table, and the `MCP_MESH_SCHEMA_STRICT` env knob.

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

Dependencies may be unavailable. During agent startup, calls on a declared-but-unresolved dependency first wait — bounded by the settle window (`MCP_MESH_SETTLE_TIMEOUT`, default 20s; the window starts when the agent's first dependency is declared) — for the resolution to land before degrading; once the agent settles, unresolved dependencies inject `null` immediately. Always handle `null`:

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

By default a dependency is optional: an unresolved dependency injects `null`, and the agent still starts, registers, and serves (soft-fail). Mark an edge `required` to opt that single edge into strictness:

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
    data_service: McpMeshTool | null = null, // dependencies[0] — required
    formatter: McpMeshTool | null = null,    // dependencies[1] — optional
  ) => { /* ... */ },
});
```

`required` defaults to `false` and combines with the other selector fields (`tags`, `version`, `expectedSchema`). It is carried on the wire only when `true`.

### Availability Semantics

The registry computes a capability-availability predicate:

> a capability is **available** ⇔ its owning agent is healthy **AND** every one of its `required` dependencies resolves to an available provider (full tag / version / schema matching)

The predicate is **transitive**: in a required chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. Optional edges never propagate — strictness flows only along edges you mark `required`, so the soft-fail default is preserved everywhere else.

An unavailable capability is excluded from resolution exactly like an unhealthy provider — it drops out at the resolver's `health` stage. Consumers holding a proxy to it see the proxy flip to `null` through the same background dependency-update channel that already delivers topology changes — no code changes, no SDK upgrade required.

### Route Perimeter (503)

Mesh-internal calls go through proxies; external HTTP callers to a `mesh.route()` handler do not. When a route declares a required dependency that is unavailable at call time, the framework's own middleware returns **503** — before your handler runs, after the settle window — with the body:

```json
{ "error": "dependency_unavailable", "capability": "data_service" }
```

503 rather than 404 so monitoring alarms on 5xx, load-balancer health checks eject the instance, and clients see a retryable "unavailable" instead of a permanent "missing".

### Cycle Rule

A cycle among `required` edges can never converge (both ends stay unavailable forever), so the registry rejects the registration/heartbeat that would close one, loudly naming the loop:

```
required dependency cycle: analyst → enricher → analyst
```

The rejected agent logs the registration failure and keeps retrying on each heartbeat until the loop is broken. Cycles routed through an **optional** edge remain legal — that is the bootstrapping path.

### Observing Availability

The agents/capabilities API carries two derived fields per capability:

- `available` — the predicate above (boolean)
- `unavailable_reason` — set when `available` is false; names the first broken edge with its constraint detail, e.g. `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`, `required dep 'data_service' unavailable (provider agent-7 unhealthy)`, or `agent unhealthy` when the owning agent is itself down.

The capability stays visible in the registry, UI, and `meshctl` (availability is distinct from presence), so the reason chain is a diagnostic upgrade, not a disappearance.

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
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
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
- `meshctl man schema-matching` - Schema-aware capability filtering (#547)
- `meshctl man audit` - Inspecting resolution decisions
- `meshctl man health --typescript` - Health monitoring
- `meshctl man proxies --typescript` - Proxy details
