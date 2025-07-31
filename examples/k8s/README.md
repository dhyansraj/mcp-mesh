# MCP Mesh Kubernetes Examples

This directory contains Kubernetes deployment examples for MCP Mesh, demonstrating how to deploy the registry and agents in a Kubernetes cluster with proper health checks, service discovery, dependency injection, and distributed tracing.

## Quick Start

### Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/docs/start/) installed and running
- [kubectl](https://kubernetes.io/docs/tasks/tools/) configured to work with Minikube
- Docker for building local images
- At least 4GB RAM available for minikube

### 1. Start Minikube and Enable Ingress

```bash
# Start minikube with sufficient resources
minikube start --cpus=4 --memory=4g

# Enable ingress addon for external access
minikube addons enable ingress

# Verify ingress controller is running
kubectl get pods -n ingress-nginx
```

### 2. Build and Deploy Services

```bash
# Switch to minikube Docker context
eval $(minikube docker-env)

# Build registry image
docker build -t mcp-mesh/registry:latest -f docker/registry/Dockerfile .

# Build Python runtime image
docker build -t mcp-mesh/python-runtime:latest -f docker/agent/Dockerfile.python .

# Deploy the complete MCP Mesh stack
kubectl apply -k examples/k8s/base/

# Check service status
kubectl get pods -n mcp-mesh
```

Wait for all services to be healthy. The registry may take a minute to initialize the PostgreSQL database.

### 3. Configure Local Access

```bash
# Get minikube IP and add hostnames to /etc/hosts
MINIKUBE_IP=$(minikube ip)
echo "
# MCP Mesh K8s Services
$MINIKUBE_IP registry.mcp-mesh.local
$MINIKUBE_IP hello-world.mcp-mesh.local
$MINIKUBE_IP system-agent.mcp-mesh.local
$MINIKUBE_IP fastmcp-agent.mcp-mesh.local
$MINIKUBE_IP enhanced-fastmcp-agent.mcp-mesh.local
$MINIKUBE_IP dependent-agent.mcp-mesh.local
$MINIKUBE_IP grafana.mcp-mesh.local" | sudo tee -a /etc/hosts
```

### 4. View Logs

```bash
# View all logs
kubectl logs -f -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry

# View specific service logs
kubectl logs -f -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-dependent-agent
kubectl logs -f -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-fastmcp-agent
```

## Architecture Overview

The deployment includes:

- **PostgreSQL Database** - Persistent storage for registry data
- **MCP Mesh Registry** - Central service registry and discovery with distributed tracing
- **Hello World Agent** - Example agent with greeting capabilities
- **FastMCP Agent** - Demonstrates FastMCP integration with mesh capabilities
- **Dependent Agent** - Shows dependency injection patterns
- **System Agent** - System information services
- **Enhanced FastMCP Agent** - Advanced proxy features and session management
- **Redis** - Session storage and distributed tracing stream processing
- **Grafana** - Observability dashboard (admin/admin)
- **Tempo** - Distributed tracing backend

## Service Access

| Service           | Ingress URL                                  | Description                             |
| ----------------- | -------------------------------------------- | --------------------------------------- |
| Registry          | http://registry.mcp-mesh.local               | Registry API and health endpoint        |
| Hello World Agent | http://hello-world.mcp-mesh.local            | MCP agent with greeting tools           |
| System Agent      | http://system-agent.mcp-mesh.local           | System information tools                |
| FastMCP Agent     | http://fastmcp-agent.mcp-mesh.local          | Time and calculation services           |
| Enhanced FastMCP  | http://enhanced-fastmcp-agent.mcp-mesh.local | Advanced proxy features                 |
| Dependent Agent   | http://dependent-agent.mcp-mesh.local        | Tools using dependency injection        |
| Grafana           | http://grafana.mcp-mesh.local                | Observability dashboard (admin/admin)   |
| Redis             | Internal (6379)                              | Session storage and distributed tracing |
| Tempo             | Internal (3200/4317)                         | Distributed tracing backend             |

## Testing Services

### Health Checks

All services support both GET and HEAD methods for health checks:

```bash
# Registry health
curl -X HEAD -I http://registry.mcp-mesh.local/health
curl -s http://registry.mcp-mesh.local/health | jq

# Agent health examples
curl -X HEAD -I http://hello-world.mcp-mesh.local/health
curl -s http://hello-world.mcp-mesh.local/health | jq

curl -X HEAD -I http://system-agent.mcp-mesh.local/health
curl -s http://system-agent.mcp-mesh.local/health | jq

curl -X HEAD -I http://fastmcp-agent.mcp-mesh.local/health
curl -s http://fastmcp-agent.mcp-mesh.local/health | jq

curl -X HEAD -I http://dependent-agent.mcp-mesh.local/health
curl -s http://dependent-agent.mcp-mesh.local/health | jq
```

### Registry Agents List

Check which agents are currently registered:

```bash
curl -s http://registry.mcp-mesh.local/agents | jq '.agents[] | {name: .name, status: .status, capabilities: (.capabilities | length), endpoint: .endpoint}'
```

### MCP Tool Discovery

List available tools on each agent:

```bash
# Hello World Agent Tools
curl -s -X POST http://hello-world.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# FastMCP Agent Tools
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# System Agent Tools
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Dependent Agent Tools
curl -s -X POST http://dependent-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Enhanced FastMCP Agent Tools
curl -s -X POST http://enhanced-fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'
```

## Tool Examples

### Hello World Agent

**Available Tools:**

- `hello_mesh_simple` - MCP Mesh greeting with simple typing
- `hello_mesh_typed` - MCP Mesh greeting with smart tag-based dependency resolution
- `test_dependencies` - Test function showing hybrid dependency resolution

```bash
# Simple greeting
curl -s -X POST http://hello-world.mcp-mesh.local/mcp/ \
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
curl -s -X POST http://hello-world.mcp-mesh.local/mcp/ \
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

### FastMCP Agent

**Available Tools:**

- `get_current_time` - Get the current system time
- `calculate_with_timestamp` - Perform math operation with timestamp from time service
- `process_data` - Process and format data
- `get_enriched_system_info` - Get enriched system information by calling system agent
- `increment_session_counter` - Increment a counter for a specific session

```bash
# Get current time
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
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
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
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
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "process_data",
      "arguments": {
        "data": "sample data to process"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Get enriched system info (dependency chain: FastMCP → System)
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_enriched_system_info",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

### System Agent

**Available Tools:**

- `get_current_time` - Get the current system date and time
- `fetch_system_overview` - Get comprehensive system information
- `check_how_long_running` - Get system uptime information
- `analyze_storage_and_os` - Get disk and OS information
- `perform_health_diagnostic` - Get system status including current time

```bash
# Get current time
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
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
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
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
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
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

# Health diagnostic with dependency injection
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "perform_health_diagnostic",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .
```

### Enhanced FastMCP Agent

**Available Tools:**

- `get_enhanced_time` - Enhanced time with metadata and auto-configured timeouts
- `calculate_enhanced` - Enhanced math with automatic retry logic and timeouts
- `stream_data_processing` - Streaming data processing with auto-configured streaming
- `get_secure_config` - Secure configuration with authentication handling
- `enhanced_session_increment` - Enhanced session management with auto-session handling

```bash
# Get enhanced time with metadata
curl -s -X POST http://enhanced-fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_enhanced_time",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Enhanced calculation with auto-retry
curl -s -X POST http://enhanced-fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "calculate_enhanced",
      "arguments": {
        "operation": "power",
        "a": 2,
        "b": 8
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Enhanced session management
curl -s -X POST http://enhanced-fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "enhanced_session_increment",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

### Dependent Agent (Multi-Agent Dependency Injection Demo)

**Available Tools:**

- `generate_comprehensive_report` - **3-Agent Chain**: Dependent → FastMCP → System (with distributed tracing)
- `generate_report` - Generate a timestamped report using the time service
- `analyze_data` - Analyze data with timestamp from time service

```bash
# 🔥 3-Agent Dependency Chain with Distributed Tracing
# This demonstrates the complete dependency injection flow:
# Dependent Agent → FastMCP Agent → System Agent
curl -s -X POST http://dependent-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_comprehensive_report",
      "arguments": {
        "report_title": "Multi-Agent K8s System Report",
        "include_system_data": true
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Generate report (uses FastMCP agent's time service)
curl -s -X POST http://dependent-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {
        "title": "K8s System Status Report",
        "content": "All K8s systems operational"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .

# Analyze data (uses dependency injection for timestamps)
curl -s -X POST http://dependent-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "analyze_data",
      "arguments": {
        "data": ["k8s-pod1", "k8s-pod2", "k8s-service", "k8s-ingress", "k8s-configmap"]
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | jq .
```

#### 🔍 **Distributed Tracing Verification**

After calling `generate_comprehensive_report`, you can verify the distributed trace was captured:

```bash
# Get minikube IP for Redis access
MINIKUBE_IP=$(minikube ip)

# Check Redis trace stream for distributed tracing data
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-redis -o jsonpath='{.items[0].metadata.name}') -- redis-cli XREVRANGE mesh:trace + - COUNT 9

# View trace relationships and timing
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-redis -o jsonpath='{.items[0].metadata.name}') -- redis-cli XREVRANGE mesh:trace + - COUNT 9 | grep -E "(function_name|trace_id|duration_ms)" -A1

# Check consumer group processing status
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-redis -o jsonpath='{.items[0].metadata.name}') -- redis-cli XINFO GROUPS mesh:trace

# Check traces in Tempo
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app=tempo -o jsonpath='{.items[0].metadata.name}') -- wget -qO- "http://localhost:3200/api/search?tags=" | jq '.traces | length'
```

The trace will show the complete execution flow:

1. **Root**: `generate_comprehensive_report` (dependent-service)
2. **Child**: `get_enriched_system_info` (fastmcp-service)
3. **Grandchild**: `fetch_system_overview` (system-agent)

## Key Features Demonstrated

### 1. **🔥 Distributed Tracing with Redis Streams & Tempo**

- Complete trace context propagation across all agent boundaries
- Parent-child span relationships maintained for complex dependency chains
- Real-time trace data published to Redis streams (`mesh:trace`)
- Registry automatically consumes and exports traces to Tempo via OTLP
- Agent metadata collection (hostname, IP, port, namespace, capabilities)
- Microsecond-precision timing measurements
- Trace visualization ready for Grafana/Tempo integration

### 2. **Fast Heartbeat Optimization**

- Agents send heartbeats every 5 seconds via HEAD requests
- Registry responds in microseconds for healthy agents
- 20-second timeout threshold prevents false negatives
- Automatic recovery from unhealthy status

### 3. **Complete Observability Stack**

- **Grafana Dashboard**: http://grafana.mcp-mesh.local (admin/admin) - Enhanced MCP Mesh overview with trace data
- **Tempo Tracing**: Internal distributed trace visualization backend
- **Redis Streams**: Real-time trace data storage and querying
- **Registry Consumer**: Automatic trace processing with consumer groups

### 4. **Ingress-Based Service Access**

- No port forwarding required - direct HTTP access via hostnames
- Production-ready networking with load balancing support
- Both host-based (`service.mcp-mesh.local`) and path-based routing
- SSL-ready for HTTPS termination

### 5. **Service Discovery & Dependency Injection**

- Automatic agent registration with the central registry
- Dynamic dependency injection between agents
- Dependent Agent automatically finds and uses FastMCP/System services
- Kubernetes DNS-based service resolution

### 6. **PostgreSQL Backend**

- Persistent storage for registry data
- Eliminates SQLite transaction locking issues
- Supports concurrent agent operations
- Automatic database initialization

### 7. **Hybrid FastMCP + MCP Mesh Architecture**

- FastMCP decorators (`@app.tool`) for familiar MCP development
- MCP Mesh decorators (`@mesh.tool`) for dependency injection
- No manual server setup required - mesh handles everything

### 8. **Enhanced Proxy Features**

- Auto-configuration of timeouts, retries, authentication
- Session affinity and management
- Streaming data processing support
- Performance optimization based on decorator metadata

## Service Management

### Start/Stop Individual Services

```bash
# Stop a service (triggers graceful shutdown)
kubectl scale deployment mcp-mesh-fastmcp-agent --replicas=0 -n mcp-mesh

# Start a service
kubectl scale deployment mcp-mesh-fastmcp-agent --replicas=1 -n mcp-mesh

# Restart a service
kubectl rollout restart deployment/mcp-mesh-hello-world -n mcp-mesh

# View service logs
kubectl logs -f -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-dependent-agent
```

### Scale Services

```bash
# Not recommended for stateful registry/database
# But agents can be scaled:
kubectl scale deployment mcp-mesh-hello-world --replicas=2 -n mcp-mesh
```

## Observability

### Grafana Dashboard

Access the enhanced Grafana dashboard at http://grafana.mcp-mesh.local (admin/admin):

- **MCP Mesh Distributed Tracing Overview** - Pie chart showing trace durations by service
- **MCP Calls** - Detailed table of individual trace calls with timing and metadata
- **Real-time updates** - 5-second refresh with 1-hour trace history
- **Service topology** - Visual representation of agent dependencies

### Registry Tracing Endpoints

Check tracing status and information:

```bash
# Registry tracing status
curl -s http://registry.mcp-mesh.local/tracing/info | jq

# Registry tracing statistics
curl -s http://registry.mcp-mesh.local/tracing/stats | jq

# Registry health with tracing info
curl -s http://registry.mcp-mesh.local/health | jq
```

## Troubleshooting

### Service Not Starting

Check service dependencies and logs:

```bash
# Check service status
kubectl get pods -n mcp-mesh

# View detailed logs
kubectl logs -n mcp-mesh <pod-name>
kubectl describe pod -n mcp-mesh <pod-name>

# Check resource usage
kubectl top pods -n mcp-mesh
```

### Tool Calls Failing

1. **Check agent registration:**

   ```bash
   curl -s http://registry.mcp-mesh.local/agents | jq '.agents[].name'
   ```

2. **Check agent health:**

   ```bash
   curl -s http://dependent-agent.mcp-mesh.local/health | jq '.status'
   ```

3. **Check dependency resolution:**
   ```bash
   # Look for dependency resolution in agent logs
   kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-dependent-agent | grep -i "dependency\|resolve"
   ```

### Database Issues

Reset PostgreSQL data:

```bash
# Stop services
kubectl scale statefulset mcp-mesh-postgres --replicas=0 -n mcp-mesh

# Remove database volume
kubectl delete pvc -n mcp-mesh postgres-data-mcp-mesh-postgres-0

# Restart services
kubectl scale statefulset mcp-mesh-postgres --replicas=1 -n mcp-mesh
kubectl rollout restart deployment/mcp-mesh-registry -n mcp-mesh
```

### Ingress Access Issues

```bash
# Check ingress status
kubectl get ingress -n mcp-mesh

# Verify minikube IP matches /etc/hosts
minikube ip

# Test ingress connectivity
curl -s http://registry.mcp-mesh.local/health

# If hostnames don't resolve, re-add to /etc/hosts
MINIKUBE_IP=$(minikube ip)
echo "$MINIKUBE_IP registry.mcp-mesh.local" | sudo tee -a /etc/hosts
```

### Distributed Tracing Issues

```bash
# Check Redis stream length
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-redis -o jsonpath='{.items[0].metadata.name}') -- redis-cli XLEN mesh:trace

