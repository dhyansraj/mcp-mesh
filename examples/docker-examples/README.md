# MCP Mesh Docker Compose Examples

This directory contains Docker Compose examples for MCP Mesh, demonstrating how to deploy the registry and agents locally with proper health checks, service discovery, and dependency injection.

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed
- At least 4GB RAM available for containers

### 1. Build and Start Services

```bash
# Build and start all services
docker compose up --build -d

# Check service status
docker compose ps
```

Wait for all services to be healthy. The registry may take a minute to initialize the PostgreSQL database.

### 2. View Logs

```bash
# View all logs
docker compose logs -f

# View specific service logs
docker compose logs -f registry
docker compose logs -f hello-world-agent
```

## Architecture Overview

The deployment includes:

- **PostgreSQL Database** - Persistent storage for registry data
- **MCP Mesh Registry** - Central service registry and discovery
- **Hello World Agent** - Example agent with greeting capabilities
- **FastMCP Agent** - Demonstrates FastMCP integration with mesh capabilities
- **Dependent Agent** - Shows dependency injection patterns
- **System Agent** - System information services (can be started separately)

## Service Ports

| Service           | Port | Description                             |
| ----------------- | ---- | --------------------------------------- |
| Registry          | 8000 | Registry API and health endpoint        |
| Hello World Agent | 8081 | MCP agent with greeting tools           |
| System Agent      | 8082 | System information tools (when running) |
| FastMCP Agent     | 8083 | Time and calculation services           |
| Dependent Agent   | 8084 | Tools using dependency injection        |
| PostgreSQL        | 5432 | Database (internal)                     |
| Redis             | 6379 | Session storage and distributed tracing |
| Grafana           | 3000 | Observability dashboard (admin/admin)   |
| Tempo             | 3200 | Distributed tracing backend             |

## Testing Services

### Health Checks

All services support both GET and HEAD methods for health checks:

```bash
# Registry health
curl -X HEAD -I http://localhost:8000/health
curl -s http://localhost:8000/health | jq

# Agent health examples
curl -X HEAD -I http://localhost:8081/health
curl -s http://localhost:8081/health | jq

curl -X HEAD -I http://localhost:8082/health
curl -s http://localhost:8082/health | jq

curl -X HEAD -I http://localhost:8083/health
curl -s http://localhost:8083/health | jq

curl -X HEAD -I http://localhost:8084/health
curl -s http://localhost:8084/health | jq
```

### Registry Agents List

Check which agents are currently registered:

```bash
curl -s http://localhost:8000/agents | jq '.agents[] | {name: .name, status: .status, capabilities: (.capabilities | length), endpoint: .endpoint}'
```

### MCP Tool Discovery

List available tools on each agent:

```bash
# Hello World Agent Tools
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'

# FastMCP Agent Tools
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# System Agent Tools
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Dependent Agent Tools
curl -s -X POST http://localhost:8084/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

## Tool Examples

### Hello World Agent

**Available Tools:**

- `hello_mesh_simple` - MCP Mesh greeting with simple typing
- `hello_mesh_typed` - MCP Mesh greeting with smart tag-based dependency resolution
- `test_dependencies` - Test function showing hybrid dependency resolution

```bash
# Simple greeting
meshctl call hello_mesh_simple

# Typed greeting with dependency resolution
meshctl call hello_mesh_typed
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# Simple greeting
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_simple",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Typed greeting with dependency resolution
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_typed",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

</details>

### FastMCP Agent

**Available Tools:**

- `get_current_time` - Get the current system time
- `calculate_with_timestamp` - Perform math operation with timestamp from time service
- `process_data` - Process and format data

```bash
# Get current time
meshctl call get_current_time

# Math calculation with timestamp
meshctl call calculate_with_timestamp '{"operation": "add", "a": 10, "b": 5}'

# Process data
meshctl call process_data '{"input": "sample data to process"}'
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# Get current time
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_time",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Math calculation with timestamp
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "calculate_with_timestamp",
      "arguments": {
        "operation": "add",
        "a": 10,
        "b": 5
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Process data
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "process_data",
      "arguments": {
        "input": "sample data to process"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

</details>

### System Agent

**Available Tools:**

- `get_current_time` - Get the current system date and time
- `fetch_system_overview` - Get comprehensive system information
- `check_how_long_running` - Get system uptime information
- `analyze_storage_and_os` - Get disk and OS information
- `perform_health_diagnostic` - Get system status including current time

```bash
# Get current time
meshctl call get_current_time

