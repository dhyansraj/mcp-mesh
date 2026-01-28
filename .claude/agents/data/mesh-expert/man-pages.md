# CAPABILITIES

# Capabilities System

> Named services that agents provide for discovery and dependency injection

## Overview

Capabilities are named services that agents register with the mesh. When an agent declares a capability, other agents can discover and use it through dependency injection. Multiple agents can provide the same capability with different implementations.

## Capability Selector Syntax

MCP Mesh uses a unified syntax for selecting capabilities throughout the framework. This same pattern appears in `dependencies`, `@mesh.llm` provider/filter, `@mesh.route`, and `meshctl scaffold --filter`.

### Selector Fields

| Field        | Required | Description                                   |
| ------------ | -------- | --------------------------------------------- |
| `capability` | Yes\*    | Capability name to match                      |
| `tags`       | No       | Tag filters with +/- operators                |
| `version`    | No       | Semantic version constraint (e.g., `>=2.0.0`) |

\*When filtering by tags only (e.g., LLM tool filter), `capability` can be omitted.

### Syntax Forms

**Shorthand** (capability name only):

```python
dependencies=["date_service", "weather_data"]
```

**Full form** (with filters):

```python
dependencies=[
    {"capability": "date_service"},
    {"capability": "weather_data", "tags": ["+fast", "-deprecated"]},
    {"capability": "api_client", "version": ">=2.0.0"},
]
```

### Where This Syntax Is Used

| Context                     | Example                                                 |
| --------------------------- | ------------------------------------------------------- |
| `@mesh.tool` dependencies   | `dependencies=["svc"]` or `[{"capability": "svc"}]`     |
| `@mesh.llm` provider        | `provider={"capability": "llm", "tags": ["+claude"]}`   |
| `@mesh.llm` filter          | `filter=[{"capability": "calc"}, {"tags": ["tools"]}]`  |
| `@mesh.route` dependencies  | `dependencies=[{"capability": "api", "tags": ["+v2"]}]` |
| `meshctl scaffold --filter` | `--filter '[{"capability": "x"}]'`                      |

### Tag Operators

| Prefix | Meaning   | Example         |
| ------ | --------- | --------------- |
| (none) | Required  | `"api"`         |
| `+`    | Preferred | `"+fast"`       |
| `-`    | Excluded  | `"-deprecated"` |

### Selector Logic (AND/OR)

| Syntax                         | Semantics                             |
| ------------------------------ | ------------------------------------- |
| `tags: ["a", "b", "c"]`        | a AND b AND c (all required)          |
| `tags: ["+a", "+b"]`           | Prefer a, prefer b (neither required) |
| `tags: ["a", "-x"]`            | Must have a, must NOT have x          |
| `[{tags:["a"]}, {tags:["b"]}]` | a OR b (multiple selectors)           |

See `meshctl man tags` for detailed tag matching behavior.

## Declaring Capabilities

```python
@app.tool()
@mesh.tool(
    capability="weather_data",           # Capability name
    description="Provides weather info", # Human-readable description
    version="1.0.0",                     # Semantic version
    tags=["weather", "current", "api"],  # Tags for filtering
)
def get_weather(city: str) -> dict:
    return {"city": city, "temp": 72, "conditions": "sunny"}
```

## Capability Resolution

When an agent requests a dependency, the registry resolves it by:

1. **Name matching**: Find agents providing the requested capability
2. **Tag filtering**: Apply tag constraints (if specified)
3. **Version constraints**: Check semantic version compatibility
4. **Load balancing**: Select from multiple matching providers

## Multiple Implementations

Multiple agents can provide the same capability:

```python
# Agent 1: OpenWeather implementation
@mesh.tool(
    capability="weather_data",
    tags=["weather", "openweather", "free"],
)
def openweather_data(city: str): ...

# Agent 2: Premium weather implementation
@mesh.tool(
    capability="weather_data",
    tags=["weather", "premium", "accurate"],
)
def premium_weather_data(city: str): ...
```

Consumers can select implementations using tag filters:

```python
@mesh.tool(
    dependencies=[{"capability": "weather_data", "tags": ["+premium"]}],
)
def get_forecast(weather: mesh.McpMeshTool = None): ...
```

## Dependency Declaration

### Simple (by name)

```python
@mesh.tool(
    dependencies=["date_service", "weather_data"],
)
def my_tool(date: mesh.McpMeshTool = None, weather: mesh.McpMeshTool = None):
    pass
```

### Advanced (with filters)

```python
@mesh.tool(
    dependencies=[
        {"capability": "date_service"},
        {"capability": "weather_data", "tags": ["+accurate", "-deprecated"]},
    ],
)
def my_tool(date: mesh.McpMeshTool = None, weather: mesh.McpMeshTool = None):
    pass
```

## Capability Naming Conventions

| Pattern         | Example         | Use Case         |
| --------------- | --------------- | ---------------- |
| `noun_noun`     | `weather_data`  | Data providers   |
| `verb_noun`     | `get_time`      | Action services  |
| `domain_action` | `auth_validate` | Domain-specific  |
| `service`       | `llm`           | Generic services |

## Versioning

Capabilities support semantic versioning:

```python
@mesh.tool(
    capability="api_client",
    version="2.1.0",
)
def api_v2(): ...
```

Consumers can specify version constraints (coming soon):

```python
dependencies=[{"capability": "api_client", "version": ">=2.0.0"}]
```

## See Also

- `meshctl man tags` - Tag matching system
- `meshctl man dependency-injection` - How DI works
- `meshctl man decorators` - All decorator options

---

# CLI

# CLI Commands for Development

> Essential meshctl commands for developing and testing agents

## Quick Reference

| Command                | Purpose                      |
| ---------------------- | ---------------------------- |
| `meshctl call`         | Invoke a tool on any agent   |
| `meshctl list`         | Show healthy agents          |
| `meshctl list --tools` | List all available tools     |
| `meshctl status`       | Show agent wiring details    |
| `meshctl trace`        | View distributed call traces |

## Calling Tools

```bash
# Call a tool (auto-discovers agent via registry) - recommended
meshctl call hello_mesh_simple
meshctl call add '{"a": 1, "b": 2}'               # With arguments
meshctl call process --file data.json             # Arguments from file

# Target specific agent (use full agent ID from 'meshctl list')
meshctl call weather-agent-7f3a2b:get_weather     # agent-ID:tool format

# Direct agent call (skip registry)
meshctl call hello_mesh --agent-url http://localhost:8080
```

## Distributed Tracing

Track calls across multiple agents with `--trace`:

```bash
# Call with tracing enabled
meshctl call smart_analyze '{"query": "test"}' --trace
# Output includes: Trace ID: abc123...

# View the call tree
meshctl trace abc123

# Example output:
# └─ smart_analyze (llm-agent) [120ms] ✓
#    ├─ get_current_time (time-agent) [5ms] ✓
#    └─ fetch_data (data-agent) [15ms] ✓

# Show internal wrapper spans
meshctl trace abc123 --show-internal

# Output as JSON
meshctl trace abc123 --json
```

## Listing Agents and Tools

```bash
# Show healthy agents (default)
meshctl list

# Show all agents including unhealthy/expired
meshctl list --all

# Wide view with endpoints and tool counts
meshctl list --wide

# Filter by name
meshctl list --filter hello

# List tools from healthy agents
meshctl list --tools

# Show tool's input schema
meshctl list --tools=get_current_time
```

## Checking Status

```bash
# Show all healthy agents' wiring
meshctl status

# Show specific agent details
meshctl status hello-world-5395c5e4

# JSON output
meshctl status --json
```

## Remote Registry

All commands support connecting to remote registries:

```bash
meshctl call hello_mesh --registry-url http://remote:8000
meshctl list --registry-url http://remote:8000
meshctl status --registry-url http://remote:8000
```

## Docker Compose (from host machine)

Calls route through registry proxy by default, reaching agents via container hostnames:

```bash
# Calls route through registry proxy (default)
meshctl call greet
meshctl call add '{"a": 1, "b": 2}'

# Direct call bypassing proxy
meshctl call greet --agent-url http://localhost:9001 --use-proxy=false
```

## Kubernetes (with ingress)

```bash
# With DNS configured
meshctl call greet --ingress-domain mcp-mesh.local

# Port-forwarded ingress
meshctl call greet --ingress-domain mcp-mesh.local --ingress-url http://localhost:9080
```

## See Also

- `meshctl man testing` - MCP JSON-RPC protocol details
- `meshctl man scaffold` - Creating new agents

---

# DECORATORS

# MCP Mesh Decorators

> Core decorators for building distributed agent systems

## Overview

MCP Mesh provides five core decorators that transform regular Python functions and classes into mesh-aware distributed services. These decorators handle registration, dependency injection, and communication automatically.

| Decorator            | Purpose                         |
| -------------------- | ------------------------------- |
| `@mesh.agent`        | Configure agent server settings |
| `@mesh.tool`         | Register capability with DI     |
| `@mesh.llm`          | Enable LLM-powered tools        |
| `@mesh.llm_provider` | Create LLM provider (zero-code) |
| `@mesh.route`        | FastAPI route with mesh DI      |

## Decorator Order (Critical!)

When using multiple decorators, order matters:

```python
@app.tool()           # 1. FastMCP protocol handler (outermost)
@mesh.llm(...)        # 2. LLM integration (if using)
@mesh.tool(...)       # 3. Mesh capability registration (innermost)
def my_function():
    pass
```

## @mesh.agent

Configures the agent server settings. Applied to a class.

```python
@mesh.agent(
    name="my-service",           # Required: unique agent identifier
    version="1.0.0",             # Semantic version
    description="Service desc",  # Human-readable description
    http_port=8080,              # HTTP server port (0 = auto-assign)
    http_host="localhost",       # Host announced to registry
    namespace="default",         # Namespace for isolation
    auto_run=True,               # Start automatically (no main() needed)
    auto_run_interval=30,        # Heartbeat interval in seconds
    health_check=health_fn,      # Optional health check function
    health_check_ttl=30,         # Health check cache TTL
)
class MyAgent:
    pass
```

## @mesh.tool

Registers a function as a mesh capability with dependency injection.

```python
@app.tool()
@mesh.tool(
    capability="greeting",              # Capability name for discovery
    description="Greets users",         # Human-readable description
    version="1.0.0",                    # Capability version
    tags=["greeting", "utility"],       # Tags for filtering
    dependencies=["date_service"],      # Required capabilities
)
async def greet(name: str, date_svc: mesh.McpMeshTool = None) -> str:
    if date_svc:
        today = await date_svc()  # Must use await for proxy calls!
        return f"Hello {name}! Today is {today}"
    return f"Hello {name}!"  # Graceful degradation
```

**Note**: Functions with dependencies must be `async def` and proxy calls require `await`.

### Dependency Injection Types

| Type                | Use Case                               |
| ------------------- | -------------------------------------- |
| `mesh.McpMeshTool` | Tool calls via proxy                   |
| `mesh.MeshLlmAgent` | LLM agent injection (with `@mesh.llm`) |

## @mesh.llm

Enables LLM-powered tools with automatic tool discovery.

```python
@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},  # LLM provider selector
    max_iterations=5,                    # Max agentic loop iterations
    system_prompt="file://prompts/agent.jinja2",  # Jinja2 template
    context_param="ctx",                 # Parameter name for context
    filter=[{"tags": ["tools"]}],        # Tool filter for discovery
    filter_mode="all",                   # "all", "best_match", or "*"
)
@mesh.tool(
    capability="smart_assistant",
    description="LLM-powered assistant",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Help the user with their request")
```

**Note**: Response format is determined by return type: `-> str` for text, `-> PydanticModel` for JSON.

### Filter Modes

| Mode         | Description                              |
| ------------ | ---------------------------------------- |
| `all`        | Include all tools matching any filter    |
| `best_match` | One tool per capability (best tag match) |
| `*`          | All available tools (wildcard)           |

## @mesh.llm_provider

Creates a zero-code LLM provider wrapping LiteLLM.

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",  # LiteLLM model string
    capability="llm",                      # Capability name
    tags=["llm", "claude", "provider"],    # Discovery tags
    version="1.0.0",                       # Provider version
)
def claude_provider():
    pass  # No implementation needed
```

## @mesh.route

Enables mesh dependency injection in FastAPI route handlers. Use this when building REST APIs that consume mesh capabilities.

```python
from fastapi import APIRouter, Request
import mesh
from mesh.types import McpMeshTool

router = APIRouter()

@router.post("/chat")
@mesh.route(dependencies=["avatar_chat"])
async def chat_endpoint(
    request: Request,
    message: str,
    avatar_agent: McpMeshTool = None,  # Injected by mesh
):
    result = await avatar_agent(message=message, user_email="user@example.com")
    return {"response": result.get("message")}
```

**Note**: `@mesh.route` is for FastAPI backends that _consume_ mesh capabilities. Use `@mesh.tool` for MCP agents that _provide_ capabilities.

See `meshctl man fastapi` for complete FastAPI integration guide.

## Environment Variable Overrides

All decorator parameters can be overridden via environment variables:

```bash
export MCP_MESH_AGENT_NAME=custom-name
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_NAMESPACE=production
export MCP_MESH_AUTO_RUN=false
```

## See Also

- `meshctl man dependency-injection` - DI details
- `meshctl man llm` - LLM integration guide
- `meshctl man tags` - Tag matching system
- `meshctl man capabilities` - Capabilities system
- `meshctl man fastapi` - FastAPI integration with @mesh.route

---

# DEPENDENCY-INJECTION

# Dependency Injection

> Automatic wiring of capabilities between agents

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a function declares a dependency, the mesh automatically creates a callable proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Function declares dependencies via `@mesh.tool` decorator
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh creates proxy objects for each dependency
5. **Invocation**: Calling the proxy routes to the remote agent

## Declaring Dependencies

### Simple Dependencies

```python
@app.tool()
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],  # Request by capability name
)
async def greet(name: str, date_service: mesh.McpMeshTool = None) -> str:
    if date_service:
        today = await date_service()  # Must use await!
        return f"Hello {name}! Today is {today}"
    return f"Hello {name}!"
```

**Important**: Functions with dependencies must be `async def` and calls must use `await`.

### Dependencies with Filters

Use the capability selector syntax (see `meshctl man capabilities`) to filter by tags or version:

```python
@app.tool()
@mesh.tool(
    capability="report",
    dependencies=[
        {"capability": "data_service", "tags": ["+fast"]},
        {"capability": "formatter", "tags": ["-deprecated"]},
    ],
)
async def generate_report(
    data_svc: mesh.McpMeshTool = None,
    formatter: mesh.McpMeshTool = None,
) -> str:
    data = await data_svc(query="sales")
    return await formatter(data=data)
```

## Injection Types

### mesh.McpMeshTool

Callable proxy for tool invocations:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    result = await helper(arg1="value")  # Direct call
    result = await helper.call_tool("tool_name", {"arg": "value"})  # Named tool
```

### mesh.MeshLlmAgent

For LLM agent injection in `@mesh.llm` decorated functions:

```python
@mesh.llm(...)
def smart_tool(ctx: Context, llm: mesh.MeshLlmAgent = None):
    response = llm("Process this request")
```

## Graceful Degradation

Dependencies may be unavailable. Always handle `None`:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper is None:
        return "Service temporarily unavailable"
    return await helper()
```

Or use default values:

```python
async def get_time(date_service: mesh.McpMeshTool = None):
    if date_service:
        return await date_service()
    return datetime.now().isoformat()  # Fallback
```

## Proxy Configuration

Configure proxy behavior via `dependency_kwargs`:

```python
@mesh.tool(
    dependencies=["slow_service"],
    dependency_kwargs={
        "slow_service": {
            "timeout": 60,           # Request timeout (seconds)
            "retry_count": 3,        # Retry attempts
            "streaming": True,       # Enable streaming
            "session_required": True, # Require session affinity
        }
    },
)
async def my_tool(slow_service: mesh.McpMeshTool = None):
    result = await slow_service(data="large_payload")
    ...
```

## Proxy Types (Auto-Selected)

The mesh automatically selects the appropriate proxy:

| Proxy Type               | Use Case                 |
| ------------------------ | ------------------------ |
| `SelfDependencyProxy`    | Same agent (direct call) |
| `MCPClientProxy`         | Simple tool calls        |
| `EnhancedMCPClientProxy` | Timeout/retry config     |
| `EnhancedFullMCPProxy`   | Streaming/sessions       |

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

## See Also

- `meshctl man capabilities` - Declaring capabilities
- `meshctl man tags` - Tag-based selection
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details

---

# DEPLOYMENT

# Deployment Patterns

> Local, Docker, and Kubernetes deployment options

## Overview

MCP Mesh supports multiple deployment patterns from local development to production Kubernetes clusters. Use `meshctl scaffold` to generate deployment-ready files automatically.

## Official Docker Images

| Image                        | Description                                    |
| ---------------------------- | ---------------------------------------------- |
| `mcpmesh/registry:0.8`       | Registry service for agent discovery           |
| `mcpmesh/python-runtime:0.8` | Python runtime with mcp-mesh SDK pre-installed |

## Local Development

### Setup

Create a virtual environment in your project root. `meshctl start` automatically detects and uses `.venv` if present:

```bash
# Create project and virtual environment
meshctl scaffold --name my-agent --agent-type tool
cd my-agent

# Create .venv (meshctl looks for this first)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install MCP Mesh SDK
pip install "mcp-mesh>=0.8,<0.9"

# Install agent dependencies
pip install -r requirements.txt
```

### Quick Start

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug

# Terminal 2: Start agent (uses .venv automatically)
meshctl start my_agent.py --debug

# Terminal 3: Monitor
watch 'meshctl list'
```

### Multiple Agents

```bash
# Start multiple agents
meshctl start agent1.py agent2.py agent3.py

# Or with specific ports
MCP_MESH_HTTP_PORT=8081 python agent1.py &
MCP_MESH_HTTP_PORT=8082 python agent2.py &
MCP_MESH_HTTP_PORT=8083 python agent3.py &
```

### Development Workflow

For fast iterative development:

```bash
# Watch mode: auto-restart on file changes
meshctl start my_agent.py --watch --debug

# Or run in background
meshctl start my_agent.py --detach

# Stop when done
meshctl stop my_agent      # Stop specific agent
meshctl stop               # Stop all
```