# Check registry consumer group
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-redis -o jsonpath='{.items[0].metadata.name}') -- redis-cli XINFO GROUPS mesh:trace

# Check registry tracing logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry | grep -i trace

# Check Tempo connectivity
kubectl exec -n mcp-mesh $(kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry -o jsonpath='{.items[0].metadata.name}') -- nc -z tempo 4317
```

## Development Workflow

1. **Make code changes** in your local development environment
2. **Switch to minikube context**: `eval $(minikube docker-env)`
3. **Rebuild images**:

   ```bash
   # Registry changes
   docker build -t mcp-mesh/registry:latest -f docker/registry/Dockerfile .

   # Python runtime changes
   docker build -t mcp-mesh/python-runtime:latest -f docker/agent/Dockerfile.python .
   ```

4. **Update agent code** (if changed):
   ```bash
   kubectl replace -f examples/k8s/base/agents/agent-code-configmap.yaml
   ```
5. **Restart deployments**:
   ```bash
   kubectl rollout restart deployment -n mcp-mesh
   ```
6. **Test changes** using the ingress URLs

## Configuration

### Environment Variables

Key configuration in Kubernetes deployments:

- `MCP_MESH_AUTO_RUN_INTERVAL=5` - Heartbeat frequency (seconds)
- `MCP_MESH_HEALTH_INTERVAL=5` - Health check frequency (seconds)
- `MCP_MESH_LOG_LEVEL=DEBUG` - Logging verbosity
- `MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true` - Enable distributed tracing
- `REDIS_URL=redis://mcp-mesh-redis:6379` - Redis connection for tracing
- `DATABASE_URL` - PostgreSQL connection string

