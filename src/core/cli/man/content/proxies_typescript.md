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

MCP Mesh automatically selects the appropriate proxy:

| Proxy                    | Use Case     | Features             |
| ------------------------ | ------------ | -------------------- |
| `SelfDependencyProxy`    | Same agent   | Direct function call |
| `MCPClientProxy`         | Simple tools | Basic MCP calls      |
| `EnhancedMCPClientProxy` | Configured   | Timeout, retry       |
| `EnhancedFullMCPProxy`   | Advanced     | Streaming, sessions  |

## Using Proxies

All proxy calls are async and return Promises.

### Simple Call

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["helper"],
  parameters: z.object({}),
  execute: async ({}, { helper }) => {
    if (helper) {
      const result = await helper({});  // Call default tool
      return result;
    }
    return "Helper unavailable";
  },
});
```

### Named Tool Call

```typescript
execute: async ({}, { helper }) => {
  if (helper) {
    const result = await helper.callTool("specific_tool", { arg: "value" });
    return result;
  }
}
```

### With Arguments

```typescript
execute: async ({}, { weather }) => {
  if (weather) {
    const result = await weather({ city: "London", units: "metric" });
    return result;
  }
}
```

## Proxy Configuration

Configure via `dependencyConfig` in the tool options:

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["slow_service"],
  dependencyConfig: {
    slow_service: {
      timeout: 60000,             // Request timeout (ms)
      retryCount: 3,              // Retry attempts on failure
      customHeaders: {            // Custom HTTP headers
        "X-Request-ID": "...",
      },
      streaming: true,            // Enable streaming responses
      sessionRequired: true,      // Require session affinity
      authRequired: true,         // Require authentication
      stateful: true,             // Mark as stateful
      autoSessionManagement: true, // Auto session lifecycle
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

## Configuration Options

| Option                  | Type    | Default | Description                  |
| ----------------------- | ------- | ------- | ---------------------------- |
| `timeout`               | number  | 30000   | Request timeout in ms        |
| `retryCount`            | number  | 0       | Number of retry attempts     |
| `streaming`             | boolean | false   | Enable streaming responses   |
| `sessionRequired`       | boolean | false   | Require session affinity     |
| `authRequired`          | boolean | false   | Require authentication       |
| `stateful`              | boolean | false   | Mark capability as stateful  |
| `autoSessionManagement` | boolean | false   | Auto manage sessions         |
| `customHeaders`         | object  | {}      | Additional HTTP headers      |

## Streaming

Enable streaming for real-time data:

```typescript
agent.addTool({
  name: "process_stream",
  capability: "stream_processor",
  dependencies: ["stream_service"],
  dependencyConfig: {
    stream_service: { streaming: true },
  },
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, { stream_service }) => {
    if (stream_service) {
      const chunks: string[] = [];
      for await (const chunk of stream_service.stream({ query })) {
        chunks.push(chunk);
      }
      return chunks.join("");
    }
    return "Stream service unavailable";
  },
});
```

## Session Affinity

For stateful services, ensure requests go to the same instance:

```typescript
agent.addTool({
  name: "stateful_operation",
  capability: "stateful_op",
  dependencies: ["stateful_service"],
  dependencyConfig: {
    stateful_service: {
      sessionRequired: true,
      autoSessionManagement: true,
    },
  },
  parameters: z.object({ action: z.string() }),
  execute: async ({ action }, { stateful_service }) => {
    if (stateful_service) {
      // All calls routed to same instance
      await stateful_service.callTool("initialize", {});
      const result = await stateful_service.callTool("process", { action });
      await stateful_service.callTool("cleanup", {});
      return result;
    }
    return "Service unavailable";
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
  execute: async ({}, { helper }) => {
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
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Data Processor", version: "1.0.0" });
const agent = mesh(server, { name: "data-processor", port: 9000 });

agent.addTool({
  name: "process_data",
  capability: "data_processing",
  description: "Process data with retry and timeout",
  dependencies: ["data_source", "validator", "storage"],
  dependencyConfig: {
    data_source: {
      timeout: 10000,
      retryCount: 2,
    },
    validator: {
      timeout: 5000,
    },
    storage: {
      timeout: 30000,
      retryCount: 3,
      sessionRequired: true,
    },
  },
  parameters: z.object({
    dataId: z.string(),
  }),
  execute: async ({ dataId }, { data_source, validator, storage }) => {
    // Fetch data
    if (!data_source) {
      return JSON.stringify({ error: "Data source unavailable" });
    }
    const data = await data_source({ id: dataId });

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
