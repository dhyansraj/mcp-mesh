# Environment Variables Reference

> Configure MCP Mesh agents and services with environment variables

## Overview

MCP Mesh can be configured using environment variables, allowing you to customize behavior without changing code. Environment variables override `@mesh.agent` decorator parameters and provide flexibility for different deployment environments.

## Essential Environment Variables

### Logging and Debug

```bash
# Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export MCP_MESH_LOG_LEVEL=DEBUG

# Enable debug mode (forces DEBUG level)
export MCP_MESH_DEBUG_MODE=true
```

### Registry Configuration

```bash
# Complete registry URL
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Or set host and port separately
export MCP_MESH_REGISTRY_HOST=localhost
export MCP_MESH_REGISTRY_PORT=8000
```

### Agent Configuration

```bash
# Override agent name
export MCP_MESH_AGENT_NAME=my-custom-agent

# Set agent namespace
export MCP_MESH_NAMESPACE=development

# Enable/disable auto-run
export MCP_MESH_AUTO_RUN=true

# Auto-run heartbeat interval (seconds)
export MCP_MESH_AUTO_RUN_INTERVAL=30
```

### HTTP Server Settings

```bash
# Server binding address (what interface to bind to)
export HOST=0.0.0.0

# Agent HTTP port
export MCP_MESH_HTTP_PORT=8080

# Enable/disable HTTP transport
export MCP_MESH_HTTP_ENABLED=true

# External hostname announced to registry
export MCP_MESH_HTTP_HOST=my-agent
```

### Health and Monitoring

```bash
# Health check interval (seconds)
export MCP_MESH_HEALTH_INTERVAL=30

# Enable global mesh functionality
export MCP_MESH_ENABLED=true
```

## Registry Server Configuration

> These variables configure the **Go registry server** (`mcp-mesh-registry`)

### Core Server Settings

```bash
# Server binding host
export HOST=localhost

# Server port
export PORT=8000

# Database connection URL
export DATABASE_URL=mcp_mesh_registry.db

# Registry service name
export REGISTRY_NAME=mcp-mesh-registry
```

### Fast Heartbeat & Health Monitoring

```bash
# Agent heartbeat timeout - when to mark agents as unhealthy (seconds)
# Optimized for 5-second HEAD heartbeats: 4 missed beats = 20s
export DEFAULT_TIMEOUT_THRESHOLD=20

# Health monitor scan interval - how often to check for unhealthy agents (seconds)
export HEALTH_CHECK_INTERVAL=10

# Agent eviction threshold - when to remove stale agents (seconds)
export DEFAULT_EVICTION_THRESHOLD=60
```

### Cache and Performance

```bash
# Response cache TTL (seconds)
export CACHE_TTL=30

# Enable response caching
export ENABLE_RESPONSE_CACHE=true
```

### Logging and Debug

```bash
# Registry log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export MCP_MESH_LOG_LEVEL=INFO

# Enable debug mode (true/false)
export MCP_MESH_DEBUG_MODE=false
```

### CORS Configuration

```bash
# Enable CORS support
export ENABLE_CORS=true

# Allowed origins (comma-separated)
export ALLOWED_ORIGINS="*"

# Allowed HTTP methods
export ALLOWED_METHODS="GET,POST,PUT,DELETE,OPTIONS"

# Allowed headers
export ALLOWED_HEADERS="*"
```

### Feature Flags

```bash
# Enable metrics collection
export ENABLE_METRICS=true

# Enable Prometheus metrics
export ENABLE_PROMETHEUS=true

# Enable event system
export ENABLE_EVENTS=true
```

## Configuration Patterns

### Registry Server Configurations

#### Development Registry

```bash
# .env.registry.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
HOST=localhost
PORT=8000
DEFAULT_TIMEOUT_THRESHOLD=10  # Fast detection for development
HEALTH_CHECK_INTERVAL=5       # Quick scans for development
ENABLE_RESPONSE_CACHE=false   # Disable cache for testing
```

#### Production Registry