# Get system overview
meshctl call fetch_system_overview

# Check system uptime
meshctl call check_how_long_running
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# Get current time
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_time",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Get system overview
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "fetch_system_overview",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Check system uptime
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "check_how_long_running",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

</details>

### Dependent Agent (3-Agent Dependency Injection Demo)

**Available Tools:**

- `generate_comprehensive_report` - **3-Agent Chain**: Dependent → FastMCP → System (with distributed tracing)
- `generate_report` - Generate a timestamped report using the time service
- `analyze_data` - Analyze data with timestamp from time service

```bash
# 🔥 3-Agent Dependency Chain with Distributed Tracing
# This demonstrates the complete dependency injection flow:
# Dependent Agent → FastMCP Agent → System Agent
meshctl call generate_comprehensive_report '{"report_title": "Multi-Agent System Report", "include_system_data": true}'

# Generate report (uses FastMCP agent's time service)
meshctl call generate_report '{"title": "System Status Report", "content": "All systems operational"}'

# Analyze data (uses dependency injection for timestamps)
meshctl call analyze_data '{"data": ["value1", "value2", "value3", "value4", "value5"]}'
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# 3-Agent Dependency Chain with Distributed Tracing
curl -s -X POST http://localhost:8084/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_comprehensive_report",
      "arguments": {
        "report_title": "Multi-Agent System Report",
        "include_system_data": true
      }
    }
  }'

# Generate report (uses FastMCP agent's time service)
curl -s -X POST http://localhost:8084/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {
        "title": "System Status Report",
        "content": "All systems operational"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Analyze data (uses dependency injection for timestamps)
curl -s -X POST http://localhost:8084/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "analyze_data",
      "arguments": {
        "data": ["value1", "value2", "value3", "value4", "value5"]
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .
```

</details>

#### 🔍 **Distributed Tracing Verification**

After calling `generate_comprehensive_report`, you can verify the distributed trace was captured:

```bash
# Check Redis trace stream for distributed tracing data
docker exec mcp-mesh-redis redis-cli XREVRANGE mesh:trace + - COUNT 9

# View trace relationships and timing
docker exec mcp-mesh-redis redis-cli XREVRANGE mesh:trace + - COUNT 9 | grep -E "(function_name|trace_id|duration_ms)" -A1
```

The trace will show the complete execution flow:

1. **Root**: `generate_comprehensive_report` (dependent-service)
2. **Child**: `get_enriched_system_info` (fastmcp-service)
3. **Grandchild**: `fetch_system_overview` (system-agent)

## Key Features Demonstrated

### 1. **🔥 NEW: Distributed Tracing with Redis Storage**

- Complete trace context propagation across all agent boundaries
- Parent-child span relationships maintained for complex dependency chains
- Real-time trace data published to Redis streams (`mesh:trace`)
- Agent metadata collection (hostname, IP, port, namespace, capabilities)
- Microsecond-precision timing measurements
- Trace visualization ready for Grafana/Tempo integration

### 2. **Fast Heartbeat Optimization**

- Agents send heartbeats every 5 seconds via HEAD requests
- Registry responds in microseconds for healthy agents
- 20-second timeout threshold prevents false negatives
- Automatic recovery from unhealthy status

### 3. **Complete Observability Stack**

- **Grafana Dashboard**: http://localhost:3000 (admin/admin) - Pre-configured MCP Mesh overview
- **Tempo Tracing**: http://localhost:3200 - Distributed trace visualization
- **Redis Streams**: Real-time trace data storage and querying
- **Prometheus Metrics**: Agent health and performance metrics at `/metrics` endpoints

### 4. **Graceful Shutdown**

- Agents automatically unregister on SIGTERM/SIGINT
- Clean shutdown prevents stale registry entries
- Test by stopping containers: `docker compose stop <service>`

### 5. **Service Discovery & Dependency Injection**

