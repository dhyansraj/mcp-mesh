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
  execute: async ({ name }, { date_service }) => {
    if (date_service) {
      const today = await date_service({});
      return `Hello ${name}! Today is ${today}`;
    }
    return `Hello ${name}!`;
  },
});
```

**Important**: Dependencies are injected as the second parameter to `execute`, keyed by capability name. They may be `null` if unavailable.

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
  execute: async ({}, { data_service, formatter }) => {
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
  execute: async ({ a, b }, { math }) => {
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
execute: async ({}, { helper }) => {
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
  execute: async ({}, { helper }) => {
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
  execute: async ({}, { date_service }) => {
    if (date_service) {
      return await date_service({});
    }
    return new Date().toISOString(); // Fallback
  },
});
```

## Proxy Configuration

Configure proxy behavior via `dependencyConfig`:

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["slow_service"],
  dependencyConfig: {
    slow_service: {
      timeout: 60000, // Request timeout (milliseconds)
      retryCount: 3, // Retry attempts
      streaming: true, // Enable streaming
      sessionRequired: true, // Require session affinity
    },
  },
  parameters: z.object({ data: z.string() }),
  execute: async ({ data }, { slow_service }) => {
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
// Dependencies are McpMeshTool | null
execute: async (params, deps: Record<string, McpMeshTool | null>) => {
  const { date_service, weather_service } = deps;

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
const agent = mesh(server, { name: "report-service", httpPort: 9000 });

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
    { data_service, formatter, audit_log },
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
