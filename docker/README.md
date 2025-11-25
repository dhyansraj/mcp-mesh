# MCP Mesh Docker Configuration

This directory contains Docker configurations for MCP Mesh components:

## Directory Structure

```
docker/
├── README.md              # This file
├── agent/
│   ├── Dockerfile.base    # Base Python image with mcp_mesh library
│   ├── Dockerfile.python  # Full-featured Python agent (extends base)
│   └── Dockerfile         # Simple test agent (mount your own script)
└── registry/
    └── Dockerfile         # Go-based registry service
```

## Available Images

### Registry (`docker/registry/Dockerfile`)

- **Base**: `golang:1.23-alpine` → `alpine:latest`
- **Purpose**: Go-based registry service with SQLite
- **Ports**: 8000 (HTTP API)
- **Features**: Multi-stage build, security hardened, health checks

### Base Agent (`docker/agent/Dockerfile.base`)

- **Base**: `python:3.11-slim`
- **Purpose**: Base image with mcp_mesh library installed
- **Features**: Full mcp_mesh runtime, dependency injection support
- **Usage**: Extended by specific agent implementations

### Python Agent (`docker/agent/Dockerfile.python`)

- **Base**: `mcp-mesh-base:latest`
- **Purpose**: Full-featured Python agents with mesh capabilities
- **Features**: Extends base image, includes sample agent code

### Test Agent (`docker/agent/Dockerfile`)

- **Base**: `python:3.11-slim`
- **Purpose**: Lightweight container for testing custom agents
- **Features**: Basic Python environment, mount your own agent script
- **Usage**: Requires agent script to be mounted at `/app/agent.py`

## Building Images

### Build All Images

```bash
# From project root
docker-compose build
```

### Build Individual Images

```bash
# Registry
docker build -f docker/registry/Dockerfile -t mcp-mesh-registry .

# Base agent image
docker build -f docker/agent/Dockerfile.base -t mcp-mesh-base .

# Python agent
docker build -f docker/agent/Dockerfile.python -t mcp-mesh-agent .

# Test agent
docker build -f docker/agent/Dockerfile -t mcp-mesh-test-agent .
```

## Running Services

### Quick Start

```bash
# Start complete mesh
docker-compose up --build

# Start only registry
docker-compose up --build registry

# Start specific agents
docker-compose up --build hello-world-agent system-agent
```

### Access Points

- **Registry**: http://localhost:8000
- **Hello World Agent**: http://localhost:8081
- **System Agent**: http://localhost:8082

## Environment Configuration

Create `.env.local` to override defaults:

```bash
# .env.local
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
HELLO_WORLD_PORT=9081
SYSTEM_AGENT_PORT=9082

# For additional agents
WEATHER_AGENT_PORT=8083
CUSTOM_AGENT_PORT=8084
```

## Health Checks

All services include health check endpoints:

```bash
# Check registry
curl http://localhost:8000/health

# Check agents
curl http://localhost:8081/health
curl http://localhost:8082/health
```

## Using Existing Agent Examples

MCP Mesh provides several ready-to-use agent examples in the `examples/` directory:

### Available Examples

#### Simple Agents (`examples/simple/`)

- **`hello_world.py`** - Basic greeting agent (used by default)
- **`system_agent.py`** - System monitoring agent (used by default)

#### Advanced Agents (`examples/advanced/`)

- **`weather_agent.py`** - Weather service with API integration
- **`llm_chat_agent.py`** - LLM-powered chat agent
- **`llm_sampling_agent.py`** - LLM sampling and analysis
- **`system_agent.py`** - Advanced system monitoring

### Adding Custom Agents

#### Method 1: Add to docker-compose.yml

```yaml
# Uncomment and customize the example in docker-compose.yml
custom-agent:
  image: mcp-mesh-base:latest
  container_name: mcp-mesh-custom-agent
  ports:
    - "8083:8080"
  volumes:
    # Choose any example or your own script
    - ./examples/advanced/weather_agent.py:/app/agent.py:ro
  environment:
    - MCP_MESH_REGISTRY_URL=http://registry:8000
    - MCP_MESH_AGENT_NAME=weather-agent
    - MCP_MESH_HTTP_PORT=8080
  depends_on:
    mcp-mesh-base:
      condition: service_completed_successfully
  networks:
    - mcp-mesh
```

#### Method 2: Run Individual Container

```bash
# Run weather agent
docker run -d \
  --network mcp-mesh-network \
  -p 8083:8080 \
  -v ./examples/advanced/weather_agent.py:/app/agent.py:ro \
  -e MCP_MESH_REGISTRY_URL=http://registry:8000 \
  -e MCP_MESH_AGENT_NAME=weather-agent \
  mcp-mesh-base:latest

# Run LLM chat agent
docker run -d \
  --network mcp-mesh-network \
  -p 8084:8080 \
  -v ./examples/advanced/llm_chat_agent.py:/app/agent.py:ro \
  -e MCP_MESH_REGISTRY_URL=http://registry:8000 \
  -e MCP_MESH_AGENT_NAME=llm-chat \
  -e OPENAI_API_KEY=your-api-key \
  mcp-mesh-base:latest
```

#### Method 3: Create Your Own Agent

```bash
# Create new agent script
cp examples/simple/hello_world.py my_custom_agent.py
# Edit my_custom_agent.py...

# Add to docker-compose.yml or run directly
docker run -d \
  --network mcp-mesh-network \
  -p 8085:8080 \
  -v ./my_custom_agent.py:/app/agent.py:ro \
  -e MCP_MESH_REGISTRY_URL=http://registry:8000 \
  -e MCP_MESH_AGENT_NAME=my-custom-agent \
  mcp-mesh-base:latest
```

## Development Usage

### Working with Examples

```bash
# Start with advanced weather agent
docker-compose up --build registry
docker run -d \
  --network mcp-mesh-network \
  -p 8083:8080 \
  -v ./examples/advanced/weather_agent.py:/app/agent.py:ro \
  -e MCP_MESH_REGISTRY_URL=http://registry:8000 \
  -e MCP_MESH_AGENT_NAME=weather-service \
  -e WEATHER_API_KEY=your-api-key \
  mcp-mesh-base:latest

# Test the weather agent
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Debug Mode

```bash
# Enable debug logging
MCP_MESH_LOG_LEVEL=DEBUG MCP_MESH_DEBUG_MODE=true docker-compose up
```

### Development with Hot Reload

```bash
# Use local source code
docker-compose -f docker-compose.yml -f docker-compose.override.yml up --build
```

## Architecture Notes

- **Resilient Design**: Agents work standalone and enhance when registry available
- **Security**: All containers run as non-root users
- **Networking**: Isolated Docker network for inter-service communication
- **Storage**: Registry data persisted in Docker volume
- **Health**: Comprehensive health checking for all services

## Troubleshooting

### Container Issues

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f registry
docker-compose logs -f hello-world-agent

# Debug container
docker-compose exec registry sh
docker-compose exec hello-world-agent bash
```

### Network Issues

```bash
# Check network
docker network inspect mcp-mesh-network

# Test connectivity
docker-compose exec hello-world-agent ping registry
```

### Build Issues

```bash
# Clean rebuild
docker-compose build --no-cache

# Remove all containers and volumes
docker-compose down -v
docker system prune -f
```

For more detailed examples and usage patterns, see the working examples in `examples/docker-examples/`.
