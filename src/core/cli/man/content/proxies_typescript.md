# Proxy System & Communication (TypeScript)

> Inter-agent communication and proxy configuration

## Overview

MCP Mesh uses proxy objects to enable seamless communication between agents. When you call an injected dependency, you're actually calling a proxy that routes to the remote agent via MCP JSON-RPC.

## How Proxies Work

```
┌─────────────┐     Proxy Call      ┌─────────────┐
│   Agent A   │ ────────────────►   │   Agent B   │
│             │   MCP JSON-RPC      │             │
│  date_svc() │ ◄────────────────   │ get_time()  │
└─────────────┘     Response        └─────────────┘
```

1. Agent A calls `date_svc()` (the proxy)
2. Proxy serializes call to MCP JSON-RPC
3. HTTP POST to Agent B's `/mcp` endpoint
4. Agent B executes `get_time()` function
5. Response returned to Agent A

## Proxy Types

Every injected dependency is an `McpMeshTool` proxy that calls its provider over HTTP, including a dependency on another tool of the same agent. A service view (`mesh.serviceView`) injects a facade whose methods are such proxies.

## Using Proxies

All proxy calls are async and return Promises.

### Simple Call

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["helper"],
  parameters: z.object({}),
  execute: async ({}, helper: McpMeshTool | null = null) => {
    if (helper) {
      const result = await helper({}); // Call default tool
      return result;
    }
    return "Helper unavailable";
  },
});
```

### Named Tool Call

```typescript
execute: async ({}, helper: McpMeshTool | null = null) => {
  if (helper) {
    const result = await helper.callTool("specific_tool", { arg: "value" });
    return result;
  }
};
```

### With Arguments

```typescript
execute: async ({}, weather: McpMeshTool | null = null) => {
  if (weather) {
    const result = await weather({ city: "London", units: "metric" });
    return result;
  }
};
```

## Proxy Configuration

Configure via `dependencyKwargs` in the tool options. It is an array indexed
by position: `dependencyKwargs[i]` configures `dependencies[i]`.

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["slow_service"],
  dependencyKwargs: [
    {
      timeout: 60, // Request timeout (seconds)
      maxAttempts: 3, // Total attempts, including the first
      customHeaders: {
        // Custom HTTP headers
        "X-Request-ID": "...",
      },
    },
  ],
  parameters: z.object({ data: z.string() }),
  execute: async ({ data }, slowService: McpMeshTool | null = null) => {
    if (slowService) {
      return await slowService({ data });
    }
    return "Service unavailable";
  },
});
```

## Configuration Options

| Option            | Type    | Default    | Description                                                    |
| ----------------- | ------- | ---------- | -------------------------------------------------------------- |
| `timeout`         | number  | 300        | Request timeout in seconds (default from `MCP_MESH_CALL_TIMEOUT`) |
| `maxAttempts`     | number  | 1          | Total attempts; a timeout is never retried                     |
| `retryDelay`      | number  | 0.1        | Initial delay between attempts, in seconds                     |
| `retryBackoff`    | number  | 2.0        | Multiplier applied to the delay after each attempt             |
| `streaming`       | boolean | false      | Run unary calls on `streamTimeout` instead of `timeout`        |
| `streamTimeout`   | number  | 300        | Timeout for `stream()` and `streaming: true` calls, in seconds |
| `customHeaders`   | object  | {}         | Additional HTTP headers on every call to this dependency       |
| `maxResponseSize` | number  | 10485760   | Largest accepted response body, in bytes                       |

## Streaming

`proxy.stream(args)` returns an `AsyncIterable<string>` of text chunks and
always runs on `streamTimeout`:

```typescript
agent.addTool({
  name: "process_stream",
  capability: "stream_processor",
  dependencies: ["stream_service"],
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, streamService: McpMeshTool | null = null) => {
    if (streamService) {
      const chunks: string[] = [];
      for await (const chunk of streamService.stream({ query })) {
        chunks.push(chunk);
      }
      return chunks.join("");
    }
    return "Stream service unavailable";
  },
});
```

## Error Handling

Proxies handle errors gracefully:

```typescript
agent.addTool({
  name: "resilient_tool",
  capability: "resilient",
  dependencies: ["helper"],
  parameters: z.object({}),
  execute: async ({}, helper: McpMeshTool | null = null) => {
    if (helper === null) {
      return "Service unavailable";
    }

    try {
      return await helper({});
    } catch (error) {
      if (error instanceof Error) {
        if (error.message.includes("timeout")) {
          return "Service timed out";
        }
        if (error.message.includes("ECONNREFUSED")) {
          return "Cannot reach service";
        }
      }
      return "Unknown error occurred";
    }
  },
});
```

## Direct Communication

Agents communicate directly - no proxy server:

- Registry provides endpoint information
- Agents call each other via HTTP
- Minimal latency (no intermediary)
- Continues working if registry is down

## Complete Example

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Data Processor", version: "1.0.0" });
const agent = mesh(server, { name: "data-processor", httpPort: 8080 });

agent.addTool({
  name: "process_data",
  capability: "data_processing",
  description: "Process data with retry and timeout",
  dependencies: ["data_source", "validator", "storage"],
  dependencyKwargs: [
    { timeout: 10, maxAttempts: 3 }, // data_source
    { timeout: 5 }, // validator
    { timeout: 30, maxAttempts: 4 }, // storage
  ],
  parameters: z.object({
    dataId: z.string(),
  }),
  execute: async (
    { dataId },
    dataSource: McpMeshTool | null = null,  // dependencies[0]
    validator: McpMeshTool | null = null,   // dependencies[1]
    storage: McpMeshTool | null = null,     // dependencies[2]
  ) => {
    // Fetch data
    if (!dataSource) {
      return JSON.stringify({ error: "Data source unavailable" });
    }
    const data = await dataSource({ id: dataId });

    // Validate (optional)
    if (validator) {
      const isValid = await validator({ data });
      if (!isValid) {
        return JSON.stringify({ error: "Validation failed" });
      }
    }

    // Store (optional)
    if (storage) {
      await storage({ data, id: dataId });
    }

    return JSON.stringify({ success: true, processed: dataId });
  },
});
```

## See Also

- `meshctl man dependency-injection --typescript` - DI overview
- `meshctl man health --typescript` - Auto-rewiring on failure
- `meshctl man testing --typescript` - Testing agent communication
