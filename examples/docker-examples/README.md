# MCP Mesh Docker Examples

This directory contains a complete Docker Compose setup demonstrating the MCP Mesh architecture with:

- **Go-based Registry**: Service discovery and coordination
- **Python Agents**: Multiple containerized agents with dependency injection
- **Automatic Service Discovery**: Agents automatically find and communicate with each other
- **Source Installation**: All components built from source for development

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/docker-examples

# Start the entire mesh
docker-compose up --build

# In another terminal, use meshctl to interact with the mesh
cd ../..  # Back to project root
./bin/meshctl list --registry http://localhost:8000
```

That's it! The mesh will automatically:

1. Start the Go registry on port 8000
2. Build and start Python agents
3. Agents auto-register with the registry
4. Dependency injection happens automatically
5. You can interact with the mesh using `meshctl`

## 🏗️ Resilient Architecture

MCP Mesh uses a **resilient architecture** where agents work independently and enhance themselves when the registry is available:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Registry      │    │  Hello World     │    │  System Agent  │
│   (Go + SQLite) │    │  (Python)        │    │  (Python)       │
│   Port: 8000    │◄──►│  Port: 8081      │◄──►│  Port: 8082     │
│   [Optional]    │    │  [Standalone]    │    │  [Standalone]   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
        ▲                        ▲                        ▲
        │              ┌─────────┴────────┐              │
        └──────────────│  meshctl Client  │──────────────┘
                      │  (Dashboard)     │
                      └──────────────────┘
```

### 🔄 Resilience Behavior

1. **Agents Start Independently**: No hard dependency on registry
2. **Registry Available**: Agents auto-register and wire up dependencies
3. **Registry Goes Down**: Agents keep existing connections and continue working
4. **Registry Returns**: Agents reconnect automatically

### Services

- **registry**: Go-based registry with SQLite database (optional for agent operation)
- **hello-world-agent**: Python agent with greeting capabilities (works standalone)
- **system-agent**: Python agent with system monitoring (works standalone)
- **meshctl**: CLI tool for mesh management (run from host)

## 📁 Directory Structure

```
examples/docker-examples/
├── docker-compose.yml          # Main orchestration file
├── docker-compose.override.yml # Development overrides
├── .env                       # Environment defaults
├── .dockerignore              # Docker build optimization
├── README.md                  # This file
├── ARM_BUILD_NOTES.md         # ARM/Apple Silicon build notes
├── registry/
│   ├── Dockerfile             # Go registry container (Alpine)
│   └── Dockerfile.debian      # Alternative Debian build
├── agents/
│   └── base/
│       ├── Dockerfile.base    # Base Python + mcp_mesh image
│       └── requirements.txt   # Base Python dependencies
└── scripts/
    ├── demo.sh                # Interactive demo script
    ├── health-check.sh        # Health monitoring script
    └── switch-to-debian.sh    # Switch to Debian build if needed

# Agent code is mounted from:
../simple/hello_world.py       # → hello-world-agent container
../simple/system_agent.py      # → system-agent container
```

## 🔧 Environment Variables

All environment variables from `MCP_MESH_ENV_VARS.md` are supported. Key defaults:

```bash
# Registry
MCP_MESH_REGISTRY_URL=http://registry:8000  # Internal container URL
MCP_MESH_REGISTRY_PORT=8000

# Agents HTTP Configuration
MCP_MESH_HTTP_PORT=8080                     # Port agents use inside containers
MCP_MESH_HTTP_HOST=0.0.0.0

# Agents
MCP_MESH_ENABLED=true
MCP_MESH_AUTO_RUN=true
MCP_MESH_NAMESPACE=default

# Logging
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
```

Create a `.env.local` file to override defaults:

```bash
# .env.local
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_HTTP_PORT=9000  # Change internal port if needed
```

### 🔌 Using Your Own Agents

The example mounts agents from `../simple/` but you can easily use your own:

**Option 1: Modify docker-compose.yml volumes:**

```yaml
volumes:
  - /path/to/your/agent.py:/app/agent.py:ro
```

**Option 2: Set environment variables in your agent:**

```python
import os

@mesh.agent(
    name=os.getenv("MCP_MESH_AGENT_NAME", "my-agent"),
    http_port=int(os.getenv("MCP_MESH_HTTP_PORT", "8080"))
)
class MyAgent:
    pass
```

**Option 3: Use advanced agents:**

```yaml
# Mount advanced agents instead
volumes:
  - ../advanced/weather_agent.py:/app/agent.py:ro
  - ../advanced/llm_chat_agent.py:/app/agent.py:ro
```

**Option 4: Add your own service:**

```yaml
# Add to docker-compose.yml
my-custom-agent:
  image: mcp-mesh-base:latest
  volumes:
    - /path/to/my/custom_agent.py:/app/agent.py:ro
  environment:
    - MCP_MESH_AGENT_NAME=my-custom-agent
    - MCP_MESH_HTTP_PORT=8080
  # ... rest of configuration
```

## 🎯 Usage Examples

### 1. Basic Operations

```bash
# Start the mesh
docker-compose up --build

# Check status
docker-compose ps

# View logs
docker-compose logs -f hello-world-agent
docker-compose logs -f system-agent
docker-compose logs -f registry

# Stop the mesh
docker-compose down
```

