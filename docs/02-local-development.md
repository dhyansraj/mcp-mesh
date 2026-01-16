# Local Development

> Develop your own MCP Mesh agents locally

## Overview

This guide walks you through setting up a local development environment for building your own MCP Mesh agents. You'll learn how to scaffold, develop, and test agents on your machine using **Python** or **TypeScript**.

## Development Workflow

```mermaid
graph LR
    A[Install Tools] --> B[Scaffold Agent]
    B --> C[Write Code]
    C --> D[Start Agents]
    D --> E[Test with meshctl]
    E --> C
```

## Quick Start

### 1. Install Required Components

=== "meshctl (CLI)"

    ```bash
    npm install -g @mcpmesh/cli
    ```

    Command-line tool for managing agents, registry, and mesh operations.

=== "Registry"

    ```bash
    npm install -g @mcpmesh/cli
    ```

    Service discovery and coordination server. Included with the npm package above.

=== "Python Runtime"

    ```bash
    pip install "mcp-mesh>=0.8,<0.9"
    ```

    Runtime for building agents with `@mesh.agent` and `@mesh.tool` decorators.

=== "TypeScript Runtime"

    ```bash
    npm install @mcpmesh/sdk
    ```

    Runtime for building agents with `mesh()` and `agent.addTool()` functions.

### 2. Set Up Your Project

=== "Python"

    ```bash
    # Create project directory
    mkdir my-agent-project
    cd my-agent-project

    # Create and activate virtual environment
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate

    # Install MCP Mesh SDK
    pip install "mcp-mesh>=0.8,<0.9"
    ```

=== "TypeScript"

    ```bash
    # Create project directory
    mkdir my-agent-project
    cd my-agent-project

    # Initialize npm project
    npm init -y

    # Install MCP Mesh SDK and dependencies
    npm install @mcpmesh/sdk zod
    npm install -D typescript tsx @types/node

    # Create src directory
    mkdir src
    ```

### 3. Scaffold Your Agent

=== "Python"

    ```bash
    # Generate a new agent
    meshctl scaffold --name my-agent --capability my_service

    # Or with Docker Compose for deployment
    meshctl scaffold --name my-agent --compose
    ```

    This creates:

    ```
    my-agent/
    ├── main.py           # Your agent code
    ├── requirements.txt  # Dependencies
    └── README.md         # Documentation
    ```

=== "TypeScript"

    ```bash
    # Generate a new TypeScript agent
    meshctl scaffold --name my-agent --capability my_service --lang typescript

    # Or with Docker Compose for deployment
    meshctl scaffold --name my-agent --lang typescript --compose
    ```

    This creates:

    ```
    my-agent/
    ├── src/
    │   └── index.ts      # Your agent code
    ├── package.json      # Dependencies
    ├── tsconfig.json     # TypeScript config
    └── README.md         # Documentation
    ```

### 4. Develop Your Agent

=== "Python"

    Edit `main.py` to add your functionality:

    ```python
    import mesh
    from fastmcp import FastMCP

    app = FastMCP("My Agent")

    @app.tool()
    @mesh.tool(capability="my_service")
    def my_function(data: str) -> str:
        """Your custom functionality."""
        return f"Processed: {data}"

    @mesh.agent(name="my-agent", http_port=8080, auto_run=True)
    class MyAgent:
        pass
    ```

=== "TypeScript"

    Edit `src/index.ts` to add your functionality:

    ```typescript
    import { FastMCP, mesh } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({
      name: "My Agent",
      version: "1.0.0",
    });

    const agent = mesh(server, {
      name: "my-agent",
      port: 8080,
    });

    agent.addTool({
      name: "my_function",
      capability: "my_service",
      description: "Your custom functionality",
      parameters: z.object({
        data: z.string().describe("Input data"),
      }),
      execute: async ({ data }) => {
        return `Processed: ${data}`;
      },
    });
    ```

### 5. Start Your Agent

=== "Python"

    ```bash
    # Start your agent (registry auto-starts if not running)
    meshctl start main.py
    ```

=== "TypeScript"

    ```bash
    # Start your agent (registry auto-starts if not running)
    meshctl start src/index.ts
    ```

### 6. Test Your Agent

```bash
# List registered agents
meshctl list

# Call your tool
meshctl call my_function '{"data":"hello"}'
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# List available tools
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Call your tool
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"my_function","arguments":{"data":"hello"}}}'
```

!!! note "SSE Response Format"
MCP Mesh uses Server-Sent Events (SSE) format. `meshctl call` handles this automatically.

</details>

## Multi-Agent Development

Develop multiple agents that work together:

=== "Python"

    ```bash
    # Terminal 1: Start first agent
    meshctl start agents/auth_agent.py

    # Terminal 2: Start second agent (depends on first)
    meshctl start agents/api_agent.py

    # Test dependency injection
    meshctl call secure_operation
    ```

