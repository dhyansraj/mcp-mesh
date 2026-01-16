<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/examples/">Python Testing</a></span>
</div>

# Testing MCP Agents (TypeScript)

> How to test TypeScript MCP Mesh agents

## Quick Way: meshctl call

```bash
meshctl call hello_mesh_simple                    # Call tool by name
meshctl call add --params '{"a": 1, "b": 2}'     # With arguments
meshctl list --tools                              # List all available tools
```

See `meshctl man cli` for more CLI commands.

## Unit Testing with Vitest

The TypeScript SDK works well with Vitest for unit testing:

```typescript
// src/index.test.ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

describe("Calculator Agent", () => {
  let agent: ReturnType<typeof mesh>;

  beforeAll(() => {
    const server = new FastMCP({ name: "Test Calculator", version: "1.0.0" });
    agent = mesh(server, {
      name: "test-calculator",
      port: 0, // Auto-assign port for testing
      registryUrl: "", // No registry for unit tests
    });

    agent.addTool({
      name: "add",
      capability: "calculator_add",
      description: "Add two numbers",
      parameters: z.object({ a: z.number(), b: z.number() }),
      execute: async ({ a, b }) => String(a + b),
    });
  });

  it("should add two numbers", async () => {
    // Test the execute function directly
    const result = await agent.callTool("add", { a: 2, b: 3 });
    expect(result).toBe("5");
  });
});
```

### Running Tests

```bash
# Install vitest
npm install -D vitest

# Run tests
npx vitest

# Watch mode
npx vitest --watch

# With coverage
npx vitest --coverage
```

## Integration Testing

For testing agents with the mesh:

```typescript
// integration.test.ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { spawn, ChildProcess } from "child_process";

describe("Agent Integration", () => {
  let registryProcess: ChildProcess;
  let agentProcess: ChildProcess;

  beforeAll(async () => {
    // Start registry
    registryProcess = spawn("meshctl", ["start", "--registry-only"], {
      stdio: "pipe",
    });

    // Wait for registry
    await new Promise((resolve) => setTimeout(resolve, 2000));

    // Start agent
    agentProcess = spawn("meshctl", ["start", "src/index.ts"], {
      stdio: "pipe",
      env: { ...process.env, MCP_MESH_REGISTRY_URL: "http://localhost:8000" },
    });

    // Wait for agent registration
    await new Promise((resolve) => setTimeout(resolve, 3000));
  });

  afterAll(() => {
    agentProcess?.kill();
    registryProcess?.kill();
  });

  it("should register with mesh", async () => {
    const response = await fetch("http://localhost:8000/agents");
    const agents = await response.json();
    expect(agents.some((a: any) => a.name.startsWith("my-agent"))).toBe(true);
  });
});
```

## Testing with Docker Compose

```yaml
# docker-compose.test.yml
services:
  registry:
    image: mcpmesh/registry:0.7
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 5

  agent-under-test:
    build: .
    depends_on:
      registry:
        condition: service_healthy
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
```

```bash
# Run integration tests
docker compose -f docker-compose.test.yml up -d
npx vitest run integration/
docker compose -f docker-compose.test.yml down
```

## Protocol Details: curl

MCP agents expose a JSON-RPC 2.0 API over HTTP with SSE responses:

### List Available Tools

```bash
curl -s -X POST http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

### Call a Tool

```bash
curl -s -X POST http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "add",
      "arguments": {"a": 1, "b": 2}
    }
  }'
```

### Parse SSE Response

```bash
# Parse SSE format
| grep "^data:" | sed 's/^data: //' | jq .
```

## Testing Dependencies

Test graceful degradation when dependencies are unavailable:

```typescript
import { describe, it, expect } from "vitest";

describe("Dependency Handling", () => {
  it("should handle missing dependency gracefully", async () => {
    // With no registry, dependencies will be null
    const result = await agent.callTool("smart_greet", { name: "Test" });

    // Should use fallback behavior
    expect(result).toContain("(service unavailable)");
  });
});
```

## Mocking Dependencies

```typescript
import { vi } from "vitest";

// Mock a dependency proxy
const mockCalculator = vi.fn().mockResolvedValue("42");

// Inject mock into agent
agent.setMockDependency("calculator", mockCalculator);

// Test
const result = await agent.callTool("calculate", { expression: "6*7" });
expect(mockCalculator).toHaveBeenCalledWith({ expression: "6*7" });
expect(result).toBe("42");
```

## Available MCP Methods

| Method           | Description                  |
| ---------------- | ---------------------------- |
| `tools/list`     | List all available tools     |
| `tools/call`     | Invoke a tool with arguments |
| `prompts/list`   | List available prompts       |
| `resources/list` | List available resources     |

## See Also

- `meshctl man cli` - CLI commands reference
- `meshctl man decorators --typescript` - TypeScript functions
- `meshctl man deployment --typescript` - Deployment patterns