### 2. Using meshctl Dashboard

```bash
# From project root directory
cd ../..

# List all agents
./bin/meshctl list --registry http://localhost:8000

# Get detailed status
./bin/meshctl status --registry http://localhost:8000

# Monitor in real-time
./bin/meshctl status --registry http://localhost:8000 --follow
```

### 3. Testing Agent Communication

```bash
# Test hello-world agent
curl http://localhost:8081/tools/greeting

# Test system agent
curl http://localhost:8082/tools/date_service

# Test dependency injection (once both agents are running)
curl http://localhost:8081/tools/dependency_test
```

### 4. Direct Registry API

```bash
# Get registry health
curl http://localhost:8000/health

# List registered agents
curl http://localhost:8000/agents

# Get agent details
curl http://localhost:8000/agents/hello-world
```

### 5. Testing Resilient Architecture

```bash
# Start all services
docker-compose up -d

# Test agents work standalone (before they register)
curl http://localhost:8081/tools/greeting
curl http://localhost:8082/tools/date_service

# Wait for registry connection (30 seconds)
sleep 30

# Test enhanced functionality (with dependency injection)
curl http://localhost:8081/tools/dependency_test

# Test resilience: stop registry
docker-compose stop registry

# Agents should continue working with cached connections
curl http://localhost:8081/tools/dependency_test

# Restart registry
docker-compose start registry

# Agents should reconnect automatically
```

## 🔍 Understanding Dependency Injection

This example demonstrates automatic dependency injection:

1. **System Agent provides**: `date_service`, `info`, `uptime_info`
2. **Hello World Agent depends on**: `date_service`, `info`
3. **Automatic Resolution**: Registry automatically connects them

### Example Flow

```python
# In hello_world_agent.py
@mesh.tool(dependencies=["date_service"])
def hello_mesh_simple(date_service=None):
    if date_service:
        current_date = date_service()  # Calls system agent!
        return f"Hello! Today is {current_date}"
```

The `date_service` parameter is automatically injected with a proxy to the system agent's `get_current_time()` function.

## 🐛 Debugging

### Check Container Health

```bash
# Check all container health
docker-compose ps

# Check specific service
docker inspect mcp-mesh-hello-world --format='{{json .State.Health}}'
```

### View Detailed Logs

```bash
# All services
docker-compose logs

# Specific service with timestamps
docker-compose logs -t -f system-agent

# Follow logs for dependency resolution
docker-compose logs -f | grep -i "inject\|depend\|register"
```

### Common Issues

1. **Port conflicts**: Change ports in `.env.local`
2. **Build issues**: Clean and rebuild with `docker-compose build --no-cache`
3. **Registry connection**: Check `MCP_MESH_REGISTRY_URL` in agent logs
4. **Dependency injection delays**: Normal for agents to take 30-60 seconds to fully connect

## 🧪 Development Workflow

### Modify an Agent

```bash
# 1. Edit agent code
vim agents/hello-world/hello_world_agent.py

# 2. Rebuild specific service
docker-compose build hello-world-agent

# 3. Restart just that service
docker-compose up -d hello-world-agent

# 4. Check logs
docker-compose logs -f hello-world-agent
```

### Add a New Agent

```bash
# 1. Create agent directory
mkdir agents/my-agent

# 2. Create Dockerfile (copy from hello-world)
cp agents/hello-world/Dockerfile agents/my-agent/

# 3. Create agent code
vim agents/my-agent/my_agent.py

# 4. Add to docker-compose.yml
# (Add new service definition)

# 5. Start the new agent
docker-compose up --build my-agent
```

### Update mcp_mesh Source

```bash
# Rebuild base image with latest source
docker-compose build --no-cache mcp-mesh-base

# Rebuild all agents
docker-compose build

# Restart everything
docker-compose up -d
```

## 📊 Monitoring

### Health Checks

All services include health checks:

- **Registry**: `GET /health`
- **Agents**: Python health check script

### Metrics

The registry provides basic metrics:

```bash
curl http://localhost:8000/agents | jq '.[] | {name: .name, status: .status}'
```

### Logs

Structured logging is available:

```bash
# JSON formatted logs
docker-compose logs registry | jq '.'

# Filter for errors
docker-compose logs | grep -i error
```

## 🔐 Security Notes

- All containers run as non-root users
- Internal network isolation via Docker networks
- External access only on specified ports
- SQLite database is persisted in Docker volume

## 🤝 Contributing

To contribute to these examples:

1. Test your changes with: `docker-compose up --build`
2. Verify with meshctl: `./bin/meshctl list --registry http://localhost:8000`
3. Check all health checks pass: `docker-compose ps`
4. Update documentation if needed

## 📝 Next Steps

- **Scale up**: Add more agent types
- **Production**: Use external databases and service mesh
- **Monitoring**: Integrate with Prometheus/Grafana
- **Security**: Add TLS and authentication
- **CI/CD**: Automate builds and deployments

## 🆘 Getting Help

- Check container logs: `docker-compose logs`
- Verify networking: `docker network inspect mcp-mesh-network`
- Test connectivity: `docker-compose exec hello-world-agent ping registry`
- Use meshctl debugging: `./bin/meshctl status --registry http://localhost:8000 --verbose`