```bash
# .env.registry.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
HOST=0.0.0.0
PORT=8000
DEFAULT_TIMEOUT_THRESHOLD=20  # Balanced for production
HEALTH_CHECK_INTERVAL=10      # Regular monitoring
ENABLE_RESPONSE_CACHE=true
CACHE_TTL=30
DATABASE_URL=postgresql://user:pass@db:5432/mcp_mesh
```

#### High-Performance Registry

```bash
# .env.registry.high-perf
MCP_MESH_LOG_LEVEL=WARNING
DEFAULT_TIMEOUT_THRESHOLD=5   # Ultra-fast detection
HEALTH_CHECK_INTERVAL=2       # Very frequent monitoring
CACHE_TTL=60                  # Longer cache for performance
ENABLE_RESPONSE_CACHE=true
```

### Agent Development Environment

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_AUTO_RUN_INTERVAL=10
MCP_MESH_HEALTH_INTERVAL=15
```

### Production Environment

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=http://registry.company.com:8000
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
HOST=0.0.0.0
MCP_MESH_HTTP_HOST=api-service.company.com
```

### Testing Environment

```bash
# .env.testing
MCP_MESH_LOG_LEVEL=WARNING
MCP_MESH_DEBUG_MODE=false
MCP_MESH_AUTO_RUN=false
MCP_MESH_REGISTRY_URL=http://test-registry:8000
MCP_MESH_NAMESPACE=testing
```

## Using Environment Variables

### With Registry Server

```bash
# Start registry with environment file
mcp-mesh-registry --host 0.0.0.0 --port 8000

# Or with environment variables
DEFAULT_TIMEOUT_THRESHOLD=10 HEALTH_CHECK_INTERVAL=5 mcp-mesh-registry

# Load environment file manually
source .env.registry.development
mcp-mesh-registry

# Check registry configuration
mcp-mesh-registry --help
```

### With meshctl

```bash
# Load environment file
meshctl start my_agent.py --env-file .env.development

# Pass individual variables
meshctl start my_agent.py --env MCP_MESH_LOG_LEVEL=DEBUG --env MCP_MESH_DEBUG_MODE=true

# Use system environment
export MCP_MESH_LOG_LEVEL=DEBUG
meshctl start my_agent.py
```

### With Python

```bash
# Load environment file manually
source .env.development
python my_agent.py

# Or use python-dotenv in your agent
pip install python-dotenv
```

```python
import os
from dotenv import load_dotenv

# Load environment file
load_dotenv('.env.development')

# Your agent code here
```

### Override Agent Configuration

Environment variables override `@mesh.agent` decorator parameters:

```python
@mesh.agent(
    name="default-service",
    http_port=8080,
    auto_run=True,
    namespace="default"
)
class MyAgent:
    pass
```

```bash
# Override decorator settings
export MCP_MESH_AGENT_NAME=overridden-service
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_AUTO_RUN=false
export MCP_MESH_NAMESPACE=custom

# Runs with overridden values
python my_agent.py
```

## Advanced Configuration

### Kubernetes Environment

```bash
# Service discovery variables (auto-detected in K8s)
export SERVICE_NAME=my-service
export NAMESPACE=production
export POD_NAME=my-service-abc123
export POD_IP=10.244.1.5
export NODE_NAME=worker-node-1
```

### Docker Compose Environment

```yaml
# docker-compose.yml
services:
  my-agent:
    environment:
      - HOST=0.0.0.0 # Bind to all interfaces
      - MCP_MESH_HTTP_HOST=my-agent # Service name for inter-container communication
      - MCP_MESH_HTTP_PORT=8080
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_LOG_LEVEL=INFO
      - MCP_MESH_NAMESPACE=docker
```

### Performance Tuning

```bash
# Python runtime optimization
export PYTHONUNBUFFERED=1
export PYTHONPATH=/app/lib:/app/agents

# Uvicorn server settings (for FastMCP)
export UVICORN_WORKERS=1
export UVICORN_LOOP=auto
export UVICORN_LIFESPAN=on
```

### Fast Heartbeat Optimization

> **New in v0.2+**: Ultra-fast topology change detection

