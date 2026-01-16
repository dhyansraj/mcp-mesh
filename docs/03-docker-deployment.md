# Docker Deployment

> Run MCP Mesh agents in containers with pre-built images and generated compose files

## Overview

MCP Mesh provides pre-built Docker images and a scaffold tool to generate Docker Compose files automatically. No need to write Dockerfiles from scratch.

## Quick Start (30 seconds)

```bash
# Generate a new agent with Dockerfile and compose file
meshctl scaffold --name my-agent --compose

# Start everything (docker-compose.yml is in current directory)
docker-compose up
```

That's it! Your agent is running with the registry and observability stack.

## Pre-built Images

MCP Mesh publishes official images to Docker Hub:

| Image                        | Purpose                                      |
| ---------------------------- | -------------------------------------------- |
| `mcpmesh/registry:0.8`       | Go-based registry service                    |
| `mcpmesh/python-runtime:0.8` | Python agent runtime (includes mcp-mesh SDK) |

## Using Scaffold to Generate Compose Files

The `meshctl scaffold` command generates everything you need:

```bash
# Generate compose for existing agents directory
meshctl scaffold --compose -d ./agents

# Include observability stack (Grafana, Tempo, Redis)
meshctl scaffold --compose --observability -d ./agents

# Preview without creating files
meshctl scaffold --compose --dry-run -d ./agents
```

### Generated docker-compose.yml

```yaml
version: "3.8"

services:
  registry:
    image: mcpmesh/registry:0.8
    ports:
      - "8000:8000"
    environment:
      - HOST=0.0.0.0
      - PORT=8000
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  my-agent:
    image: mcpmesh/python-runtime:0.8
    ports:
      - "8080:8080"
    volumes:
      - ./my-agent:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080
    depends_on:
      registry:
        condition: service_healthy

networks:
  default:
    name: mcp-mesh
```

## Manual Setup (Without Scaffold)

If you prefer manual control, here's a minimal compose file:

```yaml
version: "3.8"

services:
  registry:
    image: mcpmesh/registry:0.8
    ports:
      - "8000:8000"

  my-agent:
    image: mcpmesh/python-runtime:0.8
    volumes:
      - ./agent.py:/app/agent.py:ro
    command: ["python", "/app/agent.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000

networks:
  default:
    name: mcp-mesh
```

## Building Custom Agent Images

The `meshctl scaffold` command automatically generates a `Dockerfile` for each agent. Use that for production builds.

If you didn't use scaffold, here's a sample Dockerfile:

```dockerfile
# Dockerfile
FROM mcpmesh/python-runtime:0.8

# Copy your agent code
COPY ./my-agent /app/agent

# Install additional dependencies if needed
RUN pip install -r /app/agent/requirements.txt

# Run the agent
CMD ["python", "/app/agent/main.py"]
```

Build and run:

```bash
docker build -t my-company/my-agent:1.0 .
docker run -e MCP_MESH_REGISTRY_URL=http://registry:8000 my-company/my-agent:1.0
```

## Multi-Agent Setup

Run multiple agents with a single compose file:

```yaml
version: "3.8"

services:
  registry:
    image: mcpmesh/registry:0.8
    ports:
      - "8000:8000"

  auth-agent:
    image: mcpmesh/python-runtime:0.8
    volumes:
      - ./agents/auth:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080

  data-agent:
    image: mcpmesh/python-runtime:0.8
    volumes:
      - ./agents/data:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080

  api-agent:
    image: mcpmesh/python-runtime:0.8
    volumes:
      - ./agents/api:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080

networks:
  default:
    name: mcp-mesh
```

## Adding Observability

Use `--observability` flag to include Grafana, Tempo, and Redis:

```bash
meshctl scaffold --compose --observability -d ./agents
```

Or add manually:

```yaml
services:
  # ... your agents ...

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  tempo:
    image: grafana/tempo:latest
    ports:
      - "3200:3200"
      - "4317:4317"

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
```

## Environment Variables

Key environment variables for containerized agents:

| Variable                | Description        | Default                 |
| ----------------------- | ------------------ | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry endpoint  | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port    | `8080`                  |
| `MCP_MESH_LOG_LEVEL`    | Logging level      | `INFO`                  |
| `REDIS_URL`             | Redis for sessions | (optional)              |
| `TEMPO_ENDPOINT`        | Tracing endpoint   | (optional)              |

## Best Practices

1. **Use pre-built images** - Don't build from source unless necessary
2. **Generate with scaffold** - Let `meshctl scaffold` handle the boilerplate
3. **Volume mount for development** - Fast iteration without rebuilding
4. **Build custom images for production** - Bake code into image
5. **Use health checks** - Ensure proper startup order

## Troubleshooting

### Agent can't connect to registry

```bash
# Check registry is healthy
docker-compose ps
docker-compose logs registry

# Verify network
docker network ls
docker network inspect mcp-mesh
```

### Agent exits immediately

```bash
# Check logs
docker-compose logs my-agent

# Run interactively
docker-compose run --rm my-agent /bin/bash
```

## Next Steps

- [Networking Details](./03-docker-deployment/04-networking.md) - Deep dive into container networking
- [Kubernetes Deployment](./06-helm-deployment.md) - Production deployment with Helm