See `meshctl start --help` and `meshctl stop --help` for options.

## Docker Deployment

### Generate Dockerfile (Recommended)

`meshctl scaffold` automatically generates a production-ready Dockerfile:

```bash
# Create agent with Dockerfile
meshctl scaffold --name my-agent --agent-type tool

# Files created:
# my-agent/
#   ├── Dockerfile         # Ready for docker build
#   ├── .dockerignore      # Optimized ignores
#   ├── helm-values.yaml   # K8s deployment values
#   ├── main.py            # Agent code
#   └── requirements.txt
```

The generated Dockerfile uses the official runtime:

```dockerfile
FROM mcpmesh/python-runtime:0.8
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9000
CMD ["python", "main.py"]
```

### Generate Docker Compose (Recommended)

Use `--compose` to auto-generate docker-compose.yml for all agents in a directory:

```bash
# Create multiple agents
meshctl scaffold --name agent1 --port 9000
meshctl scaffold --name agent2 --port 9001

# Generate docker-compose.yml for all agents
meshctl scaffold --compose

# With observability stack (redis, tempo, grafana)
meshctl scaffold --compose --observability
```

Generated docker-compose.yml includes:

- PostgreSQL database for registry
- Registry service (`mcpmesh/registry:0.8`)
- All detected agents with proper networking
- Health checks and dependency ordering
- Optional: Redis, Tempo, Grafana (with `--observability`)

### Running

```bash
docker compose up -d
docker compose logs -f
docker compose ps
```

## Kubernetes Deployment

### Helm Charts (Recommended)

For production Kubernetes deployment, use the official Helm charts from the MCP Mesh OCI registry:

```bash
# Install core infrastructure (registry + database + observability)
# No "helm repo add" needed - uses OCI registry directly
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace

# Deploy agent using scaffold-generated helm-values.yaml
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0 \
  -n mcp-mesh \
  -f my-agent/helm-values.yaml
```

### Available Helm Charts

| Chart                                                | Description                                     |
| ---------------------------------------------------- | ----------------------------------------------- |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core`     | Registry + PostgreSQL + Redis + Tempo + Grafana |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent`    | Deploy individual MCP agents                    |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry` | Registry service only                           |

### Using scaffold-generated helm-values.yaml

Each scaffolded agent includes a `helm-values.yaml` ready for deployment:

```yaml
# my-agent/helm-values.yaml (auto-generated)
image:
  repository: your-registry/my-agent
  tag: latest

agent:
  name: my-agent
  # port: 8080 (default - no need to specify, see "Port Strategy" section)

mesh:
  enabled: true
  registryUrl: http://mcp-core-mcp-mesh-registry:8000

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi
```

### Deployment Workflow

```bash
# 1. Scaffold your agent (creates Dockerfile + helm-values.yaml)
meshctl scaffold --name my-agent --agent-type tool

# 2. Build and push Docker image (works on all platforms)
cd my-agent
docker buildx build --platform linux/amd64 -t your-registry/my-agent:v1.0.0 --push .

# 3. Update helm-values.yaml with your image repository
# 4. Deploy with Helm
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0 \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/my-agent \
  --set image.tag=v1.0.0
```

### Disable Optional Components

```bash
# Core without observability
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace \
  --set grafana.enabled=false \
  --set tempo.enabled=false

# Core without PostgreSQL (in-memory registry)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace \
  --set postgres.enabled=false
```

## Port Strategy: Local vs Kubernetes

Port configuration differs between deployment environments.

| Environment            | Port Strategy                | Why                                   |
| ---------------------- | ---------------------------- | ------------------------------------- |
| Local / docker-compose | Unique ports (9001, 9002...) | All containers share host network     |
| Kubernetes             | All agents use 8080          | Each pod has its own IP, no conflicts |

### Don't Copy docker-compose Ports to Kubernetes

When moving from docker-compose to Kubernetes, do NOT set custom ports:

```yaml
# ❌ WRONG - copying docker-compose ports
agent:
  port: 9001

# ✅ CORRECT - use defaults
agent:
  name: my-agent
  # port: 8080 is the default, no need to specify
```

### How It Works

The Helm chart sets `MCP_MESH_HTTP_PORT=8080` environment variable, which overrides whatever port is in your `@mesh.agent(http_port=9001)` decorator. Your code doesn't need to change.

**Precedence:**

1. `MCP_MESH_HTTP_PORT` env var (set by Helm) ← wins
2. `http_port` in `@mesh.agent()` (used for local dev)

## Best Practices

### Health Checks

Always configure health checks:

```python
async def health_check() -> dict:
    return {
        "status": "healthy",
        "checks": {"database": True},
        "errors": [],
    }

@mesh.agent(
    name="my-service",
    health_check=health_check,
    health_check_ttl=30,
)
class MyAgent:
    pass
```

### Resource Limits

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Graceful Shutdown

```bash
# Configure shutdown timeout
meshctl start my_agent.py --shutdown-timeout 60
```

### Logging

```bash
# Structured logging for production
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false
```

## See Also

- `meshctl scaffold --help` - Generate agents with deployment files
- `meshctl man environment` - Configuration options
- `meshctl man health` - Health monitoring
- `meshctl man registry` - Registry setup

---

# ENVIRONMENT

# Environment Variables

> Configure MCP Mesh via environment variables

## Overview

MCP Mesh can be configured using environment variables. They override `@mesh.agent` decorator parameters and provide flexibility for different deployment environments.

## Configuration Hierarchy

Configuration sources in order of precedence (highest wins):

1. Environment variables (system or `.env` files)
2. meshctl `--env` flags
3. `@mesh.agent` decorator parameters (lowest priority)

**Key point**: Environment variables override decorator parameters. This enables the same code to run locally (using decorator defaults) and in Kubernetes (using Helm-injected env vars) without modification.

## Agent Configuration

### Core Settings

```bash
# Agent identity
export MCP_MESH_AGENT_NAME=my-service
export MCP_MESH_NAMESPACE=production

# HTTP server
export HOST=0.0.0.0              # Bind address
export MCP_MESH_HTTP_PORT=8080   # Server port
export MCP_MESH_HTTP_HOST=my-service  # Announced hostname

# Auto-run behavior
export MCP_MESH_AUTO_RUN=true
export MCP_MESH_AUTO_RUN_INTERVAL=30  # Heartbeat interval (seconds)

# Health monitoring
export MCP_MESH_HEALTH_INTERVAL=30

# Global toggle
export MCP_MESH_ENABLED=true
```

### Registry Connection

```bash
# Full URL
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Or separate host/port
export MCP_MESH_REGISTRY_HOST=localhost
export MCP_MESH_REGISTRY_PORT=8000
```

### Logging

```bash
# Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
export MCP_MESH_LOG_LEVEL=INFO

# Debug mode (forces DEBUG level)
export MCP_MESH_DEBUG_MODE=true
```

### Advanced Settings

```bash
# HTTP server toggle
export MCP_MESH_HTTP_ENABLED=true

# External endpoint (for proxies/load balancers)
export MCP_MESH_HTTP_ENDPOINT=https://api.example.com:443

# Authentication token for secure communication
export MCP_MESH_AUTH_TOKEN=secret-token

# Startup debounce delay (seconds)
export MCP_MESH_DEBOUNCE_DELAY=1.0
```

## LLM Provider Configuration

Required for `@mesh.llm_provider` agents:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# OpenAI
export OPENAI_API_KEY=sk-your-key-here
```

## Observability

```bash
# Telemetry
export MCP_MESH_TELEMETRY_ENABLED=true

# Distributed tracing
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=false

# Redis trace publishing
export MCP_MESH_REDIS_TRACE_PUBLISHING=true
export REDIS_URL=redis://localhost:6379
```

## Registry Configuration

```bash
# Server binding
export HOST=0.0.0.0
export PORT=8000

# Database
export DATABASE_URL=mcp_mesh_registry.db  # SQLite
export DATABASE_URL=postgresql://user:pass@host:5432/db  # PostgreSQL

# Health monitoring
export DEFAULT_TIMEOUT_THRESHOLD=20   # Mark unhealthy (seconds)
export HEALTH_CHECK_INTERVAL=10       # Scan frequency (seconds)
export DEFAULT_EVICTION_THRESHOLD=60  # Evict stale agents (seconds)

# Caching
export CACHE_TTL=30
export ENABLE_RESPONSE_CACHE=true

# CORS
export ENABLE_CORS=true
export ALLOWED_ORIGINS="*"

# Features
export ENABLE_METRICS=true
export ENABLE_PROMETHEUS=true
```

## Environment Profiles

### Development

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_AUTO_RUN_INTERVAL=10
MCP_MESH_HEALTH_INTERVAL=15
HOST=0.0.0.0
```

### Production

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=https://registry.company.com
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
HOST=0.0.0.0
```

### Testing

```bash
# .env.testing
MCP_MESH_LOG_LEVEL=WARNING
MCP_MESH_AUTO_RUN=false
MCP_MESH_REGISTRY_URL=http://test-registry:8000
MCP_MESH_NAMESPACE=testing
```

## Using Environment Files

