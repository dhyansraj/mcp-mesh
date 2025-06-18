# Running Registry Locally

> Set up and manage the MCP Mesh registry with SQLite or PostgreSQL for local development

## Overview

The MCP Mesh registry is the central nervous system of your distributed agent network. It tracks available agents, manages their capabilities, and facilitates service discovery. For local development, you can run it with either SQLite (simple) or PostgreSQL (production-like).

This guide covers both database options, data persistence strategies, and how to inspect and manage your local registry during development.

## Key Concepts

- **Registry**: Go-based service that maintains agent metadata and health status
- **SQLite Mode**: Zero-configuration database perfect for development
- **PostgreSQL Mode**: Production-grade database for realistic testing
- **Data Persistence**: How to preserve agent registrations between restarts
- **Registry API**: REST endpoints for inspection and management

## Step-by-Step Guide

### Step 1: Understanding Registry Auto-Start

The registry starts automatically when you run any agent:

```bash
# Start registry manually
./bin/meshctl start-registry

# Or start an agent (which can auto-connect to existing registry)
./bin/meshctl start examples/simple/hello_world.py

# Registry runs on:
# ✅ Registry available at http://localhost:8000
```

### Step 2: Configure SQLite Mode (Default)

SQLite is perfect for local development - no setup required!

```bash
# MCP Mesh uses Go registry with automatic database setup
# No manual database configuration needed for local development

# Start registry
./bin/meshctl start-registry

# Start agents (separate terminals)
./bin/meshctl start examples/simple/system_agent.py
./bin/meshctl start examples/simple/hello_world.py
```

Check the database:

```bash
# Install SQLite CLI if needed
sudo apt-get install sqlite3  # Ubuntu/Debian
brew install sqlite3          # macOS

# Inspect the database
sqlite3 dev-registry.db
.tables
SELECT * FROM agents;
.quit
```

### Step 3: Configure PostgreSQL Mode

For production-like development:

```bash
# For production-like testing, use Docker Compose setup
cd examples/docker-examples
docker-compose up --build

# This provides:
# - Go registry with PostgreSQL
# - Multiple Python agents
# - Proper networking and service discovery

# For local K8s testing:
cd examples/k8s
kubectl apply -k base/
```

### Step 4: Inspect Registry State

The registry provides REST API endpoints for inspection:

```bash
# List all registered agents
curl http://localhost:8000/agents | jq

# Check registry health
curl http://localhost:8000/health | jq

# Use meshctl for better interface
./bin/meshctl list agents
./bin/meshctl get agent hello-world
./bin/meshctl dependencies
```

## Configuration Options

| Option                   | Description        | Default   | Example              |
| ------------------------ | ------------------ | --------- | -------------------- |
| `MCP_MESH_REGISTRY_HOST` | Registry hostname  | localhost | registry.example.com |
| `MCP_MESH_REGISTRY_PORT` | Registry HTTP port | 8000      | 9000                 |
| `MCP_MESH_LOG_LEVEL`     | Logging level      | INFO      | DEBUG, WARNING       |
| `MCP_MESH_DEBUG_MODE`    | Enable debug logs  | false     | true                 |
| `HOST`                   | Agent bind address | 0.0.0.0   | 127.0.0.1            |
| `MCP_MESH_HTTP_PORT`     | Agent HTTP port    | 0 (auto)  | 8080                 |

## Examples

### Example 1: Development Setup Script

Create `scripts/start-dev-env.sh`:

```bash
#!/bin/bash
# Start complete development environment

export MCP_MESH_LOG_LEVEL=DEBUG
export MCP_MESH_DEBUG_MODE=true

# Start registry first
echo "Starting registry..."
./bin/meshctl start-registry &
REGISTRY_PID=$!

# Wait for registry to be ready
echo "Waiting for registry..."
until curl -s http://localhost:8000/health > /dev/null; do
  sleep 1
done

# Start agents
echo "Starting system agent..."
./bin/meshctl start examples/simple/system_agent.py &
SYSTEM_PID=$!

echo "Starting hello world agent..."
./bin/meshctl start examples/simple/hello_world.py &
HELLO_PID=$!

echo "Development environment ready!"
echo "Registry: http://localhost:8000"
echo "Use './bin/meshctl list agents' to see registered agents"
echo "Registry PID: $REGISTRY_PID"
echo "System Agent PID: $SYSTEM_PID"
echo "Hello World PID: $HELLO_PID"

# Keep running until Ctrl+C
wait
```

### Example 2: PostgreSQL with Persistence

```yaml
# docker-compose.dev.yml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: mcp_mesh_dev
      POSTGRES_USER: developer
      POSTGRES_PASSWORD: devpass123
    ports:
      - "5432:5432"
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U developer"]
      interval: 10s
      timeout: 5s
      retries: 5

  registry:
    image: mcp-mesh/registry:latest
    environment:
      MCP_MESH_DB_TYPE: postgresql
      MCP_MESH_DB_HOST: postgres
      MCP_MESH_DB_NAME: mcp_mesh_dev
      MCP_MESH_DB_USER: developer
      MCP_MESH_DB_PASSWORD: devpass123
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
```

