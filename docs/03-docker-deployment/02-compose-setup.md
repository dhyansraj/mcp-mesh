# Docker Compose Setup

> Orchestrate multi-agent MCP Mesh systems with Docker Compose for development and testing

## Overview

Docker Compose simplifies running multi-container MCP Mesh deployments by defining your entire agent network in a single YAML file. This guide covers creating Compose configurations, managing service dependencies, handling networking, and implementing best practices for local development and testing.

With Docker Compose, you can spin up a complete MCP Mesh environment with a single command, making it perfect for development, testing, and demos.

## Key Concepts

- **Service Definitions**: Each agent and supporting service as a Compose service
- **Dependency Management**: Ensuring services start in the correct order
- **Network Configuration**: Containers communicating within a shared network
- **Volume Management**: Persistent data and configuration sharing
- **Environment Configuration**: Managing settings across services

## Step-by-Step Guide

### Step 1: Basic Compose Configuration

Create a `docker-compose.yml` file:

```yaml
version: "3.8"

services:
  # PostgreSQL database for registry
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: mcp_mesh
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  # MCP Mesh Registry
  registry:
    build:
      context: .
      dockerfile: docker/registry/Dockerfile
    ports:
      - "8000:8000"
    environment:
      MCP_MESH_DB_TYPE: postgresql
      MCP_MESH_DB_HOST: postgres
      MCP_MESH_DB_PORT: 5432
      MCP_MESH_DB_NAME: mcp_mesh
      MCP_MESH_DB_USER: postgres
      MCP_MESH_DB_PASSWORD: postgres
      MCP_MESH_LOG_LEVEL: INFO
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3

  # System Agent
  system-agent:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      MCP_MESH_LOG_LEVEL: INFO
    command: ["./bin/meshctl", "start", "examples/simple/system_agent.py"]
    depends_on:
      registry:
        condition: service_healthy
    restart: unless-stopped

  # Weather Agent (depends on System Agent)
  weather-agent:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      MCP_MESH_LOG_LEVEL: INFO
    command: ["./bin/meshctl", "start", "examples/simple/weather_agent.py"]
    depends_on:
      registry:
        condition: service_healthy
      system-agent:
        condition: service_started
    ports:
      - "8888:8888"
    restart: unless-stopped

volumes:
  postgres_data:

networks:
  default:
    name: mcp-mesh-net
```

### Step 2: Development Compose with Hot Reload

Create `docker-compose.dev.yml` for development:

```yaml
version: "3.8"

services:
  # Override registry for development
  registry:
    environment:
      MCP_MESH_LOG_LEVEL: DEBUG
    volumes:
      - ./data/registry:/data
      - ./logs/registry:/var/log/mcp-mesh

  # Development agent with code mounting
  dev-agent:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile.dev
    volumes:
      # Mount source code for hot reload
      - ./examples:/app/examples:ro
      - ./src:/app/src:ro
      - ./logs/agents:/var/log/mcp-mesh
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      MCP_MESH_LOG_LEVEL: DEBUG
      MCP_MESH_ENABLE_HOT_RELOAD: "true"
      PYTHONDONTWRITEBYTECODE: 1
      PYTHONUNBUFFERED: 1
    depends_on:
      registry:
        condition: service_healthy
    ports:
      - "8889:8888"
      - "5678:5678" # Debugger port
    command:
      [
        "python",
        "-m",
        "debugpy",
        "--listen",
        "0.0.0.0:5678",
        "--wait-for-client",
        "./bin/meshctl",
        "start",
        "examples/simple/my_agent.py",
      ]
```

Run with override:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Step 3: Environment-Specific Configuration

Create `.env` file for environment variables:

```bash
# .env
COMPOSE_PROJECT_NAME=mcp-mesh
POSTGRES_PASSWORD=secure_password
MCP_MESH_VERSION=0.2
REGISTRY_PORT=8000
LOG_LEVEL=INFO
```