### With meshctl

```bash
meshctl start my_agent.py --env-file .env.development

# Individual variables
meshctl start my_agent.py --env MCP_MESH_LOG_LEVEL=DEBUG
```

### With Python

```bash
source .env.development
python my_agent.py

# Or use python-dotenv
pip install python-dotenv
```

```python
from dotenv import load_dotenv
load_dotenv('.env.development')
```

## Docker Configuration

```yaml
# docker-compose.yml
services:
  my-agent:
    environment:
      - HOST=0.0.0.0
      - MCP_MESH_HTTP_HOST=my-agent
      - MCP_MESH_HTTP_PORT=8080
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_LOG_LEVEL=INFO
      - MCP_MESH_NAMESPACE=docker
```

## Kubernetes Configuration

```yaml
# deployment.yaml
env:
  - name: MCP_MESH_REGISTRY_URL
    value: "http://registry.mcp-mesh:8000"
  - name: MCP_MESH_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  - name: MCP_MESH_AGENT_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
```

## Debugging

```bash
# Show all MCP Mesh environment variables
env | grep MCP_MESH

# Test specific variable
echo $MCP_MESH_LOG_LEVEL

# Verify with meshctl
meshctl start my_agent.py --env-file .env.dev --debug
```

## Common Issues

### Port Already in Use

```bash
lsof -i :8080
export MCP_MESH_HTTP_PORT=8081
```

### Registry Connection Failed

```bash
curl -s http://localhost:8000/health
export MCP_MESH_REGISTRY_URL=http://backup-registry:8000
```

### Agent Name Conflicts

```bash
export MCP_MESH_AGENT_NAME=my-unique-agent-$(date +%s)
meshctl list
```

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man registry` - Registry configuration
- `meshctl man health` - Health monitoring settings

---

# FASTAPI

# FastAPI Integration

> Use mesh dependency injection in FastAPI backends with @mesh.route

## Overview

MCP Mesh provides `@mesh.route` decorator for FastAPI applications that need to consume mesh capabilities without being MCP agents themselves. This enables traditional REST APIs to leverage the mesh service layer.

**Important**: This is for integrating MCP Mesh into your EXISTING FastAPI app. There is no `meshctl scaffold` command for FastAPI. To create a new MCP agent, use `meshctl scaffold` instead.

## Installation

```bash
pip install mcp-mesh
```

## Two Architectures

| Pattern         | Decorator                    | Use Case                              |
| --------------- | ---------------------------- | ------------------------------------- |
| MCP Agent       | `@mesh.tool` + `@mesh.agent` | Service that _provides_ capabilities  |
| FastAPI Backend | `@mesh.route`                | REST API that _consumes_ capabilities |

```
[Frontend] → [FastAPI Backend] → [MCP Mesh] → [Agents]
                   ↑
            @mesh.route
```

## @mesh.route Decorator

```python
from fastapi import APIRouter, Request
import mesh
from mesh.types import McpMeshTool

router = APIRouter()

@router.post("/chat")
@mesh.route(dependencies=["avatar_chat"])
async def chat(
    request: Request,
    message: str,
    avatar_agent: McpMeshTool = None,  # Injected by mesh
):
    result = await avatar_agent(
        message=message,
        user_email="user@example.com",
    )
    return {"response": result.get("message")}
```

## Dependency Declaration

### Simple (by capability name)

```python
@mesh.route(dependencies=["user_service", "notification_service"])
async def handler(
    user_svc: McpMeshTool = None,
    notif_svc: McpMeshTool = None,
):
    ...
```

### With Tag Filtering

```python
@mesh.route(dependencies=[
    {"capability": "llm", "tags": ["+claude"]},
    {"capability": "storage", "tags": ["-deprecated"]},
])
async def handler(
    llm_agent: McpMeshTool = None,
    storage_agent: McpMeshTool = None,
):
    ...
```

## Complete Example

```python
from fastapi import FastAPI, APIRouter, Request, HTTPException
import mesh
from mesh.types import McpMeshTool
from pydantic import BaseModel

app = FastAPI(title="My Backend")
router = APIRouter(prefix="/api", tags=["api"])

class ChatRequest(BaseModel):
    message: str
    avatar_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    avatar_id: str

@router.post("/chat", response_model=ChatResponse)
@mesh.route(dependencies=["avatar_chat"])
async def chat_endpoint(
    request: Request,
    chat_req: ChatRequest,
    avatar_agent: McpMeshTool = None,
):
    """Chat endpoint that delegates to mesh avatar agent."""
    if avatar_agent is None:
        raise HTTPException(503, "Avatar service unavailable")

    result = await avatar_agent(
        message=chat_req.message,
        avatar_id=chat_req.avatar_id,
        user_email="user@example.com",
    )

    return ChatResponse(
        response=result.get("message", ""),
        avatar_id=chat_req.avatar_id,
    )

@router.get("/history")
@mesh.route(dependencies=["conversation_history_get"])
async def get_history(
    request: Request,
    avatar_id: str = "default",
    limit: int = 50,
    history_agent: McpMeshTool = None,
):
    """Get conversation history from mesh agent."""
    result = await history_agent(
        avatar_id=avatar_id,
        limit=limit,
    )
    return {"messages": result.get("messages", [])}

app.include_router(router)
```

## Running Your FastAPI App

Run your existing FastAPI application as you normally would:

```bash
export MCP_MESH_REGISTRY_URL=http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8080
```

**Note**: Unlike MCP agents, FastAPI backends are NOT started with `meshctl start`.

The backend will:

1. Connect to the mesh registry on startup
2. Resolve dependencies declared in `@mesh.route`
3. Inject `McpMeshTool` proxies into route handlers
4. Re-resolve on topology changes (auto-rewiring)

## Key Differences from @mesh.tool

| Aspect                | @mesh.tool   | @mesh.route                     |
| --------------------- | ------------ | ------------------------------- |
| Registers with mesh   | Yes          | No                              |
| Provides capabilities | Yes          | No                              |
| Consumes capabilities | Yes          | Yes                             |
| Has heartbeat         | Yes          | Yes (for dependency resolution) |
| Protocol              | MCP JSON-RPC | REST/HTTP                       |
| Use case              | Microservice | API Gateway/Backend             |

## When to Use @mesh.route

- Building a REST API that fronts mesh services
- API gateway pattern
- Backend-for-Frontend (BFF) services
- Adding REST endpoints to existing FastAPI apps
- When you need traditional HTTP semantics (REST, OpenAPI docs)

## When to Use @mesh.tool Instead

- Building reusable mesh capabilities
- Service-to-service communication
- LLM tool providers
- When other agents need to discover and call your service

## See Also

- `meshctl man decorators` - All mesh decorators
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration

---

# HEALTH

# Health Monitoring & Auto-Rewiring

> Fast heartbeat system and automatic topology updates

## Overview

MCP Mesh uses a dual-heartbeat system for fast failure detection and automatic topology updates. Agents maintain connectivity with the registry, and the mesh automatically rewires dependencies when agents join or leave.

## Heartbeat System

### Dual-Heartbeat Design

| Type | Frequency  | Size  | Purpose                  |
| ---- | ---------- | ----- | ------------------------ |
| HEAD | ~5 seconds | ~200B | Lightweight keep-alive   |
| POST | On change  | ~2KB  | Full registration update |

### How It Works

1. Agent sends HEAD request every 5 seconds
2. Registry responds with status:
   - `200 OK`: No changes
   - `202 Accepted`: Topology changed, refresh needed
   - `410 Gone`: Agent unknown, re-register
3. On `202`, agent sends POST with full registration
4. Registry returns updated dependency topology

### Failure Detection

- Registry marks agents unhealthy after missed heartbeats
- Default threshold: 20 seconds (4 missed 5-second heartbeats)
- Configurable via environment variables

## Registry Health Monitor

Background process that:

- Scans for agents past timeout threshold
- Marks unhealthy agents in database
- Generates audit events for topology changes
- Triggers `202` responses to notify other agents

## Configuration

### Agent Settings

```bash
# Heartbeat interval (seconds)
export MCP_MESH_AUTO_RUN_INTERVAL=30

# Health check interval (seconds)
export MCP_MESH_HEALTH_INTERVAL=30
```

### Registry Settings

```bash
# When to mark agents unhealthy (seconds)
export DEFAULT_TIMEOUT_THRESHOLD=20

# How often to scan for unhealthy agents (seconds)
export HEALTH_CHECK_INTERVAL=10

# When to evict stale agents (seconds)
export DEFAULT_EVICTION_THRESHOLD=60
```

### Performance Profiles

**Development (fast feedback)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=10
HEALTH_CHECK_INTERVAL=5
```

**Production (balanced)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=20
HEALTH_CHECK_INTERVAL=10
```

**High-Performance (sub-5s detection)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=5
HEALTH_CHECK_INTERVAL=2
```

## Auto-Rewiring

When topology changes, the mesh automatically:

1. **Detects change**: Via heartbeat response (`202`)
2. **Fetches new topology**: Registry returns updated dependencies
3. **Compares hashes**: Prevents unnecessary updates
4. **Refreshes proxies**: Creates new proxy objects
5. **Routes traffic**: New calls go to updated providers

### Code Impact