## Best Practices

1. **Use SQLite for Quick Development**: No setup, portable, perfect for prototyping
2. **Use PostgreSQL for Integration Testing**: Catches production issues early
3. **Version Control Database Schemas**: Track schema changes in migrations/
4. **Clean State for Tests**: Delete SQLite file or use test database
5. **Monitor Registry Logs**: Enable DEBUG logging during development

## Common Pitfalls

### Pitfall 1: Registry Port Conflicts

**Problem**: "address already in use" error when starting registry

**Solution**: Check what's using port 8080:

```bash
# Find process using port 8080
lsof -i :8080  # macOS/Linux
netstat -ano | findstr :8080  # Windows

# Use different port
export MCP_MESH_REGISTRY_PORT=9090
```

### Pitfall 2: Stale Agent Registrations

**Problem**: Registry shows agents that are no longer running

**Solution**: Registry auto-cleans stale entries after health check failures, or manually:

```bash
# For SQLite - start fresh
rm dev-registry.db

# For PostgreSQL - clean agents table
psql -h localhost -U postgres -d mcp_mesh -c "DELETE FROM agents WHERE last_seen < NOW() - INTERVAL '5 minutes';"
```

## Testing

### Unit Test Example

```python
# tests/test_registry_connection.py
import requests
import pytest

def test_registry_health():
    """Verify registry is accessible"""
    response = requests.get("http://localhost:8080/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_agent_registration():
    """Test agent appears in registry"""
    # Start your agent first
    response = requests.get("http://localhost:8080/api/v1/agents")
    agents = response.json()
    assert len(agents) > 0
    assert any(a["name"] == "SystemAgent" for a in agents)
```

### Integration Test Example

```python
# tests/test_registry_persistence.py
import subprocess
import time
import requests

def test_registry_persistence():
    """Verify data persists across registry restarts"""
    # Start agent
    proc = subprocess.Popen(["mcp-mesh-dev", "start", "examples/system_agent.py"])
    time.sleep(5)

    # Verify registration
    agents = requests.get("http://localhost:8080/api/v1/agents").json()
    assert len(agents) == 1

    # Stop agent but registry keeps running
    proc.terminate()
    time.sleep(2)

    # Agent should still be in registry (before health check)
    agents = requests.get("http://localhost:8080/api/v1/agents").json()
    assert len(agents) == 1
```

## Monitoring and Debugging

### Logs to Check

```bash
# Registry logs (auto-started)
tail -f ~/.mcp-mesh/logs/registry.log

# Check database queries (PostgreSQL)
docker logs mcp-postgres -f

# Enable SQL logging
export MCP_MESH_DB_LOG_SQL=true
```

### Metrics to Monitor

- **Registry Memory**: Should stay under 100MB for < 100 agents
- **Database Size**: SQLite file or PostgreSQL disk usage
- **Query Performance**: Registration should take < 100ms

## 🔧 Troubleshooting

### Issue 1: Registry Won't Start

**Symptoms**: "connection refused" when accessing registry

**Cause**: Port conflict or database connection issue

**Solution**:

```bash
# Check if port is available
nc -zv localhost 8000

# Check registry process
ps aux | grep meshctl

# Start registry manually for debugging
./bin/meshctl start-registry --verbose
```

### Issue 2: Database Connection Errors

**Symptoms**: "database connection failed" in logs

**Cause**: Wrong credentials or database not running

**Solution**:

```bash
# Test registry connection
curl http://localhost:8000/health

# Check registry logs
./bin/meshctl status --verbose

# Restart registry if needed
pkill -f meshctl
./bin/meshctl start-registry
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **SQLite Concurrency**: Limited to one writer at a time - fine for development
- **Auto-Start**: Only works with mcp-mesh-dev CLI, not direct Python execution
- **Data Migration**: No automatic migration between SQLite and PostgreSQL

## 📝 TODO

- [ ] Add support for MySQL/MariaDB backend
- [ ] Implement data export/import tools
- [ ] Add registry UI for visual inspection
- [ ] Support for registry clustering

## Summary

You can now run the MCP Mesh registry locally with your choice of database backend.

Key takeaways:

- 🔑 Registry auto-starts when you run agents via mcp-mesh-dev
- 🔑 SQLite is perfect for development, PostgreSQL for production-like testing
- 🔑 REST API provides full visibility into registry state
- 🔑 Data persistence options for different development scenarios

## Next Steps

With the registry running, let's explore debugging techniques for your agents.

Continue to [Debugging Agents](./03-debugging.md) →

---

💡 **Tip**: Use `watch -n 1 'curl -s localhost:8080/api/v1/agents | jq'` to monitor agent registrations in real-time

📚 **Reference**: [Registry API Documentation](../../reference/registry-api.md)

🧪 **Try It**: Start the registry with PostgreSQL and register multiple agents - watch them appear in the database
