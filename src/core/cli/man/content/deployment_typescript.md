# Deployment Patterns (TypeScript)

> Local, Docker, and Kubernetes deployment for TypeScript agents

## Overview

MCP Mesh supports multiple deployment patterns for TypeScript agents. Use `meshctl scaffold --lang typescript` to generate deployment-ready files automatically.

## Official Docker Images

| Image                            | Description                                        |
| -------------------------------- | -------------------------------------------------- |
| `mcpmesh/registry:0.8`           | Registry service for agent discovery               |
| `mcpmesh/typescript-runtime:0.9` | TypeScript runtime with @mcpmesh/sdk pre-installed |

## Local Development

### Setup

```bash
# Create project
meshctl scaffold --name my-agent --agent-type tool --lang typescript
cd my-agent

# Install dependencies
npm install

# Verify setup
npx tsx src/index.ts --help
```

### Quick Start

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug

# Terminal 2: Start agent (uses npx tsx automatically)
meshctl start src/index.ts --debug

# Terminal 3: Monitor
watch 'meshctl list'
```

### Multiple Agents

```bash
# Start multiple TypeScript agents
meshctl start agent1/src/index.ts agent2/src/index.ts

# Or with specific ports
MCP_MESH_HTTP_PORT=9001 npx tsx agent1/src/index.ts &
MCP_MESH_HTTP_PORT=9002 npx tsx agent2/src/index.ts &
```

### Development Workflow

```bash
# Watch mode: auto-restart on file changes
meshctl start src/index.ts --watch --debug

# Or run in background
meshctl start src/index.ts --detach

# Stop when done
meshctl stop my-agent      # Stop specific agent
meshctl stop               # Stop all
```

## Docker Deployment

### Generated Dockerfile

`meshctl scaffold --lang typescript` generates a Dockerfile:

```dockerfile
# Dockerfile for my-agent MCP Mesh agent
FROM mcpmesh/typescript-runtime:0.9

WORKDIR /app

# Switch to root to copy files (base image runs as non-root mcp-mesh user)
USER root

# Copy package files and install app-specific dependencies only
COPY package*.json ./
RUN npm ci --omit=dev

# Copy agent source code and set permissions
COPY --chmod=755 . .
RUN chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user for security
USER mcp-mesh

# Expose the agent port (configured via --port flag)
EXPOSE 8080

# Run the agent (tsx for .ts files)
CMD ["npx", "tsx", "src/index.ts"]
```

**Security notes:**

- **USER root / USER mcp-mesh**: The base image runs as the non-root `mcp-mesh` user by default. We temporarily switch to root for file operations, then drop privileges back to `mcp-mesh` for runtime security.
- **COPY --chmod=755 / chown**: Ensures files have correct permissions and ownership for the `mcp-mesh` user to execute.
- **EXPOSE**: The port is configured via `--port` flag during scaffold (defaults to 8080).

### Generate Docker Compose

```bash
# Create multiple TypeScript agents
meshctl scaffold --name agent1 --port 8080 --lang typescript
meshctl scaffold --name agent2 --port 9001 --lang typescript

# Generate docker-compose.yml for all agents
meshctl scaffold --compose

# With observability stack (Redis, Tempo, Grafana)
meshctl scaffold --compose --observability
```

Generated `docker-compose.yml` includes:

- PostgreSQL database for registry
- Registry service (`mcpmesh/registry:0.8`)
- TypeScript agents with `mcpmesh/typescript-runtime:0.9`
- Health checks and dependency ordering
- Optional: Redis, Tempo, Grafana (with `--observability`)

### Running

```bash
docker compose up -d
docker compose logs -f
docker compose ps
```

## Kubernetes Deployment

### Helm Charts

For production Kubernetes deployment:

```bash
# Install core infrastructure
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.8 \
  -n mcp-mesh --create-namespace

# Deploy TypeScript agent
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.8 \
  -n mcp-mesh \
  -f my-agent/helm-values.yaml
```

### Generated helm-values.yaml

```yaml
# my-agent/helm-values.yaml (auto-generated for TypeScript)
image:
  # Override with your built agent image
  repository: your-registry/my-agent
  tag: latest

agent:
  name: my-agent
  # No script needed - TypeScript agents use Docker CMD from Dockerfile
  # The scaffolded Dockerfile includes: CMD ["npx", "tsx", "src/index.ts"]
  command: [] # Empty = use Docker image's CMD (recommended)

mesh:
  enabled: true

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi
```

**Note:** Unlike Python agents which may use `agent.script`, TypeScript agents rely on the Docker image's CMD. The runtime is baked into your image when you build from the scaffolded Dockerfile.

### Deployment Workflow

```bash
# 1. Scaffold TypeScript agent
meshctl scaffold --name my-agent --agent-type tool --lang typescript

# 2. Build and push Docker image
cd my-agent
docker buildx build --platform linux/amd64 -t your-registry/my-agent:v1.0.0 --push .

# 3. Deploy with Helm
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.8 \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/my-agent \
  --set image.tag=v1.0.0
```

## Port Strategy

| Environment            | Port Strategy                | Why                                   |
| ---------------------- | ---------------------------- | ------------------------------------- |
| Local / docker-compose | Unique ports (9001, 9002...) | All containers share host network     |
| Kubernetes             | All agents use 8080          | Each pod has its own IP, no conflicts |

## Best Practices

### Health Checks

TypeScript agents automatically expose health endpoints:

```typescript
// Automatic health check at /health
// Returns: { status: "healthy", agentId: "my-agent-abc123" }
```

### Graceful Shutdown

TypeScript SDK handles SIGINT/SIGTERM automatically:

```typescript
// No code needed - SDK installs handlers automatically
// Agents deregister cleanly on shutdown
```

### Logging

```bash
# Structured logging for production
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false

# Enable debug logging (either option works)
export MCP_MESH_LOG_LEVEL=DEBUG
# or
export MCP_MESH_DEBUG_MODE=true
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

## See Also

- `meshctl scaffold --help` - Generate TypeScript agents
- `meshctl man environment` - Configuration options
- `meshctl man health` - Health monitoring
- `meshctl man express` - Express API integration