Reference in compose file:

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}

  registry:
    image: mcp-mesh/registry:${MCP_MESH_VERSION:-0.3}
    ports:
      - "${REGISTRY_PORT:-8000}:8000"
    environment:
      MCP_MESH_LOG_LEVEL: ${LOG_LEVEL:-INFO}
```

### Step 4: Advanced Networking Configuration

Configure custom networks for isolation:

```yaml
version: "3.8"

services:
  registry:
    networks:
      - mesh-internal
      - mesh-public

  agent-internal:
    networks:
      - mesh-internal

  agent-public:
    networks:
      - mesh-internal
      - mesh-public
    ports:
      - "8888:8888"

networks:
  mesh-internal:
    driver: bridge
    internal: true # No external access
  mesh-public:
    driver: bridge
```

## Configuration Options

| Environment Variable     | Description          | Default                     | Example                                   |
| ------------------------ | -------------------- | --------------------------- | ----------------------------------------- |
| `COMPOSE_PROJECT_NAME`   | Project namespace    | directory name              | mcp-mesh                                  |
| `COMPOSE_FILE`           | Compose files to use | docker-compose.yml          | docker-compose.yml:docker-compose.dev.yml |
| `COMPOSE_PROFILES`       | Active profiles      | -                           | dev,debug                                 |
| `DOCKER_HOST`            | Docker daemon socket | unix:///var/run/docker.sock | tcp://remote:2375                         |
| `COMPOSE_PARALLEL_LIMIT` | Parallel operations  | 64                          | 10                                        |

## Examples

### Example 1: Production-Like Setup

```yaml
# docker-compose.prod.yml
version: "3.8"

x-common-variables: &common-variables
  MCP_MESH_LOG_LEVEL: INFO
  MCP_MESH_METRICS_ENABLED: "true"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: mcp_mesh
      POSTGRES_USER: mcp_user
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  registry:
    image: mcp-mesh/registry:${VERSION:-0.3}
    environment:
      <<: *common-variables
      MCP_MESH_DB_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    deploy:
      replicas: 2
      restart_policy:
        condition: any
        delay: 5s
        max_attempts: 3

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - registry

secrets:
  db_password:
    file: ./secrets/db_password.txt

volumes:
  postgres_data:
    driver: local
```

### Example 2: Testing Environment

```yaml
# docker-compose.test.yml
version: "3.8"

services:
  # Test database (ephemeral)
  test-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: test_mesh
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    tmpfs:
      - /var/lib/postgresql/data

  # Test agents
  test-agent-1:
    build:
      context: .
      dockerfile: docker/agent/Dockerfile
      args:
        RUN_TESTS: "true"
    environment:
      MCP_MESH_REGISTRY_URL: http://test-registry:8000
      TEST_MODE: "true"
    depends_on:
      - test-registry
    command: ["pytest", "-v", "/app/tests/"]
    entrypoint: ["./bin/meshctl", "start", "examples/simple/test_agent.py"]

  # Integration test runner
  test-runner:
    build:
      context: .
      dockerfile: docker/test/Dockerfile
    volumes:
      - ./tests:/tests
      - ./test-results:/results
    depends_on:
      - test-agent-1
      - test-agent-2
    command:
      ["pytest", "-v", "--junit-xml=/results/junit.xml", "/tests/integration/"]
```

## Best Practices

1. **Use Health Checks**: Ensure services are ready before dependents start
2. **Named Volumes**: Use named volumes for data persistence
3. **Resource Limits**: Set memory and CPU limits for stability
4. **Secret Management**: Use Docker secrets or external files
5. **Profile Organization**: Separate concerns with multiple compose files

## Common Pitfalls

### Pitfall 1: Service Start Order Issues

**Problem**: Agents fail because registry isn't ready

**Solution**: Use proper health checks and depends_on:

```yaml
depends_on:
  registry:
    condition: service_healthy # Wait for health check
  # not just:
  # - registry  # Only waits for container start