```bash
# Ultra-aggressive (sub-5 second detection)
export DEFAULT_TIMEOUT_THRESHOLD=5   # Mark unhealthy after 5s
export HEALTH_CHECK_INTERVAL=2       # Scan every 2 seconds

# Balanced (default - sub-20 second detection)  
export DEFAULT_TIMEOUT_THRESHOLD=20  # Mark unhealthy after 20s (4 missed 5s heartbeats)
export HEALTH_CHECK_INTERVAL=10      # Scan every 10 seconds

# Conservative (legacy behavior)
export DEFAULT_TIMEOUT_THRESHOLD=60  # Mark unhealthy after 60s
export HEALTH_CHECK_INTERVAL=30      # Scan every 30 seconds

# Production recommended
export DEFAULT_TIMEOUT_THRESHOLD=20
export HEALTH_CHECK_INTERVAL=10
```

**How it works:**
- Agents send lightweight HEAD requests every ~5 seconds
- Registry responds with topology change status (200/202/410)
- Background monitor detects unhealthy agents and creates events
- Other agents get notified via 202 responses on their HEAD checks

### Dynamic Updates

```bash
# Enable dynamic capability updates
export MCP_MESH_DYNAMIC_UPDATES=true

# Update strategy (immediate, graceful)
export MCP_MESH_UPDATE_STRATEGY=graceful

# Grace period for updates (seconds)
export MCP_MESH_UPDATE_GRACE_PERIOD=30
```

## Real-World Examples

### Multi-Service Development

```bash
# Terminal 1: Start registry with fast heartbeats
export MCP_MESH_LOG_LEVEL=DEBUG
export DEFAULT_TIMEOUT_THRESHOLD=10
export HEALTH_CHECK_INTERVAL=5
mcp-mesh-registry --host localhost --port 8000

# Terminal 2: Start auth service
export MCP_MESH_AGENT_NAME=auth-service
export MCP_MESH_HTTP_PORT=8081
export MCP_MESH_NAMESPACE=dev
export MCP_MESH_LOG_LEVEL=DEBUG
python services/auth.py

# Terminal 3: Start API service
export MCP_MESH_AGENT_NAME=api-service
export MCP_MESH_HTTP_PORT=8082
export MCP_MESH_NAMESPACE=dev
export MCP_MESH_LOG_LEVEL=DEBUG
python services/api.py
```

### Registry High Availability

```bash
# Primary registry (port 8000)
export HOST=0.0.0.0
export PORT=8000
export DATABASE_URL=postgresql://user:pass@primary-db:5432/mcp_mesh
export DEFAULT_TIMEOUT_THRESHOLD=20
export HEALTH_CHECK_INTERVAL=10
mcp-mesh-registry &

# Backup registry (port 8001) - read-only mode for failover
export HOST=0.0.0.0
export PORT=8001  
export DATABASE_URL=postgresql://user:pass@replica-db:5432/mcp_mesh
export DEFAULT_TIMEOUT_THRESHOLD=30
export HEALTH_CHECK_INTERVAL=15
mcp-mesh-registry &
```

### Remote Registry Connection

```bash
# Connect to shared development registry
export MCP_MESH_REGISTRY_URL=http://dev-registry.team.local:8000
export MCP_MESH_NAMESPACE=shared-dev
export MCP_MESH_AGENT_NAME=my-feature-branch

python my_agent.py
```

### CI/CD Pipeline

```bash
# Test environment variables
export MCP_MESH_AUTO_RUN=false          # Don't auto-start in tests
export MCP_MESH_LOG_LEVEL=ERROR         # Minimal logging
export MCP_MESH_REGISTRY_URL=http://test-registry:8000
export MCP_MESH_NAMESPACE=ci-${BUILD_ID}

# Run tests
python -m pytest tests/
```

### Load Testing Setup

```bash
# Start multiple instances with unique names
for i in {1..5}; do
  export MCP_MESH_AGENT_NAME=load-test-agent-$i
  export MCP_MESH_HTTP_PORT=$((8080 + i))
  python my_agent.py &
done

# Monitor all instances
meshctl list --filter load-test
```

## Environment Variable Hierarchy

Environment variables are applied in this order (last wins):

