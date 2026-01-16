<div class="runtime-crossref">
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/getting-started/index/">TypeScript Quick Start</a></span>
</div>

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
pip install "mcp-mesh>=0.7,<0.8"
```

## 1. Start the Registry

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug
```

## 2. Create Your First Agent

```bash
# Terminal 2: Scaffold a basic agent
meshctl scaffold --name greeter --agent-type tool
```

This creates `greeter/main.py`:

```python
import mesh

app = mesh.get_app()

@app.tool()
@mesh.tool(
    capability="greeting",
    description="Greet a user by name",
)
def greet(name: str) -> str:
    return f"Hello, {name}!"

@mesh.agent(
    name="greeter",
    version="1.0.0",
    http_port=9000,
)
class GreeterAgent:
    pass
```

## 3. Run the Agent

```bash
# Terminal 2: Start the agent
meshctl start greeter/main.py --debug
```

## 4. Test the Agent

```bash
# Terminal 3: Call the agent
meshctl call greeter greeting --params '{"name": "World"}'
# Output: Hello, World!

# Or list running agents
meshctl list
```

## 5. Add a Dependency

Create a second agent that depends on the greeter:

```bash
meshctl scaffold --name assistant --agent-type tool
```

Edit `assistant/main.py`:

```python
import mesh

app = mesh.get_app()

@app.tool()
@mesh.tool(
    capability="smart_greeting",
    description="Enhanced greeting with time",
    dependencies=["greeting"],  # Depend on greeter
)
async def smart_greet(
    name: str,
    greeting_svc: mesh.McpMeshAgent = None,  # Injected!
) -> str:
    if greeting_svc:
        base_greeting = await greeting_svc(name=name)
        return f"{base_greeting} Welcome to MCP Mesh!"
    return f"Hello, {name}! (greeter unavailable)"

@mesh.agent(
    name="assistant",
    version="1.0.0",
    http_port=9001,
)
class AssistantAgent:
    pass
```

```bash
# Start the assistant
meshctl start assistant/main.py --debug

# Call the smart greeting
meshctl call assistant smart_greeting --params '{"name": "Developer"}'
# Output: Hello, Developer! Welcome to MCP Mesh!
```

## Next Steps

- `meshctl man decorators` - Learn all mesh decorators
- `meshctl man llm` - Add LLM capabilities
- `meshctl man deployment` - Deploy to Docker/Kubernetes
- `meshctl man tags` - Tag-based service selection

## See Also

- `meshctl scaffold --help` - All scaffold options
- `meshctl man prerequisites` - Full setup guide