None! Auto-rewiring is transparent:

```python
@mesh.tool(dependencies=["date_service"])
def my_tool(date_svc: mesh.McpMeshTool = None):
    # If date_service agent restarts or is replaced,
    # the proxy automatically points to new instance
    return date_svc()
```

## Custom Health Checks

Add custom health checks to your agent:

```python
async def my_health_check() -> dict:
    # Check your dependencies
    db_ok = await check_database()
    api_ok = await check_external_api()

    return {
        "status": "healthy" if (db_ok and api_ok) else "unhealthy",
        "checks": {
            "database": db_ok,
            "external_api": api_ok,
        },
        "errors": [] if (db_ok and api_ok) else ["Some checks failed"],
    }

@mesh.agent(
    name="my-service",
    health_check=my_health_check,
    health_check_ttl=30,  # Cache health for 30 seconds
)
class MyAgent:
    pass
```

## Graceful Failure

The mesh handles failures gracefully:

- **Registry down**: Existing agent-to-agent communication continues
- **Agent down**: Dependencies return `None`, code handles gracefully
- **Network partition**: Agents continue with cached topology
- **Recovery**: Automatic reconnection and topology refresh

## Monitoring

```bash
# Check overall mesh health
meshctl status

# Verbose status with heartbeat info
meshctl status --verbose

# List agents with health status
meshctl list

# JSON output for automation
meshctl status --json
```

## See Also

- `meshctl man registry` - Registry operations
- `meshctl man dependency-injection` - How DI handles failures
- `meshctl man environment` - Configuration options

---

# LLM

# LLM Integration

> Building LLM-powered agents with @mesh.llm decorator

## Overview

MCP Mesh provides first-class support for LLM-powered agents through the `@mesh.llm` decorator. This enables agentic loops where LLMs can discover and use mesh tools automatically.

## @mesh.llm Decorator

```python
@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=5,
    system_prompt="file://prompts/assistant.jinja2",
    context_param="ctx",
    filter=[{"tags": ["tools"]}],
    filter_mode="all",
)
@mesh.tool(
    capability="smart_assistant",
    description="LLM-powered assistant",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Help the user with their request")
```

## Parameters

| Parameter        | Type | Description                                       |
| ---------------- | ---- | ------------------------------------------------- |
| `provider`       | dict | LLM provider selector (capability + tags)         |
| `max_iterations` | int  | Max agentic loop iterations (default: 1)          |
| `system_prompt`  | str  | Inline prompt or `file://path` to Jinja2 template |
| `context_param`  | str  | Parameter name receiving context object           |
| `filter`         | list | Tool filter criteria                              |
| `filter_mode`    | str  | `"all"`, `"best_match"`, or `"*"`                 |
| `<llm_params>`   | any  | LiteLLM params (max_tokens, temperature, etc.)    |

**Note**: `provider` and `filter` use the capability selector syntax (`capability`, `tags`, `version`). See `meshctl man capabilities` for details.

**Note**: Response format is determined by the function's return type annotation, not a parameter. See [Response Formats](#response-formats).

## LLM Model Parameters

Pass any LiteLLM parameter in the decorator as defaults:

```python
@mesh.llm(
    provider={"capability": "llm"},
    max_tokens=16000,
    temperature=0.7,
    top_p=0.9,
)
def assist(ctx, llm = None):
    # Uses decorator defaults
    return llm("Help the user")

    # Override at call time
    return llm("Help", max_tokens=8000)
```

Call-time parameters take precedence over decorator defaults.

## Response Metadata

LLM results include `_mesh_meta` for cost tracking and debugging:

```python
result = await llm("Analyze this")
print(result._mesh_meta.model)          # "openai/gpt-4o"
print(result._mesh_meta.input_tokens)   # 100
print(result._mesh_meta.output_tokens)  # 50
print(result._mesh_meta.latency_ms)     # 125.5
```

## LLM Provider Selection

Select LLM provider using capability and tags:

```python
# Prefer Claude
provider={"capability": "llm", "tags": ["+claude"]}

# Require OpenAI
provider={"capability": "llm", "tags": ["openai"]}

# Any LLM provider
provider={"capability": "llm"}
```

### Model Override

Override provider's default model at the consumer:

```python
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    model="anthropic/claude-haiku",  # Override provider default
)
def fast_assist(ctx, llm = None):
    return llm("Quick response needed")
```

Vendor mismatch (e.g., requesting OpenAI model from Claude provider) logs a warning and falls back to provider default.

## Creating LLM Providers

Use `@mesh.llm_provider` for zero-code LLM providers:

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["llm", "claude", "provider"],
    version="1.0.0",
)
def claude_provider():
    pass  # No implementation needed

@mesh.agent(name="claude-provider", http_port=9110)
class ClaudeProviderAgent:
    pass
```

### Supported Models (LiteLLM)

```
anthropic/claude-sonnet-4-5
anthropic/claude-sonnet-4-20250514
openai/gpt-4o
openai/gpt-4-turbo
openai/gpt-3.5-turbo
```

## Tool Filtering

Control which mesh tools the LLM can access using `filter` and `filter_mode`:

```python
filter=[{"tags": ["tools"]}],      # By tags
filter=[{"capability": "calc"}],   # By capability
filter_mode="*",                   # All tools (wildcard)
# Omit filter for no tools (LLM only)
```

For tag operators (+/-), matching algorithm, and advanced patterns, see `meshctl man tags`.

## System Prompts

### Inline Prompt

```python
system_prompt="You are a helpful assistant. Analyze the input and respond."
```

### Jinja2 Template File

```python
system_prompt="file://prompts/assistant.jinja2"
```

Template example:

```jinja2
You are {{ agent_name }}, an AI assistant.

## Context
{{ input_text }}

## Instructions
Analyze the input and provide a helpful response.
Available tools: {{ tools | join(", ") }}
```

**Note**: Context fields are accessed directly (`{{ input_text }}`), not via prefix.

## Context Objects

Define typed context with Pydantic:

```python
from pydantic import BaseModel, Field

class AssistContext(BaseModel):
    input_text: str = Field(..., description="User's request")
    user_id: str = Field(default="anonymous")
    preferences: dict = Field(default_factory=dict)

@mesh.llm(context_param="ctx", ...)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    return llm(f"Help with: {ctx.input_text}")
```

## Response Formats

Response format is determined by the **return type annotation** - not a decorator parameter.

| Return Type        | Output          | Description                   |
| ------------------ | --------------- | ----------------------------- |
| `-> str`           | Plain text      | LLM returns unstructured text |
| `-> PydanticModel` | Structured JSON | LLM returns validated object  |

### Text Response

```python
@mesh.llm(provider={"capability": "llm"}, ...)
@mesh.tool(capability="summarize")
def summarize(ctx: SummaryContext, llm: mesh.MeshLlmAgent = None) -> str:
    return llm("Summarize the input")  # Returns plain text
```

### Structured JSON Response

```python
class AssistResponse(BaseModel):
    answer: str
    confidence: float
    sources: list[str]

@mesh.llm(provider={"capability": "llm"}, ...)
@mesh.tool(capability="smart_assistant")
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Analyze and respond")  # Returns validated Pydantic object
```

## Agentic Loops

Set `max_iterations` for multi-step reasoning:

```python
@mesh.llm(
    max_iterations=10,  # Allow up to 10 tool calls
    filter=[{"tags": ["tools"]}],
)
def complex_task(ctx: TaskContext, llm: mesh.MeshLlmAgent = None):
    return llm("Complete this multi-step task")
