# Docker Deployment

> Run MCP Mesh agents in containers with pre-built images and generated compose files

## Overview

MCP Mesh provides pre-built Docker images and a scaffold tool to generate Docker Compose files automatically. No need to write Dockerfiles from scratch.

## Quick Start (30 seconds)

```bash
# Generate a new agent (includes a Dockerfile)
meshctl scaffold basic --name my-agent

# Generate docker-compose.yml for every agent in this directory
meshctl scaffold --compose --observability

# Start everything (docker-compose.yml is in current directory)
docker compose up
```

That's it! Your agent is running with the registry and observability stack.

## Pre-built Images

MCP Mesh publishes official images to Docker Hub:

| Image                            | Purpose                                          |
| -------------------------------- | ------------------------------------------------ |
| `mcpmesh/registry:3.7.1`           | Go-based registry service                        |
| `mcpmesh/python-runtime:3.7.1`     | Python agent runtime (includes mcp-mesh SDK)     |
| `mcpmesh/java-runtime:3.7.1`       | Java agent runtime (includes mcp-mesh SDK)       |
| `mcpmesh/typescript-runtime:3.7.1` | TypeScript agent runtime (includes @mcpmesh/sdk) |

## Using Scaffold to Generate Compose Files

The `meshctl scaffold` command generates everything you need:

```bash
# Generate ./agents/docker-compose.yml for the agents under ./agents
meshctl scaffold --compose -o ./agents

# Include observability stack (Grafana, Tempo, Redis)
meshctl scaffold --compose --observability -o ./agents

# Preview without creating files (prints the YAML to stdout)
meshctl scaffold --compose --dry-run -o ./agents
```

### Generated docker-compose.yml

A trimmed excerpt of what `meshctl scaffold --compose` writes for a directory named `my-project` holding one agent, `my-agent` on port 8080. Run it with `--dry-run` to print the full file for your own agents. The compose project, and so every container name, takes the directory name unless you pass `--project-name`.

The infrastructure services are the same for every language:

```yaml
services:
  # ===== INFRASTRUCTURE =====

  postgres:
    image: postgres:15-alpine
    container_name: my-project-postgres
    environment:
      POSTGRES_USER: mcpmesh
      POSTGRES_PASSWORD: mcpmesh
      POSTGRES_DB: mcpmesh
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mcpmesh"]
    networks:
      - my-project-network

  registry:
    image: mcpmesh/registry:3.7.1
    container_name: my-project-registry
    ports:
      - "8000:8000"
    environment:
      HOST: "0.0.0.0"
      PORT: "8000"
      DATABASE_URL: postgresql://mcpmesh:mcpmesh@postgres:5432/mcpmesh?sslmode=disable
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8000/health"]
    networks:
      - my-project-network

networks:
  my-project-network:
    name: my-project-network
    driver: bridge
```

Each agent runs on its language's runtime image with its directory mounted, and is health-checked on `/livez`:

=== "Python"

    ```yaml
      my-agent:
        image: mcpmesh/python-runtime:3.7.1
        container_name: my-project-my-agent
        ports:
          - "8080:8080"
        volumes:
          - ./my-agent:/app:ro
          - my-agent-packages:/packages
        working_dir: /app
        entrypoint: ["sh", "-c"]
        command: ["chown -R mcp-mesh:mcp-mesh /packages && su mcp-mesh -c 'if [ -f /app/requirements.txt ]; then pip install --target /packages -q -r /app/requirements.txt 2>/dev/null; fi && python main.py'"]
        environment:
          PYTHONPATH: /packages
          MCP_MESH_REGISTRY_URL: http://registry:8000
          MCP_MESH_HTTP_HOST: my-agent
          MCP_MESH_HTTP_PORT: "8080"
          MCP_MESH_AGENT_NAME: my-agent
        healthcheck:
          test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/livez').read()"]
          start_period: 30s
        networks:
          - my-project-network
    ```

=== "Java"

    ```yaml
      my-agent:
        image: mcpmesh/java-runtime:3.7.1
        container_name: my-project-my-agent
        ports:
          - "8080:8080"
        volumes:
          - ./my-agent:/app
          - my-agent-maven-repo:/root/.m2
        working_dir: /app
        entrypoint: ["sh", "-c"]
        command: ["mvn spring-boot:run -DskipTests -q"]
        environment:
          MCP_MESH_REGISTRY_URL: http://registry:8000
          MCP_MESH_HTTP_HOST: my-agent
          MCP_MESH_HTTP_PORT: "8080"
          MCP_MESH_AGENT_NAME: my-agent
        healthcheck:
          test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/livez"]
          start_period: 60s
        networks:
          - my-project-network
    ```

