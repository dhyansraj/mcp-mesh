# MCP Mesh Kubernetes Examples

This directory contains Kubernetes deployment examples for MCP Mesh, demonstrating how to deploy the registry and agents in a Kubernetes cluster with proper health checks, service discovery, and dependency injection.

## Quick Start with Minikube

### Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/docs/start/) installed and running
- [kubectl](https://kubernetes.io/docs/tasks/tools/) configured to work with Minikube
- Docker for building local images

### 1. Start Minikube

```bash
minikube start
```

### 2. Build Docker Images in Minikube Context

Switch to Minikube's Docker daemon and build the required images:

```bash
# Switch to Minikube Docker context
eval $(minikube docker-env)

# Build registry image
docker build -f docker/registry/Dockerfile -t mcp-mesh-registry:latest .

# Build agent base image
docker build -f docker/agent/Dockerfile.base -t mcp-mesh-base:latest .

# Verify images are built
docker images | grep mcp-mesh
```

### 3. Deploy to Kubernetes

```bash
# Deploy the complete MCP Mesh stack
kubectl apply -k examples/k8s/base/

# Check deployment status
kubectl get pods -n mcp-mesh
```

Wait for all pods to be in `Running` state. The registry may take a few minutes to initialize the database.

## Architecture Overview

The deployment includes:

- **PostgreSQL Database** - Persistent storage for registry data
- **MCP Mesh Registry** - Central service registry and discovery
- **Hello World Agent** - Example agent with greeting capabilities
- **System Agent** - System information and time services
- **FastMCP Agent** - Demonstrates FastMCP integration with mesh capabilities
- **Dependent Agent** - Shows dependency injection patterns

## Accessing Services

### Port Forwarding for Local Access

To access the services from your local machine, set up port forwarding:

```bash
# Registry (health endpoint and agent registration)
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 &

# Hello World Agent
kubectl port-forward -n mcp-mesh svc/mcp-mesh-hello-world 9090:9090 &

# System Agent
kubectl port-forward -n mcp-mesh svc/mcp-mesh-system-agent 8080:8080 &

# FastMCP Agent
kubectl port-forward -n mcp-mesh svc/mcp-mesh-fastmcp-agent 9092:9092 &

# Dependent Agent
kubectl port-forward -n mcp-mesh svc/mcp-mesh-dependent-agent 9093:9093 &
```

### Testing Health Endpoints

All services support both GET and HEAD methods for health checks:

```bash
# Registry health
curl -X HEAD -I http://localhost:8000/health
curl -s http://localhost:8000/health | jq

# Agent health examples
curl -X HEAD -I http://localhost:9090/health
curl -s http://localhost:9090/health | jq
```

### Testing MCP Tool Endpoints

List available tools on each agent:

```bash
# Hello World Agent
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# System Agent
curl -s -X POST http://localhost:8080/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# FastMCP Agent
curl -s -X POST http://localhost:9092/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Dependent Agent
curl -s -X POST http://localhost:9093/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'
```

### Testing Tool Calls with Dependency Injection

Call tools that demonstrate dependency injection:

```bash
# Call dependent agent tool that uses time service from FastMCP agent
curl -s -X POST http://localhost:9093/mcp/ \
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
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].object'

# Call hello world tool that uses system agent dependency
curl -s -X POST http://localhost:9090/mcp/ \
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
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text'
```

### Registry Agents List

Check which agents are registered:

```bash
curl -s http://localhost:8000/agents | jq '.agents[] | {name: .name, status: .status, capabilities: (.capabilities | length), endpoint: .endpoint}'
```

## Key Features Demonstrated

### 1. **Optimized Health Checks**

- Uses native Kubernetes `httpGet` probes instead of `exec` commands
- Supports both GET and HEAD methods for efficient health monitoring
- Custom health headers for detailed status information

### 2. **Service Discovery**

- Automatic agent registration with the central registry
- Kubernetes DNS-based service resolution
- Dynamic dependency injection between agents

### 3. **Dependency Injection**

- Dependent Agent uses time service from FastMCP Agent
- Hello World Agent uses system information from System Agent
- Automatic capability resolution and service binding

### 4. **Hybrid FastMCP + MCP Mesh Architecture**

- FastMCP decorators (`@app.tool`) for familiar MCP development
- MCP Mesh decorators (`@mesh.tool`) for dependency injection
- No manual server setup required - mesh handles everything

## Troubleshooting

### Pod Not Starting

Check pod logs for detailed error information:

```bash
kubectl logs -n mcp-mesh <pod-name>
kubectl describe pod -n mcp-mesh <pod-name>
```

### Service Not Accessible

Verify service endpoints are populated:

```bash
kubectl get endpoints -n mcp-mesh
```

If endpoints are empty, check that pod labels match service selectors.

### Database Connection Issues

Check PostgreSQL connectivity:

```bash
kubectl logs -n mcp-mesh mcp-mesh-postgres-0
kubectl logs -n mcp-mesh mcp-mesh-registry-0
```

### Port Forwarding Issues

Kill existing port forwards and restart:

```bash
pkill -f "port-forward"
# Then restart the port forwarding commands
```

## Advanced Configuration

### Customizing Agent Code

Agent code is stored in ConfigMaps and can be modified:

```bash
kubectl edit configmap mcp-agent-code -n mcp-mesh
```

After editing, restart the affected deployments:

```bash
kubectl rollout restart deployment/mcp-mesh-<agent-name> -n mcp-mesh
```

### Scaling

Scale agent deployments:

```bash
kubectl scale deployment mcp-mesh-hello-world --replicas=2 -n mcp-mesh
```

### Persistent Storage

The registry uses a persistent volume for database storage. To reset data:

```bash
kubectl delete pvc -n mcp-mesh --all
kubectl rollout restart statefulset/mcp-mesh-postgres -n mcp-mesh
kubectl rollout restart statefulset/mcp-mesh-registry -n mcp-mesh
```

## Cleanup

Remove the entire deployment:

```bash
kubectl delete namespace mcp-mesh
```

Or remove specific components:

```bash
kubectl delete -k examples/k8s/base/
```

## Development Workflow

1. **Make code changes** in your local development environment
2. **Rebuild images** in Minikube context using the build commands above
3. **Update ConfigMaps** if agent code changed
4. **Restart deployments** to pick up new images/code
5. **Test changes** using the port forwarding and curl commands

For faster iteration, you can patch deployments to use `imagePullPolicy: Always` and push to a container registry, or use tools like [Skaffold](https://skaffold.dev/) for automated development workflows.

## Expected Tool Lists

After successful deployment, each agent should expose the following tools:

### Hello World Agent Tools

- `hello_mesh_simple` - MCP Mesh greeting with simple typing
- `hello_mesh_typed` - MCP Mesh greeting with smart tag-based dependency resolution
- `test_dependencies` - Test function showing hybrid dependency resolution

### System Agent Tools

- `get_current_time` - Get the current system date and time
- `fetch_system_overview` - Get comprehensive system information
- `check_how_long_running` - Get system uptime information
- `analyze_storage_and_os` - Get disk and OS information
- `perform_health_diagnostic` - Get system status including current time

### FastMCP Agent Tools

- `get_current_time` - Get the current system time
- `calculate_with_timestamp` - Perform math operation with timestamp from time service
- `process_data` - Process and format data

### Dependent Agent Tools

- `generate_report` - Generate a timestamped report using the time service
- `analyze_data` - Analyze data with timestamp from time service

## Technical Implementation Details

### Optimized Health Probes

The deployment uses efficient `httpGet` probes instead of complex `exec` commands:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 9090
    httpHeaders:
      - name: Accept
        value: application/json
```

### HEAD Method Support

All health endpoints support both GET and HEAD methods for efficient monitoring:

- HEAD requests return only headers (no response body)
- Includes custom headers: `X-Health-Status`, `X-Service-Version`, `X-Uptime-Seconds`

### Service Discovery

- Automatic registration with MCP Mesh registry
- Kubernetes DNS-based service resolution
- Dynamic dependency injection between agents

### Agent Code Injection

Agent Python code is stored in ConfigMaps and mounted into containers, allowing easy customization without rebuilding images.

This deployment demonstrates a production-ready MCP Mesh setup with proper health monitoring, service discovery, and dependency injection capabilities.