1. **System environment variables**
2. **Environment files** (`.env`)
3. **meshctl `--env` flags**
4. **`@mesh.agent` decorator parameters**

```bash
# Example: Final port will be 9999
export MCP_MESH_HTTP_PORT=8080              # System (1)
# .env file has: MCP_MESH_HTTP_PORT=8081    # File (2)
meshctl start my_agent.py --env MCP_MESH_HTTP_PORT=9999  # Flag (3)
```

## Debugging Environment Issues

### Check Current Environment

```bash
# Show all MCP Mesh environment variables
env | grep MCP_MESH

# Test specific variable
echo $MCP_MESH_LOG_LEVEL

# Verify environment file loading
meshctl start my_agent.py --env-file .env.development --debug
```

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using a port
lsof -i :8080

# Use different port
export MCP_MESH_HTTP_PORT=8081
```

#### 2. Registry Connection Failed

```bash
# Test registry connectivity
curl -s http://localhost:8000/health

# Use different registry
export MCP_MESH_REGISTRY_URL=http://backup-registry:8000
```

#### 3. Agent Name Conflicts

```bash
# Use unique agent name
export MCP_MESH_AGENT_NAME=my-unique-agent-$(date +%s)

# Check existing agents
meshctl list
```

#### 4. Environment File Not Loaded

```bash
# Verify file exists and is readable
cat .env.development

# Use absolute path
meshctl start my_agent.py --env-file /full/path/to/.env.development
```

## Environment Templates

### Development Template

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

### Production Template

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=https://registry.company.com
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
MCP_MESH_UPDATE_STRATEGY=graceful
MCP_MESH_UPDATE_GRACE_PERIOD=60
HOST=0.0.0.0
```

### Docker Template

```bash
# .env.docker
HOST=0.0.0.0
MCP_MESH_HTTP_HOST=my-service
MCP_MESH_REGISTRY_URL=http://registry:8000
MCP_MESH_NAMESPACE=docker
MCP_MESH_LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
```

## Security Considerations

### Sensitive Information

```bash
# ❌ Don't put secrets in environment files committed to git
MCP_MESH_API_KEY=secret123

# ✅ Use secure secret management
export MCP_MESH_API_KEY=$(kubectl get secret mesh-api-key -o jsonpath='{.data.key}' | base64 -d)

# ✅ Or use external secret providers
export MCP_MESH_REGISTRY_URL=$(vault kv get -field=url secret/mesh/registry)
```

### Network Security

```bash
# Use secure URLs in production
export MCP_MESH_REGISTRY_URL=https://registry.company.com  # ✅ HTTPS

# Bind to specific interfaces when needed
export HOST=127.0.0.1  # ✅ Localhost only
export HOST=0.0.0.0    # ⚠️ All interfaces (use carefully)
```

## Next Steps

Now that you understand environment configuration:

1. **[Advanced Patterns](./09-advanced-patterns.md)** - Complex multi-service architectures
2. **[Local Development](../02-local-development.md)** - Professional development workflows
3. **[Production Deployment](../03-docker-deployment.md)** - Container orchestration

---

## Summary

### Agent Configuration (Python)
Focus on `MCP_MESH_*` variables for agent behavior, heartbeat intervals, and service discovery.

### Registry Configuration (Go)
Focus on `DEFAULT_TIMEOUT_THRESHOLD` and `HEALTH_CHECK_INTERVAL` for fast topology detection.

---

💡 **Pro Tip**: Use environment files for different deployment stages - keeps configuration organized and secure.

🔧 **Development Tip**: Set `MCP_MESH_DEBUG_MODE=true` during development for detailed logging and faster feedback.

🚀 **Production Tip**: Use `DEFAULT_TIMEOUT_THRESHOLD=20` and `HEALTH_CHECK_INTERVAL=10` for optimal fast heartbeat performance.

⚡ **Performance Tip**: For ultra-fast systems, try `DEFAULT_TIMEOUT_THRESHOLD=5` and `HEALTH_CHECK_INTERVAL=2` for sub-5 second topology detection.

🛡️ **Registry Tip**: Use `DATABASE_URL` with PostgreSQL in production for better performance and reliability.
