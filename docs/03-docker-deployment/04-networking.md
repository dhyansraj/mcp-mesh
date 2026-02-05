# Networking in Docker Compose

> How agents discover and communicate with each other in Docker

## Overview

MCP Mesh agents communicate through the registry. In Docker Compose, all services on the same network can reach each other by service name. No special networking configuration is needed.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │ Registry │◄───│ Agent A  │    │ Agent B  │          │
│  │ :8000    │    │ :8080    │◄──►│ :8081    │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       ▲                               │                 │
│       └───────────────────────────────┘                 │
│                                                          │
│  Agents register with registry, discover each other     │
│  automatically. No depends_on needed between agents.    │
└─────────────────────────────────────────────────────────┘
```

## Simple Setup

=== "Python"

    ```yaml
    # docker-compose.yml
    services:
      registry:
        image: mcpmesh/registry:0.9
        ports:
          - "8000:8000"

      my-agent:
        image: mcpmesh/python-runtime:0.9
        volumes:
          - ./my-agent:/app/agent:ro
        command: ["python", "/app/agent/main.py"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

      another-agent:
        image: mcpmesh/python-runtime:0.9
        volumes:
          - ./another-agent:/app/agent:ro
        command: ["python", "/app/agent/main.py"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

    networks:
      default:
        name: mcp-mesh
    ```

=== "TypeScript"

    ```yaml
    # docker-compose.yml
    services:
      registry:
        image: mcpmesh/registry:0.9
        ports:
          - "8000:8000"

      my-agent:
        image: mcpmesh/typescript-runtime:0.9
        volumes:
          - ./my-agent:/app/agent:ro
        command: ["npx", "tsx", "/app/agent/src/index.ts"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

      another-agent:
        image: mcpmesh/typescript-runtime:0.9
        volumes:
          - ./another-agent:/app/agent:ro
        command: ["npx", "tsx", "/app/agent/src/index.ts"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

    networks:
      default:
        name: mcp-mesh
    ```

That's it! Docker Compose creates a default network, and agents find each other through the registry.

## Key Points

1. **No `depends_on` between agents** - Agents are resilient and auto-wire when dependencies become available
2. **Use service names** - `http://registry:8000` works because Docker DNS resolves service names
3. **Single network is fine** - All services on the default network can communicate

## Environment Variables

| Variable                | Description           | Example                |
| ----------------------- | --------------------- | ---------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL          | `http://registry:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent port (optional) | `8080`                 |
| `MCP_MESH_LOG_LEVEL`    | Log level (optional)  | `DEBUG`                |

## Troubleshooting

### Agent can't reach registry

```bash
# Check if registry is running
docker compose ps

# Check registry logs
docker compose logs registry

# Test connectivity from agent container
docker compose exec my-agent curl http://registry:8000/health
```

### Agents not discovering each other

```bash
# Check if agents are registered
curl http://localhost:8000/agents | jq '.agents[].name'

# Or use meshctl
meshctl list
```

## Next Steps

- [Troubleshooting](./troubleshooting.md) - Common Docker deployment issues