- Automatic agent registration with the central registry
- Dynamic dependency injection between agents
- Dependent Agent automatically finds and uses FastMCP Agent's time service
- No manual service binding required

### 6. **PostgreSQL Backend**

- Persistent storage for registry data
- Eliminates SQLite transaction locking issues
- Supports concurrent agent operations
- Automatic database initialization

### 7. **Hybrid FastMCP + MCP Mesh Architecture**

- FastMCP decorators (`@app.tool`) for familiar MCP development
- MCP Mesh decorators (`@mesh.tool`) for dependency injection
- No manual server setup required - mesh handles everything

## Service Management

### Start/Stop Individual Services

```bash
# Stop a service (triggers graceful shutdown)
docker compose stop fastmcp-agent

# Start a service
docker compose up -d fastmcp-agent

# Restart a service
docker compose restart hello-world-agent

# View service logs
docker compose logs -f dependent-agent
```

### Scale Services

```bash
# Not recommended for stateful registry/database
# But agents can be scaled:
docker compose up -d --scale hello-world-agent=2
```

## Troubleshooting

### Service Not Starting

Check service dependencies and logs:

```bash
# Check service status
docker compose ps

# View detailed logs
docker compose logs <service-name>

# Check resource usage
docker stats
```

### Tool Calls Failing

1. **Check agent registration:**

   ```bash
   curl -s http://localhost:8000/agents | jq '.agents[].name'
   ```

2. **Check agent health:**

   ```bash
   curl -s http://localhost:8081/health | jq '.status'
   ```

3. **Check dependency resolution:**
   ```bash
   # Look for dependency resolution in agent logs
   docker compose logs dependent-agent | grep -i "dependency\|resolve"
   ```

### Database Issues

Reset PostgreSQL data:

```bash
# Stop services
docker compose down

# Remove database volume
docker volume rm mcp-mesh-postgres-data

# Restart services
docker compose up -d
```

### Port Conflicts

If ports are already in use, modify the port mappings in `docker-compose.yml`:

```yaml
ports:
  - "8001:8000" # Change host port from 8000 to 8001
```

## Development Workflow

1. **Make code changes** in `../simple/` directory
2. **Restart affected services** to pick up changes:
   ```bash
   docker compose restart hello-world-agent
   ```
3. **Test changes** using the curl commands above
4. **Check logs** for debugging:
   ```bash
   docker compose logs -f hello-world-agent
   ```

## Configuration

### Environment Variables

Key configuration in `docker-compose.yml`:

- `MCP_MESH_AUTO_RUN_INTERVAL=5` - Heartbeat frequency (seconds)
- `MCP_MESH_HEALTH_INTERVAL=5` - Health check frequency (seconds)
- `MCP_MESH_LOG_LEVEL=DEBUG` - Logging verbosity
- `DATABASE_URL` - PostgreSQL connection string

### Agent Code

Agent implementations are in:

- `../simple/hello_world.py` - Hello World Agent
- `../simple/fastmcp_agent.py` - FastMCP Agent
- `../simple/dependent_agent.py` - Dependent Agent
- `../simple/system_agent.py` - System Agent

## Cleanup

Remove all services and data:

```bash
# Stop and remove containers, networks, and volumes
docker compose down -v

# Remove built images (optional)
docker rmi mcp-mesh-base:0.2
docker rmi $(docker images | grep mcp-mesh | awk '{print $3}')
```

## Expected Output Examples

### Successful Tool Call Response Format

All tool calls return Server-Sent Events (SSE) format:

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"..."}],"isError":false}}
```

### Registry Health Response

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 123,
  "timestamp": "2025-07-02T18:00:00.000000Z",
  "service": "mcp-mesh-registry"
}
```

### Agent Registration Response

```json
{
  "agents": [
    {
      "name": "hello-world",
      "status": "healthy",
      "capabilities": 3,
      "endpoint": "http://hello-world-agent:9090"
    }
  ]
}
```

This deployment demonstrates a production-ready MCP Mesh setup with distributed tracing, optimized heartbeats, graceful shutdown, dependency injection, persistent storage, and complete observability stack. The new 3-agent dependency chain showcases advanced distributed tracing capabilities with microsecond-precision timing and parent-child span relationships.
