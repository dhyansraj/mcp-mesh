# Quick Start

> Get started with MCP Mesh in minutes (Python)

## Prerequisites

```bash
# Python 3.11+
python3 --version

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install MCP Mesh SDK
pip install mcp-mesh
```

## 1. Start the Registry

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug
```

## 2. Create Your First Agent

```bash
# Terminal 2: Scaffold a basic agent
meshctl scaffold basic --name greeter
```

This creates `greeter/main.py`:

```python
#!/usr/bin/env python3
"""greeter - MCP Mesh Agent."""

import mesh
from fastmcp import FastMCP

app = FastMCP("Greeter Service")


@app.tool()
@mesh.tool(
    capability="hello",
    description="A tool",
    tags=["tools"],
)
async def hello() -> str:
    """A tool."""
    # TODO: Implement tool logic
    return "Not implemented"


@mesh.agent(
    name="greeter",
    version="1.0.0",
    description="MCP Mesh agent for greeter",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class GreeterAgent:
    pass
```

The scaffolded `hello()` tool is a working stub that returns `"Not implemented"`. You can run it as-is and call it to verify the mesh end-to-end, then edit `greeter/main.py` to give the tool real behavior (e.g., change the return value or add parameters as needed).

## 3. Run the Agent

```bash
# Terminal 2: Start the agent
meshctl start greeter/main.py --debug
```

## 4. Test the Agent

```bash
# Terminal 3: Call the agent
meshctl call greeter:hello '{}'
# Output: Not implemented

# Or list running agents
meshctl list
```

## 5. Add a Dependency

Create a second agent that depends on the greeter:

```bash
meshctl scaffold basic --name assistant
```

Edit `assistant/main.py` to add a `dependencies=` clause on the tool and accept the injected proxy as a keyword parameter:

```python
#!/usr/bin/env python3
"""assistant - MCP Mesh Agent demonstrating dependency injection."""

import mesh
from fastmcp import FastMCP

app = FastMCP("Assistant Service")


@app.tool()
@mesh.tool(
    capability="smart_greeting",
    description="Enhanced greeting that calls the greeter",
    tags=["tools"],
    dependencies=["hello"],   # depend on greeter's "hello" capability
)
async def smart_greet(
    name: str,
    hello: mesh.McpMeshTool = None,    # injected by mesh
) -> str:
    if hello is None:
        return f"Hello, {name}! (greeter unavailable)"
    base = await hello()                # call the greeter
    return f"{base} Welcome to MCP Mesh, {name}!"


@mesh.agent(
    name="assistant",
    version="1.0.0",
    description="MCP Mesh agent for assistant",
    http_port=9001,
    enable_http=True,
    auto_run=True,
)
class AssistantAgent:
    pass
```

```bash
# Start the assistant
meshctl start assistant/main.py --debug

# Call the smart greeting
meshctl call assistant:smart_greet '{"name":"Developer"}'
# Output: Not implemented Welcome to MCP Mesh, Developer!
```

## Next Steps

- `meshctl man decorators` - Learn all mesh decorators
- `meshctl man llm` - Add LLM capabilities
- `meshctl man deployment` - Deploy to Docker/Kubernetes
- `meshctl man tags` - Tag-based service selection

## See Also

- `meshctl scaffold --help` - All scaffold options
- `meshctl man prerequisites` - Full setup guide