```

### Pitfall 2: Network Isolation Problems

**Problem**: Containers can't communicate

**Solution**: Ensure services are on the same network:

```yaml
services:
  agent1:
    networks:
      - mesh-net
  agent2:
    networks:
      - mesh-net # Same network

networks:
  mesh-net:
    driver: bridge
```

## Testing

### Unit Test Example

```bash
# test_compose_config.sh
#!/bin/bash

# Validate compose file
docker-compose config --quiet || exit 1

# Test service dependencies
docker-compose config | grep -q "depends_on" || exit 1

# Check all images build
docker-compose build --parallel || exit 1

# Verify no port conflicts
docker-compose ps --services | while read service; do
  docker-compose port $service 8080 2>/dev/null && echo "Port conflict on $service"
done
```

### Integration Test Example

```python
# tests/test_compose_integration.py
import subprocess
import time
import requests

def test_compose_stack():
    """Test full stack starts correctly"""
    # Start stack
    subprocess.run(["docker-compose", "up", "-d"], check=True)

    try:
        # Wait for services
        time.sleep(30)

        # Check registry
        response = requests.get("http://localhost:8000/health")
        assert response.status_code == 200

        # Check agents registered
        agents = requests.get("http://localhost:8000/agents").json()
        assert len(agents) >= 2

    finally:
        # Cleanup
        subprocess.run(["docker-compose", "down", "-v"])
```

## Monitoring and Debugging

### Compose Commands for Debugging

```bash
# View service logs
docker-compose logs -f registry

# Check service status
docker-compose ps

# Execute commands in running container
docker-compose exec registry sh

# View resource usage
docker stats $(docker-compose ps -q)

# Inspect network
docker network inspect mcp-mesh-net
```

### Debugging Service Issues

```bash
# Check why service won't start
docker-compose up registry  # Run in foreground

# View detailed events
docker-compose events --json

# Force recreate services
docker-compose up -d --force-recreate --no-deps registry
```

## 🔧 Troubleshooting

### Issue 1: "Cannot create container for service"

**Symptoms**: Container name conflicts

**Cause**: Old containers still exist

**Solution**:

```bash
# Remove old containers
docker-compose down

# Or with cleanup
docker-compose down -v --remove-orphans
```

### Issue 2: Environment Variables Not Working

**Symptoms**: Services using default values

**Cause**: Variable expansion issues

**Solution**:

```bash
# Debug variable expansion
docker-compose config

# Ensure .env file is in same directory
ls -la .env

# Export variables explicitly
export MCP_MESH_LOG_LEVEL=DEBUG
docker-compose up
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Compose Version**: v3.8 features require Docker 19.03+
- **Swarm Mode**: Some features only work in Swarm mode
- **Resource Limits**: Not enforced on all platforms
- **GPU Support**: Limited in Compose, use docker run

## 📝 TODO

- [ ] Add Docker Swarm configuration examples
- [ ] Create compose file generator tool
- [ ] Add monitoring stack (Prometheus/Grafana)
- [ ] Document compose secrets rotation
- [ ] Add blue-green deployment example

## Summary

You can now orchestrate complex MCP Mesh deployments with Docker Compose:

Key takeaways:

- 🔑 Complete service definitions with health checks
- 🔑 Proper dependency management between services
- 🔑 Development and production configurations
- 🔑 Network isolation and security practices

## Next Steps

Let's explore running multiple agents in a coordinated deployment.

Continue to [Multi-Agent Deployment](./03-multi-agent.md) →

---

💡 **Tip**: Use `docker-compose config` to validate and view the final configuration after variable substitution

📚 **Reference**: [Docker Compose Documentation](https://docs.docker.com/compose/)

🧪 **Try It**: Create a compose file that scales the weather agent to 3 instances behind a load balancer
