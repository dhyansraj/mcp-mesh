# Capabilities System (TypeScript)

> Named services that agents provide for discovery and dependency injection

## Overview

Capabilities are named services that agents register with the mesh. When an agent declares a capability, other agents can discover and use it through dependency injection. Multiple agents can provide the same capability with different implementations.

## Capability Selector Syntax

MCP Mesh uses a unified syntax for selecting capabilities throughout the framework. This same pattern appears in `dependencies`, `mesh.llm()` provider/filter, `mesh.route()`, and `meshctl scaffold --filter`.

### Selector Fields

| Field        | Required | Description                                   |
| ------------ | -------- | --------------------------------------------- |
| `capability` | Yes\*    | Capability name to match                      |
| `tags`       | No       | Tag filters. Optional `+` (preferred) / `-` (excluded) operators |
| `version`    | No       | Semver constraint (bare `4.6.0` = exact; `>=2.0.0`, `^1.4`, ...) |

\*When filtering by tags only (e.g., LLM tool filter), `capability` can be omitted.

### Syntax Forms

**Shorthand** (capability name only):

```typescript
dependencies: ["date_service", "weather_data"];
```

**Full form** (with filters):

```typescript
dependencies: [
  { capability: "date_service" },
  { capability: "weather_data", tags: ["+fast", "-deprecated"] },
  { capability: "api_client", version: ">=2.0.0" },
];
```

### Where This Syntax Is Used

| Context                     | Example                                                 |
| --------------------------- | ------------------------------------------------------- |
| `addTool()` dependencies    | `dependencies: ["svc"]` or `[{ capability: "svc" }]`    |
| `mesh.llm()` provider       | `provider: { capability: "llm", tags: ["+claude"] }`    |
| `mesh.llm()` filter         | `filter: [{ capability: "calc" }, { tags: ["tools"] }]` |
| `mesh.route()` dependencies | `[{ capability: "api", tags: ["+v2"] }]`                |
| `meshctl scaffold --filter` | `--filter '[{"capability": "x"}]'`                      |

### Tag Operators

| Prefix | Meaning   | Example         |
| ------ | --------- | --------------- |
| (none) | Required  | `"api"`         |
| `+`    | Preferred | `"+fast"`       |
| `-`    | Excluded  | `"-deprecated"` |

### Selector Logic (AND/OR)

| Syntax                         | Semantics                                |
| ------------------------------ | ---------------------------------------- |
| `tags: ["a", "b", "c"]`        | a AND b AND c (all required)             |
| `tags: ["+a", "+b"]`           | Prefer a, prefer b (neither required)    |
| `tags: ["a", "-x"]`            | Must have a, must NOT have x             |
| `tags: ["a", ["b", "c"]]`      | a AND (b OR c) - tag-level OR            |
| `tags: [["a"], ["b"]]`         | a OR b (full OR)                         |
| `[{tags:["a"]}, {tags:["b"]}]` | a OR b (multiple selectors - LLM filter) |

**Tag-Level OR** (v0.9.1+):

Use nested arrays in tags for OR alternatives with fallback behavior:

```typescript
dependencies: [
  // Prefer python implementation, fallback to typescript
  { capability: "math", tags: ["addition", ["python", "typescript"]] },
];
```

Resolution order:

1. Try to find provider with `addition` AND `python` tags
2. If not found, try provider with `addition` AND `typescript` tags
3. If neither found, dependency is unresolved

See `meshctl man tags` for detailed tag matching behavior.

## Declaring Capabilities

```typescript
import { z } from "zod";

agent.addTool({
  name: "get_weather",
  capability: "weather_data", // Capability name
  description: "Provides weather info", // Human-readable description
  version: "1.0.0", // Semantic version
  tags: ["weather", "current", "api"], // Tags for filtering
  parameters: z.object({
    city: z.string(),
  }),
  execute: async ({ city }) => {
    return JSON.stringify({ city, temp: 72, conditions: "sunny" });
  },
});
```

## Capability Resolution

When an agent requests a dependency, the registry resolves it by:

1. **Name matching**: Find agents providing the requested capability
2. **Tag filtering**: Apply tag constraints (if specified) and compute a tag-match score
3. **Version constraints**: Drop providers whose version doesn't satisfy the semver constraint
4. **Selection**: Among the survivors, pick the best match — highest tag-match score first, then **highest version**, then agent ID for determinism

So when several providers share the same capability and tags, the one with the **newest version wins**.

## Multiple Implementations

Multiple agents can provide the same capability:

```typescript
// Agent 1: OpenWeather implementation
agent1.addTool({
  name: "openweather",
  capability: "weather_data",
  tags: ["weather", "openweather", "free"],
  parameters: z.object({ city: z.string() }),
  execute: async ({ city }) => {
    /* ... */
  },
});

// Agent 2: Premium weather implementation
agent2.addTool({
  name: "premium_weather",
  capability: "weather_data",
  tags: ["weather", "premium", "accurate"],
  parameters: z.object({ city: z.string() }),
  execute: async ({ city }) => {
    /* ... */
  },
});
```

Consumers can select implementations using tag filters:

```typescript
agent.addTool({
  name: "get_forecast",
  capability: "forecast",
  dependencies: [{ capability: "weather_data", tags: ["+premium"] }],
  parameters: z.object({}),
  execute: async ({}, { weather_data }) => {
    if (weather_data) {
      return await weather_data({ city: "NYC" });
    }
    return "Weather service unavailable";
  },
});
```

## Dependency Declaration

### Simple (by name)

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["date_service", "weather_data"],
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, { date_service, weather_data }) => {
    // date_service and weather_data are McpMeshTool | null
  },
});
```

### Advanced (with filters)

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: [
    { capability: "date_service" },
    { capability: "weather_data", tags: ["+accurate", "-deprecated"] },
  ],
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, { date_service, weather_data }) => {
    // Dependencies injected by capability name
  },
});
```

## Capability Naming Conventions

| Pattern         | Example         | Use Case         |
| --------------- | --------------- | ---------------- |
| `noun_noun`     | `weather_data`  | Data providers   |
| `verb_noun`     | `get_time`      | Action services  |
| `domain_action` | `auth_validate` | Domain-specific  |
| `service`       | `llm`           | Generic services |

A capability name is one or more **dot-separated segments**, each matching `^[a-zA-Z][a-zA-Z0-9_-]*$` — a leading letter followed by letters, digits, underscores, or hyphens, with no leading, trailing, or consecutive dots. Single-segment names like `weather_data` are the common case; **dot-namespacing** (`media.caption`, `billing.v2.invoice`) is the convention for grouping related capabilities under a service prefix.

## Versioning

Providers declare a concrete version (default `"1.0.0"` if unset):

```typescript
agent.addTool({
  name: "api_v2",
  capability: "api_client",
  version: "2.1.0",
  // ...
});
```

Consumers specify a **semver constraint** in the dependency selector. The constraint is a hard filter applied before selection; among the providers that satisfy it, the registry picks the **highest version**:

```typescript
dependencies: [{ capability: "api_client", version: ">=2.0.0" }];
```

| Constraint   | Matches                       | Selected                            |
| ------------ | ----------------------------- | ----------------------------------- |
| `"4.6.0"`    | exactly `4.6.0`               | `4.6.0`                             |
| `">=4.6.0"`  | any version ≥ `4.6.0`         | highest available (may cross major) |
| `"^4.6.0"`   | `>=4.6.0 <5.0.0` (same major) | highest within major `4`            |
| `"~4.6.0"`   | `>=4.6.0 <4.7.0` (same minor) | highest within minor `4.6`          |
| omitted      | any version                   | highest available                   |

A **bare** version like `"4.6.0"` means an **exact** match, consistent with `capability` and `tags` being exact matches. A provider with no/empty version cannot satisfy a non-empty constraint.

## See Also

- `meshctl man tags --typescript` - Tag matching system
- `meshctl man dependency-injection --typescript` - How DI works
- `meshctl man decorators --typescript` - All TypeScript functions