```

The LLM will:

1. Analyze the request
2. Call discovered tools as needed
3. Use tool results for further reasoning
4. Return final response

## Runtime Context Injection

Pass additional context at call time to merge with or override auto-populated context:

```python
@mesh.llm(
    system_prompt="file://prompts/assistant.jinja2",
    context_param="ctx",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    # Default: uses ctx from context_param
    return llm("Help the user")

    # Add extra context (runtime wins on conflicts)
    return llm("Help", context={"extra_info": "value"})

    # Auto context wins on conflicts
    return llm("Help", context={"extra": "value"}, context_mode="prepend")

    # Replace context entirely
    return llm("Help", context={"only": "this"}, context_mode="replace")
```

### Context Modes

| Mode      | Behavior                                    |
| --------- | ------------------------------------------- |
| `append`  | auto_context \| runtime_context (default)   |
| `prepend` | runtime_context \| auto_context (auto wins) |
| `replace` | runtime_context only (ignores auto)         |

### Use Cases

**Multi-turn conversations** with state:

```python
async def chat(ctx: ChatContext, llm: mesh.MeshLlmAgent = None):
    # First turn
    response1 = await llm("Hello", context={"turn": 1})

    # Second turn with accumulated context
    response2 = await llm("Continue", context={"turn": 2, "prev": response1})

    return response2
```

**Conditional context**:

```python
async def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    extra = {"premium": True} if ctx.user.is_premium else {}
    return await llm("Help", context=extra)
```

**Clear context** when not needed:

```python
# Explicitly clear all context
return await llm("Standalone query", context={}, context_mode="replace")
```

## Scaffolding LLM Agents

```bash
# Generate LLM agent
meshctl scaffold --name my-agent --agent-type llm-agent --llm-selector claude

# Generate LLM provider
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5
```

## See Also

- `meshctl man decorators` - All decorator options
- `meshctl man tags` - Tag matching for providers
- `meshctl man testing` - Testing LLM agents

---

# OBSERVABILITY

# Observability

> Distributed tracing and monitoring for MCP Mesh agents

## Overview

MCP Mesh provides built-in observability through:

- **CLI tracing**: Quick debugging with `meshctl call --trace`
- **Grafana dashboards**: Production monitoring with Tempo backend

## CLI Tracing

### Get trace IDs

```bash
# Add --trace flag to any call
meshctl call my-agent:my_tool --trace
# Output includes: Trace ID: abc123def456...
```

### View trace tree

```bash
# View the full call tree
meshctl trace abc123def456

# Output as JSON
meshctl trace abc123def456 --json

# Show internal spans (usually hidden)
meshctl trace abc123def456 --show-internal
```

### Example output

```
Call Tree for trace abc123def456
════════════════════════════════════════════════════════════

└─ process_request (orchestrator) [45ms] ✓
   ├─ validate_input (validator) [5ms] ✓
   └─ execute_task (worker) [38ms] ✓
      └─ fetch_data (data-service) [30ms] ✓

────────────────────────────────────────────────────────────
Summary: 4 spans across 4 agents | 45ms | ✓
Agents: orchestrator, validator, worker, data-service
```

## Production Monitoring (Grafana)

### Setup with Docker Compose

```bash
# Generate docker-compose with observability stack
meshctl scaffold --compose --observability

# Starts: Redis, Tempo, Grafana
docker compose up -d
```

### Setup with Kubernetes

```bash
# Install core with observability enabled (default)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace

# Or disable observability
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace \
  --set tempo.enabled=false \
  --set grafana.enabled=false
```

### Access Grafana

| Deployment     | URL                                                      |
| -------------- | -------------------------------------------------------- |
| Docker Compose | http://localhost:3000                                    |
| Kubernetes     | `kubectl port-forward svc/grafana 3000:3000 -n mcp-mesh` |

Default credentials: `admin` / `admin`

### Pre-built Dashboards

- **MCP Mesh Overview**: Agent health, request rates, error rates
- **Trace Explorer**: Search and visualize distributed traces
- **Agent Details**: Per-agent metrics and traces

## Environment Variables

| Variable                               | Description     | Default             |
| -------------------------------------- | --------------- | ------------------- |
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | Enable tracing  | `false`             |
| `TRACE_EXPORTER_TYPE`                  | Exporter type   | `otlp`              |
| `TELEMETRY_ENDPOINT`                   | Tempo endpoint  | `tempo:4317`        |
| `TELEMETRY_PROTOCOL`                   | Protocol        | `grpc`              |
| `TEMPO_URL`                            | Tempo query URL | `http://tempo:3200` |

## Troubleshooting

### "Trace not found"

Possible reasons:

- Trace ID incorrect or expired (traces expire after ~1 hour by default)
- Distributed tracing not enabled (`MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true`)
- Observability stack not deployed

### Traces not appearing in Grafana

1. Check Tempo is running: `docker compose ps tempo`
2. Check agent has tracing enabled in environment
3. Verify network connectivity between agents and Tempo

## See Also

- `meshctl man deployment` - Setup Docker/Kubernetes
- `meshctl man scaffold` - Generate observability stack
- `meshctl trace --help` - Trace command options

---

# OVERVIEW

# MCP Mesh

> Production-grade distributed mesh for intelligent agents

## Why MCP Mesh?

Traditional frameworks treat AI agents like dumb microservices—central orchestrators create them, control them, wire them together.

MCP Mesh takes a different view: agents are intelligent. Let them behave that way.

Agents self-organize—discovering collaborators, adapting to failures, forming dynamic partnerships. The mesh provides the environment; the intelligence does the rest.

## Core Principles

- **Agents are autonomous**: Each agent runs independently and communicates directly with other agents
- **LLMs are first-class capabilities**: LLM agents are discoverable and callable like any tool—tools can invoke LLMs, LLMs can invoke other LLMs, no artificial hierarchy
- **Registry is a facilitator**: The registry helps agents find each other but doesn't proxy communication
- **Graceful degradation**: If a dependency is unavailable, agents continue operating with reduced functionality
- **Zero boilerplate**: Decorators handle all the complex wiring automatically

## Key Components

### 1. Registry

The central coordination service that:

- Accepts agent registrations via heartbeat
- Stores capability metadata in database (SQLite or PostgreSQL)
- Resolves dependencies when agents request them
- Monitors agent health and marks unhealthy agents
- Never calls agents directly - agents always initiate communication

### 2. Agents

Python services decorated with `@mesh.agent` that:

- Register capabilities with the registry on startup
- Send periodic heartbeats to maintain registration
- Receive dependency topology from registry
- Communicate directly with other agents via FastMCP

### 3. Capabilities

Named services that agents provide:

- Identified by capability name (e.g., "date_service", "weather_data")
- Can have multiple implementations with different tags
- Resolved by registry based on name, tags, and version constraints

### 4. Dependencies

Capabilities that an agent needs from other agents:

- Declared in `@mesh.tool` decorator via `dependencies` parameter
- Automatically injected as callable proxies at runtime
- Gracefully handle unavailability (injected as `None`)

## Communication Flow

```
┌─────────┐     Heartbeat/Register     ┌──────────┐
│  Agent  │ ─────────────────────────► │ Registry │
│    A    │ ◄───────────────────────── │          │
└─────────┘   Topology (dependencies)  └──────────┘
     │
     │ Direct MCP Call (tool invocation)
     ▼
┌─────────┐
│  Agent  │
│    B    │
└─────────┘
```

## Heartbeat System

MCP Mesh uses a dual-heartbeat system for fast topology detection:

- **HEAD requests** every ~5 seconds (lightweight, ~200 bytes)
- **POST requests** when topology changes (full registration, ~2KB)
- Registry detects failures in sub-20 seconds (4 missed heartbeats)

## See Also

- `meshctl man capabilities` - Capabilities system details
- `meshctl man dependency-injection` - How DI works
- `meshctl man health` - Health monitoring and auto-rewiring
- `meshctl man registry` - Registry operations

---

# PREREQUISITES

# Prerequisites

> What you need before building MCP Mesh agents

## Windows Users

`meshctl` and `mcp-mesh-registry` require a Unix-like environment on Windows:

- **WSL2** (recommended) - Full Linux environment
- **Git Bash** - Lightweight option

Alternatively, use Docker Desktop for containerized development.

## Local Development

For developing and testing agents locally.

### Python 3.11+

```bash
# Check version
python3 --version  # Need 3.11+

# Install if needed
brew install python@3.11          # macOS
sudo apt install python3.11       # Ubuntu/Debian
```

### Virtual Environment (Recommended)

Create a virtual environment at your **project root** (where you run `meshctl`).
All agents share this single venv - do not create separate venvs inside agent folders.

> **Note:** `meshctl` is a Go binary that auto-detects `.venv` in the current directory.
> You only need to activate the venv for `pip` commands - meshctl commands work without activation.

```bash
# At project root - create venv (one-time setup)
python3.11 -m venv .venv

# Activate only when using pip
source .venv/bin/activate         # macOS/Linux
.venv\Scripts\activate            # Windows
pip install --upgrade pip
```

### MCP Mesh SDK

```bash
pip install "mcp-mesh>=0.8,<0.9"

# Verify
python -c "import mesh; print('Ready!')"
```

### Quick Start

```bash
# 1. Create venv and install SDK (one-time setup)
python3.11 -m venv .venv
source .venv/bin/activate    # Only needed for pip
pip install --upgrade pip
pip install "mcp-mesh>=0.8,<0.9"
deactivate                   # Can deactivate after pip install

# 2. Scaffold agents - meshctl auto-detects .venv (no activation needed)
meshctl scaffold --name hello --agent-type basic
meshctl scaffold --name assistant --agent-type llm-agent

# 3. Run agent - meshctl uses .venv/bin/python automatically
meshctl start hello/main.py --debug
```

## Docker Deployment

For containerized deployments.

### Docker & Docker Compose

```bash
# Check installation
docker --version
docker compose version
```

### MCP Mesh Images

| Image                        | Description             |
| ---------------------------- | ----------------------- |
| `mcpmesh/registry:0.8`       | Registry service        |
| `mcpmesh/python-runtime:0.8` | Python runtime with SDK |

```bash
# Pull images
docker pull mcpmesh/registry:0.8
docker pull mcpmesh/python-runtime:0.8
```

### Generate Docker Compose

```bash
meshctl scaffold --compose              # Basic stack
meshctl scaffold --compose --observability  # With Grafana/Tempo
```

## Kubernetes Deployment

For production Kubernetes clusters.

### kubectl

```bash
kubectl version --client
```

### Helm 3+

```bash
helm version
```

### MCP Mesh Helm Charts

Available from OCI registry (no `helm repo add` needed):

| Chart                                             | Description                   |
| ------------------------------------------------- | ----------------------------- |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core`  | Registry + DB + Observability |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent` | Deploy agents                 |

```bash
# Install core infrastructure
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0 \
  -n mcp-mesh --create-namespace

# Deploy an agent
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0 \
  -n mcp-mesh \
  -f helm-values.yaml
```

### Cluster Options

- **Minikube** - Local testing
- **Kind** - Lightweight local clusters
- **Cloud** - GKE, EKS, AKS for production

## Version Compatibility

| Component  | Minimum | Recommended |
| ---------- | ------- | ----------- |
| Python     | 3.11    | 3.12        |
| Docker     | 20.10   | Latest      |
| Kubernetes | 1.25    | 1.28+       |
| Helm       | 3.10    | 3.14+       |

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man environment` - Configuration options
- `meshctl scaffold --help` - Generate agents

---

# PROXIES

# Proxy System & Communication

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

**Important**: All proxy calls are async and require `await`.

### Simple Call

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper()  # Call default tool
```

### Named Tool Call

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper.call_tool("specific_tool", {"arg": "value"})
```

### With Arguments

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper(city="London", units="metric")
```

## Proxy Configuration

Configure via `dependency_kwargs` in the decorator:

```python
@mesh.tool(
    dependencies=["slow_service"],
    dependency_kwargs={
        "slow_service": {
            "timeout": 60,              # Request timeout (seconds)
            "retry_count": 3,           # Retry attempts on failure
            "custom_headers": {         # Custom HTTP headers
                "X-Request-ID": "...",
            },
            "streaming": True,          # Enable streaming responses
            "session_required": True,   # Require session affinity
            "auth_required": True,      # Require authentication
            "stateful": True,           # Mark as stateful
            "auto_session_management": True,  # Auto session lifecycle
        }
    },
)
async def my_tool(slow_service: mesh.McpMeshTool = None):
    result = await slow_service(data="payload")
    ...
```

## Configuration Options

| Option                    | Type | Default | Description                 |
| ------------------------- | ---- | ------- | --------------------------- |
| `timeout`                 | int  | 30      | Request timeout in seconds  |
| `retry_count`             | int  | 0       | Number of retry attempts    |
| `streaming`               | bool | False   | Enable streaming responses  |
| `session_required`        | bool | False   | Require session affinity    |
| `auth_required`           | bool | False   | Require authentication      |
| `stateful`                | bool | False   | Mark capability as stateful |
| `auto_session_management` | bool | False   | Auto manage sessions        |
| `custom_headers`          | dict | {}      | Additional HTTP headers     |

## Streaming

Enable streaming for real-time data:

```python
@mesh.tool(
    dependencies=["stream_service"],
    dependency_kwargs={
        "stream_service": {"streaming": True}
    },
)
async def process_stream(stream_svc: mesh.McpMeshTool = None):
    async for chunk in stream_svc.stream("data"):
        process(chunk)
```

## Session Affinity

For stateful services, ensure requests go to the same instance:

```python
@mesh.tool(
    dependencies=["stateful_service"],
    dependency_kwargs={
        "stateful_service": {
            "session_required": True,
            "auto_session_management": True,
        }
    },
)
async def stateful_operation(svc: mesh.McpMeshTool = None):
    # All calls routed to same instance
    await svc.initialize()
    result = await svc.process()
    await svc.cleanup()
```

## Error Handling

Proxies handle errors gracefully:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper is None:
        return "Service unavailable"

    try:
        return await helper()
    except TimeoutError:
        return "Service timed out"
    except ConnectionError:
        return "Cannot reach service"
```

## Direct Communication

Agents communicate directly - no proxy server:

- Registry provides endpoint information
- Agents call each other via HTTP
- Minimal latency (no intermediary)
- Continues working if registry is down

## See Also

- `meshctl man dependency-injection` - DI overview
- `meshctl man health` - Auto-rewiring on failure
- `meshctl man testing` - Testing agent communication

---

# REGISTRY

# Registry Operations

> Central coordination service for agent discovery and dependency resolution

## Overview

The registry is the central coordination service in MCP Mesh. It facilitates agent discovery and dependency resolution but never proxies communication - agents communicate directly with each other.

## Registry Role

The registry is a **facilitator, not a controller**:

- Accepts agent registrations via heartbeat
- Stores capability metadata in database
- Resolves dependencies on request
- Monitors health and marks unhealthy agents
- Never calls agents - agents always initiate

## Starting the Registry

### With meshctl (Recommended)

```bash
# Start registry only
meshctl start --registry-only

# Start registry on custom port
meshctl start --registry-only --registry-port 9000

# Start registry with debug logging
meshctl start --registry-only --debug
```

### With npm (Standalone Registry)

```bash
# Install registry via npm
npm install -g @mcpmesh/cli

# Start registry directly
mcp-mesh-registry --host 0.0.0.0 --port 8000
```

## Configuration

### Environment Variables

```bash
# Server binding
export HOST=0.0.0.0
export PORT=8000

# Database
export DATABASE_URL=mcp_mesh_registry.db  # SQLite
export DATABASE_URL=postgresql://user:pass@host:5432/db  # PostgreSQL

# Health monitoring
export DEFAULT_TIMEOUT_THRESHOLD=20  # Mark unhealthy after (seconds)
export HEALTH_CHECK_INTERVAL=10      # Scan frequency (seconds)
export DEFAULT_EVICTION_THRESHOLD=60 # Remove stale agents (seconds)

# Caching
export CACHE_TTL=30
export ENABLE_RESPONSE_CACHE=true

# Logging
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false
```

## API Endpoints

| Endpoint        | Method    | Description            |
| --------------- | --------- | ---------------------- |
| `/health`       | GET       | Registry health check  |
| `/agents`       | GET       | List registered agents |
| `/agents/{id}`  | GET       | Get agent details      |
| `/capabilities` | GET       | List all capabilities  |
| `/register`     | POST      | Register/update agent  |
| `/heartbeat`    | HEAD/POST | Agent heartbeat        |

## Dependency Resolution

When an agent requests dependencies, the registry:

1. **Finds providers**: Agents with matching capability
2. **Applies filters**: Tag and version constraints
3. **Scores matches**: Preferred tags add points
4. **Returns topology**: Selected providers for each dependency

### Resolution Request

```json
{
  "agent_id": "hello-world",
  "dependencies": [
    { "capability": "date_service" },
    { "capability": "weather", "tags": ["+fast"] }
  ]
}
```

### Resolution Response

```json
{
  "dependencies": {
    "date_service": {
      "agent_id": "system-agent",
      "endpoint": "http://localhost:8081",
      "capability": "date_service"
    },
    "weather": {
      "agent_id": "weather-premium",
      "endpoint": "http://localhost:8082",
      "capability": "weather"
    }
  }
}
```

## Database Storage

### SQLite (Development)

```bash
export DATABASE_URL=mcp_mesh_registry.db
```

Simple, no setup, good for development and single-node.

### PostgreSQL (Production)

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/mcp_mesh
```

Better for production: concurrent access, persistence, replication.

## Monitoring

```bash
# Check registry health
curl http://localhost:8000/health

# List all agents
curl http://localhost:8000/agents | jq .

# Get specific agent
curl http://localhost:8000/agents/hello-world | jq .

# Using meshctl
meshctl status
meshctl list
```

## High Availability (Future)

Planned features:

- Multi-registry federation
- Cross-cluster discovery
- Leader election

## See Also

- `meshctl man health` - Health monitoring details
- `meshctl man capabilities` - Capability registration
- `meshctl man environment` - All configuration options

---

# SCAFFOLD

# Agent Scaffolding

> Generate MCP Mesh agents from templates

## Input Modes

| Mode        | Usage                                                | Best For         |
| ----------- | ---------------------------------------------------- | ---------------- |
| Interactive | `meshctl scaffold`                                   | First-time users |
| CLI flags   | `meshctl scaffold --name my-agent --agent-type tool` | Scripting        |
| Config file | `meshctl scaffold --config scaffold.yaml`            | Complex agents   |

## Agent Types

| Type           | Decorator            | Description                               |
| -------------- | -------------------- | ----------------------------------------- |
| `tool`         | `@mesh.tool`         | Basic capability agent                    |
| `llm-agent`    | `@mesh.llm`          | LLM-powered agent that consumes providers |
| `llm-provider` | `@mesh.llm_provider` | Zero-code LLM provider                    |

## Quick Examples

```bash
# Basic tool agent
meshctl scaffold --name my-agent --agent-type tool

# LLM agent using Claude
meshctl scaffold --name analyzer --agent-type llm-agent --llm-selector claude

# LLM provider exposing GPT-4
meshctl scaffold --name gpt-provider --agent-type llm-provider --model openai/gpt-4

# Preview without creating files
meshctl scaffold --name my-agent --agent-type tool --dry-run

# Non-interactive mode (for CI/scripts)
meshctl scaffold --name my-agent --agent-type tool --no-interactive
```

## Adding Tools to Existing Agents

```bash
# Add a basic tool
meshctl scaffold --name my-agent --add-tool new_function --tool-type mesh.tool

# Add an LLM-powered tool
meshctl scaffold --name my-agent --add-tool smart_function --tool-type mesh.llm
```

## Docker Compose Generation

```bash
# Generate docker-compose.yml for all agents in current directory
meshctl scaffold --compose

# Include observability stack (Redis, Tempo, Grafana)
meshctl scaffold --compose --observability

# Custom project name
meshctl scaffold --compose --project-name my-project
```

## Key Flags

| Flag               | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `--name`           | Agent name (required for non-interactive)            |
| `--agent-type`     | `tool`, `llm-agent`, or `llm-provider`               |
| `--dry-run`        | Preview generated code                               |
| `--no-interactive` | Disable prompts (for scripting)                      |
| `--output`         | Output directory (default: `.`)                      |
| `--port`           | HTTP port (default: 9000)                            |
| `--model`          | LiteLLM model for llm-provider                       |
| `--llm-selector`   | LLM provider for llm-agent: `claude`, `openai`       |
| `--filter`         | Tool filter for llm-agent (capability selector JSON) |
| `--compose`        | Generate docker-compose.yml                          |
| `--observability`  | Add Redis/Tempo/Grafana to compose                   |

The `--filter` flag uses capability selector syntax. See `meshctl man capabilities` for details.

```bash
# Filter tools by capability
meshctl scaffold --name analyzer --agent-type llm-agent --filter '[{"capability": "calculator"}]'

# Filter tools by tags
meshctl scaffold --name analyzer --agent-type llm-agent --filter '[{"tags": ["tools"]}]'
```

## Hybrid Development Workflow

Run agents locally with `meshctl start` while using Docker for infrastructure and tracing:

```bash
# 1. Create registry + observability stack (no agents needed)
meshctl scaffold --compose --observability
docker compose up -d

# 2. Create .env file for local agents
cat > .env << 'EOF'
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
TRACE_EXPORTER_TYPE=otlp
TELEMETRY_ENDPOINT=localhost:4317
EOF

# 3. Run agents locally with file watching
meshctl start agent.py --watch --env-file .env
```

Benefits:
- Fast local development (edit code, auto-reload with `--watch`)
- Full observability (traces in Grafana at http://localhost:3000)
- Shared registry (all agents discover each other)

See `meshctl man environment` for all configuration options.

## See Also

- `meshctl man decorators` - Decorator reference
- `meshctl man llm` - LLM integration guide
- `meshctl man deployment` - Docker and Kubernetes deployment

---

# TAGS

# Tag Matching System

> Smart service selection using tags with +/- operators

## Overview

Tags are metadata labels attached to capabilities that enable intelligent service selection. MCP Mesh supports "smart matching" with operators that express preferences and exclusions.

Tags are part of the **Capability Selector** syntax used throughout MCP Mesh. See `meshctl man capabilities` for the complete selector reference.

## Tag Operators (Consumer Side)

Use these operators when **selecting** capabilities (dependencies, providers, filters):

| Prefix | Meaning   | Example                                 |
| ------ | --------- | --------------------------------------- |
| (none) | Required  | `"api"` - must have this tag            |
| `+`    | Preferred | `"+fast"` - bonus if present            |
| `-`    | Excluded  | `"-deprecated"` - hard failure if found |

**Note:** Operators are for consumers only. When declaring tags on your tool, use plain strings without +/- prefixes.

## Declaring Tags (Provider Side)

```python
@mesh.tool(
    capability="weather_data",
    tags=["weather", "current", "api", "free"],
)
def get_weather(city: str): ...
```

## Using Tags in Dependencies

### Simple Tag Filter

```python
@mesh.tool(
    dependencies=[
        {"capability": "weather_data", "tags": ["api"]},
    ],
)
def my_tool(weather: mesh.McpMeshTool = None): ...
```

### Smart Matching with Operators

```python
@mesh.tool(
    dependencies=[
        {
            "capability": "weather_data",
            "tags": [
                "api",           # Required: must have "api" tag
                "+accurate",     # Preferred: bonus if "accurate"
                "+fast",         # Preferred: bonus if "fast"
                "-deprecated",   # Excluded: fail if "deprecated"
            ],
        },
    ],
)
def my_tool(weather: mesh.McpMeshTool = None): ...
```

## Matching Algorithm

1. **Filter**: Remove candidates with excluded tags (`-`)
2. **Require**: Keep only candidates with required tags (no prefix)
3. **Score**: Add points for preferred tags (`+`)
4. **Select**: Choose highest-scoring candidate

### Example

Available providers:

- Provider A: `["weather", "api", "accurate"]`
- Provider B: `["weather", "api", "fast", "deprecated"]`
- Provider C: `["weather", "api", "fast", "accurate"]`

Filter: `["api", "+accurate", "+fast", "-deprecated"]`

Result:

1. Provider B eliminated (has `-deprecated`)
2. Remaining: A and C (both have required `api`)
3. Scores: A=1 (accurate), C=2 (accurate+fast)
4. Winner: Provider C

## Tag Naming Conventions

| Category    | Examples                       |
| ----------- | ------------------------------ |
| Type        | `api`, `service`, `provider`   |
| Quality     | `fast`, `accurate`, `reliable` |
| Status      | `beta`, `stable`, `deprecated` |
| Provider    | `openai`, `claude`, `local`    |
| Environment | `production`, `staging`, `dev` |

## Priority Scoring with Preferences

Stack multiple `+` tags to create priority ordering. The provider matching the most preferred tags wins.

```python
# Prefer Claude > GPT > any other LLM
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+anthropic", "+gpt"]},
)
def my_llm_tool(): ...
```

| Provider | Its Tags | Matches | Score |
|----------|----------|---------|-------|
| Claude | `["llm", "claude", "anthropic"]` | +claude, +anthropic | **+2** |
| GPT | `["llm", "gpt", "openai"]` | +gpt | **+1** |
| Llama | `["llm", "llama"]` | (none) | **+0** |

Result: Claude (+2) > GPT (+1) > Llama (+0)

This works for any capability selection (dependencies, providers, tool filters).

## Tool Filtering in @mesh.llm

Filter which tools an LLM agent can access:

```python
@mesh.llm(
    filter=[
        {"tags": ["executor", "tools"]},      # Tools with these tags
        {"capability": "calculator"},          # Or this specific capability
    ],
    filter_mode="all",  # Include all matching
)
def smart_assistant(): ...
```

## See Also

- `meshctl man capabilities` - Capabilities system
- `meshctl man llm` - LLM integration
- `meshctl man dependency-injection` - How DI works

---

# TESTING

# Testing MCP Agents

> How to test MCP Mesh agents using meshctl and curl

## Quick Way: meshctl call

```bash
meshctl call hello_mesh_simple                    # Call tool by name (recommended)
meshctl call add '{"a": 1, "b": 2}'               # With arguments
meshctl list --tools                              # List all available tools
```

See `meshctl man cli` for more CLI commands.

## Protocol Details: curl

MCP agents expose a JSON-RPC 2.0 API over HTTP with Server-Sent Events (SSE) responses. This section shows the correct curl syntax - useful for understanding the underlying protocol.

## Key Points

- **Endpoint**: Always POST to `/mcp` (not REST-style paths like `/tools/list`)
- **Method**: Always `POST`
- **Headers**: Must include both `Content-Type` AND `Accept` headers
- **Body**: JSON-RPC 2.0 format with `jsonrpc`, `id`, `method`, `params`
- **Response**: Server-Sent Events format, requires parsing

## List Available Tools

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

## Call a Tool (No Arguments)

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_time",
      "arguments": {}
    }
  }'
