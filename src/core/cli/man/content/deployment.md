# Deployment Patterns

> Local, Docker, and Kubernetes deployment options

## Overview

MCP Mesh supports multiple deployment patterns from local development to production Kubernetes clusters. Python, TypeScript, and Java agents can be deployed using the same patterns. Use `meshctl scaffold` to generate deployment-ready files automatically.

## Official Docker Images

| Image                            | Description                                        |
| -------------------------------- | -------------------------------------------------- |
| `mcpmesh/registry:0.8`           | Registry service for agent discovery               |
| `mcpmesh/python-runtime:0.8`     | Python runtime with mcp-mesh SDK pre-installed     |
| `mcpmesh/typescript-runtime:0.8` | TypeScript runtime with @mcpmesh/sdk pre-installed |

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

`meshctl scaffold` automatically generates a Dockerfile:

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
EXPOSE 8080
CMD ["python", "main.py"]
```

### Generate Docker Compose (Recommended)

Use `--compose` to auto-generate docker-compose.yml for all agents in a directory:

```bash
# Create multiple agents
meshctl scaffold --name agent1 --port 8080
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
  --version 0.9.0-beta.11 \
  -n mcp-mesh --create-namespace

# Deploy agent using scaffold-generated helm-values.yaml
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.0-beta.11 \
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
  # http_port: 8080 (default - no need to specify, see "Port Strategy" section)

mesh:
  enabled: true
  registry_url: http://mcp-core-mcp-mesh-registry:8000

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
  --version 0.9.0-beta.11 \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/my-agent \
  --set image.tag=v1.0.0
```

### Disable Optional Components

```bash
# Core without observability
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.0-beta.11 \
  -n mcp-mesh --create-namespace \
  --set grafana.enabled=false \
  --set tempo.enabled=false

# Core without PostgreSQL (in-memory registry)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.0-beta.11 \
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
  http_port: 9001

# ✅ CORRECT - use defaults
agent:
  name: my-agent
  # http_port: 8080 is the default, no need to specify
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