### Agent Code

Agent implementations are stored in ConfigMaps and can be modified:

- `examples/k8s/base/agents/agent-code-configmap.yaml` - Agent Python code
- `examples/k8s/base/agents/configmap.yaml` - Agent configuration
- `examples/simple/` - Source agent implementations

## Cleanup

Remove all services and data:

```bash
# Remove the entire namespace
kubectl delete namespace mcp-mesh

# Or remove specific components
kubectl delete -k examples/k8s/base/
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
  "timestamp": "2025-07-31T20:00:00.000000Z",
  "service": "mcp-mesh-registry",
  "distributed_tracing": {
    "enabled": true,
    "traces_processed": 27,
    "consumer_group": "mcp-mesh-registry-processors"
  }
}
```

### Agent Registration Response

```json
{
  "agents": [
    {
      "name": "dependent-service-476a55da",
      "status": "healthy",
      "capabilities": 12,
      "endpoint": "http://mcp-mesh-dependent-agent:9093"
    }
  ]
}
```

This deployment demonstrates a production-ready MCP Mesh setup with distributed tracing, ingress-based networking, optimized heartbeats, graceful shutdown, dependency injection, persistent storage, and complete observability stack. The multi-agent dependency chains showcase advanced distributed tracing capabilities with microsecond-precision timing and parent-child span relationships, all accessible through Grafana dashboards.