=== "TypeScript"

    ```bash
    # Terminal 1: Start first agent
    meshctl start agents/auth-agent/src/index.ts

    # Terminal 2: Start second agent (depends on first)
    meshctl start agents/api-agent/src/index.ts

    # Test dependency injection
    meshctl call secure_operation
    ```

## Project Structure

Each scaffolded agent gets its own directory:

=== "Python"

    ```
    my-project/
    ├── my-agent/
    │   ├── main.py           # Agent code
    │   ├── requirements.txt  # Dependencies
    │   ├── Dockerfile        # Container build
    │   ├── helm-values.yaml  # Kubernetes config
    │   └── README.md
    ├── another-agent/
    │   ├── main.py
    │   ├── requirements.txt
    │   ├── Dockerfile
    │   └── ...
    └── docker-compose.yml    # Generated with --compose
    ```

=== "TypeScript"

    ```
    my-project/
    ├── my-agent/
    │   ├── src/
    │   │   └── index.ts      # Agent code
    │   ├── package.json      # Dependencies
    │   ├── tsconfig.json     # TypeScript config
    │   ├── Dockerfile        # Container build
    │   ├── helm-values.yaml  # Kubernetes config
    │   └── README.md
    ├── another-agent/
    │   ├── src/
    │   │   └── index.ts
    │   ├── package.json
    │   ├── Dockerfile
    │   └── ...
    └── docker-compose.yml    # Generated with --compose
    ```

## Environment Variables

Configure your agents with environment variables:

```bash
# .env
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_HTTP_PORT=8080
```

## Useful Commands

```bash
# List all agents
meshctl list

# List only healthy agents
meshctl list

# Check mesh status
meshctl status

# Stop all agents
meshctl stop --all
```

## Debugging

### Enable Debug Logging

=== "Python"

    ```bash
    meshctl start --debug main.py
    ```

=== "TypeScript"

    ```bash
    meshctl start --debug src/index.ts
    ```

### Check Registry Connection

```bash
# Quick check - shows agent count and dependency resolution
meshctl list

# Detailed view - shows capabilities, dependencies, endpoints
meshctl status
```

### VS Code Configuration

=== "Python"

    Create `.vscode/launch.json`:

    ```json
    {
      "version": "0.2.0",
      "configurations": [
        {
          "name": "Debug Agent",
          "type": "python",
          "request": "launch",
          "module": "mesh",
          "args": ["start", "main.py"],
          "env": {
            "MCP_MESH_LOG_LEVEL": "DEBUG"
          }
        }
      ]
    }
    ```

=== "TypeScript"

    Create `.vscode/launch.json`:

    ```json
    {
      "version": "0.2.0",
      "configurations": [
        {
          "name": "Debug Agent",
          "type": "node",
          "request": "launch",
          "runtimeExecutable": "npx",
          "runtimeArgs": ["tsx", "src/index.ts"],
          "env": {
            "MCP_MESH_LOG_LEVEL": "DEBUG"
          },
          "console": "integratedTerminal"
        }
      ]
    }
    ```

## Testing Your Agents

=== "Python"

    ```python
    # tests/test_agents.py
    import pytest
    import requests

    def test_my_function():
        response = requests.post(
            "http://localhost:8080/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "my_function",
                    "arguments": {"data": "test"}
                }
            }
        )
        assert response.status_code == 200
        result = response.json()
        assert "Processed: test" in str(result)
    ```

    Run tests:

    ```bash
    pytest tests/
    ```

=== "TypeScript"

    ```typescript
    // src/index.test.ts
    import { describe, it, expect } from "vitest";

    describe("my_function", () => {
      it("should process data correctly", async () => {
        const response = await fetch("http://localhost:8080/mcp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "tools/call",
            params: {
              name: "my_function",
              arguments: { data: "test" }
            }
          })
        });
        expect(response.ok).toBe(true);
        const result = await response.json();
        expect(JSON.stringify(result)).toContain("Processed: test");
      });
    });
    ```

    Run tests:

    ```bash
    npx vitest
    ```

## Troubleshooting

### Registry Not Starting

```bash
# Check if port 8000 is in use
lsof -i :8000

# Kill existing process if needed
kill -9 $(lsof -t -i:8000)

# Start registry manually
meshctl start-registry
```

### Agent Not Registering

1. Check registry is running: `curl http://localhost:8000/health`
2. Check agent logs for errors
3. Verify `MCP_MESH_REGISTRY_URL` is correct

### Dependency Not Injected

```bash
# Quick check - see if all dependencies are resolved (e.g., "4/4")
meshctl list

# Detailed view - shows capabilities, resolved dependencies, and endpoints
meshctl status
```

## Next Steps

- [Docker Deployment](03-docker-deployment.md) - Package and deploy your agents
- [Kubernetes Deployment](06-helm-deployment.md) - Scale to production
- [Python Decorators](../python/decorators.md) - Python `@mesh.tool`, `@mesh.agent`, `@mesh.llm`
- [TypeScript Functions](../typescript/mesh-functions.md) - TypeScript `mesh()`, `addTool()`, `mesh.llm()`
