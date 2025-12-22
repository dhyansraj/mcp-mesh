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