```

## Call a Tool (With Arguments)

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {"title": "Test Report", "format": "markdown"}
    }
  }'
```

## Available MCP Methods

| Method           | Description                  |
| ---------------- | ---------------------------- |
| `tools/list`     | List all available tools     |
| `tools/call`     | Invoke a tool with arguments |
| `prompts/list`   | List available prompts       |
| `resources/list` | List available resources     |
| `resources/read` | Read a resource              |

## Response Format

MCP responses use Server-Sent Events (SSE) format:

```
data: {"jsonrpc":"2.0","id":1,"result":{"tools":[...]}}
```

To parse the response, you can pipe through:

```bash
| grep "^data:" | sed 's/^data: //' | jq .
```

## Common Errors

### Missing Accept Header

```
Error: Response not in expected format
Fix: Add -H "Accept: application/json, text/event-stream"
```

### Wrong Endpoint

```
Error: 404 Not Found
Fix: Use /mcp endpoint, not /tools/list or similar
```

### Invalid JSON-RPC Format

```
Error: Invalid request
Fix: Ensure body has jsonrpc, id, method, and params fields
```

## Testing in Docker Compose

Calls route through the registry proxy by default:

```bash
meshctl call greet
meshctl call add '{"a": 1, "b": 2}'

# Bypass proxy (requires mapped ports)
meshctl call greet --use-proxy=false --agent-url http://localhost:9001
```

## Testing in Kubernetes

For Kubernetes with ingress configured, use ingress mode:

```bash
# With DNS configured for the ingress domain
meshctl call greet --ingress-domain mcp-mesh.local

# Without DNS (direct IP or port-forwarded)
meshctl call greet --ingress-domain mcp-mesh.local --ingress-url http://localhost:9080
```

## Testing with meshctl

```bash
# Find agent ports
meshctl list

# Check agent status
meshctl status --verbose
```

## See Also

- `meshctl man cli` - CLI commands for development
- `meshctl man decorators` - How to create tools
- `meshctl man capabilities` - Understanding capabilities

---