=== "TypeScript"

    ```yaml
      my-agent:
        image: mcpmesh/typescript-runtime:3.7.1
        container_name: my-project-my-agent
        ports:
          - "8080:8080"
        volumes:
          - ./my-agent:/app
          - my-agent-node_modules:/app/node_modules
        working_dir: /app
        entrypoint: ["sh", "-c"]
        command: ["mkdir -p /home/mcp-mesh && chown -R mcp-mesh:mcp-mesh /home/mcp-mesh /app/node_modules && su mcp-mesh -c 'npm install --silent 2>/dev/null && npx tsx src/index.ts'"]
        environment:
          NODE_ENV: development
          MCP_MESH_REGISTRY_URL: http://registry:8000
          MCP_MESH_HTTP_HOST: my-agent
          MCP_MESH_HTTP_PORT: "8080"
          MCP_MESH_AGENT_NAME: my-agent
        healthcheck:
          test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/livez"]
          start_period: 45s
        networks:
          - my-project-network
    ```

The generated agent services also set the mesh debug-logging variables, and every agent mounts its own named volume, declared under a top-level `volumes:` key.

## Manual Setup (Without Scaffold)

If you prefer manual control, here's a minimal compose file:

=== "Python"

    ```yaml
    services:
      registry:
        image: mcpmesh/registry:3.7.1
        ports:
          - "8000:8000"

      my-agent:
        image: mcpmesh/python-runtime:3.7.1
        volumes:
          - ./agent.py:/app/agent.py:ro
        command: ["python", "/app/agent.py"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

    networks:
      default:
        name: mcp-mesh
    ```

=== "Java"

    ```yaml
    services:
      registry:
        image: mcpmesh/registry:3.7.1
        ports:
          - "8000:8000"

      my-agent:
        build: ./my-agent
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

    networks:
      default:
        name: mcp-mesh
    ```

=== "TypeScript"

    ```yaml
    services:
      registry:
        image: mcpmesh/registry:3.7.1
        ports:
          - "8000:8000"

      my-agent:
        image: mcpmesh/typescript-runtime:3.7.1
        volumes:
          - ./my-agent:/app/agent:ro
        command: ["npx", "tsx", "/app/agent/src/index.ts"]
        environment:
          - MCP_MESH_REGISTRY_URL=http://registry:8000

    networks:
      default:
        name: mcp-mesh
    ```

## Building Custom Agent Images

The `meshctl scaffold` command automatically generates a `Dockerfile` for each agent. Use that for production builds.

If you didn't use scaffold, here's a sample Dockerfile:

=== "Python"

    ```dockerfile
    FROM mcpmesh/python-runtime:3.7.1

    COPY ./my-agent /app/agent

    # Install additional dependencies if needed
    RUN pip install -r /app/agent/requirements.txt

    CMD ["python", "/app/agent/main.py"]
    ```

=== "Java"

    ```dockerfile
    FROM eclipse-temurin:17-jre-alpine

    WORKDIR /app
    COPY target/*.jar app.jar

    EXPOSE 8080
    CMD ["java", "-jar", "app.jar"]
    ```

=== "TypeScript"

    ```dockerfile
    FROM mcpmesh/typescript-runtime:3.7.1

    WORKDIR /app/agent
    COPY ./my-agent/package*.json ./
    RUN npm install

    COPY ./my-agent .

    CMD ["npx", "tsx", "src/index.ts"]
    ```

Build and run:

```bash
docker build -t my-company/my-agent:1.0 .
docker run -e MCP_MESH_REGISTRY_URL=http://registry:8000 my-company/my-agent:1.0
```

## Multi-Agent Setup

Run multiple agents with a single compose file:

```yaml
services:
  registry:
    image: mcpmesh/registry:3.7.1
    ports:
      - "8000:8000"

  auth-agent:
    image: mcpmesh/python-runtime:3.7.1
    volumes:
      - ./agents/auth:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080

  data-agent:
    image: mcpmesh/python-runtime:3.7.1
    volumes:
      - ./agents/data:/app/agent:ro
    command: ["python", "/app/agent/main.py"]
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_HTTP_PORT=8080

  api-agent:
    image: mcpmesh/python-runtime:3.7.1
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
meshctl scaffold --compose --observability -o ./agents
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
docker compose ps
docker compose logs registry

# Verify network
docker network ls
docker network inspect mcp-mesh
```

### Agent exits immediately

```bash
# Check logs
docker compose logs my-agent

# Run interactively
docker compose run --rm my-agent /bin/bash
```

## Next Steps

- [Networking Details](./03-docker-deployment/04-networking.md) - Deep dive into container networking
- [Kubernetes Deployment](./04-kubernetes-basics.md) - Production deployment with Helm
