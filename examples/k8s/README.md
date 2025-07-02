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

### 3. Enable Ingress in Minikube

Enable the ingress controller to access services without port forwarding:

```bash
# Enable ingress addon
minikube addons enable ingress

# Verify ingress controller is running
kubectl get pods -n ingress-nginx
```

### 4. Deploy to Kubernetes

```bash
# Deploy the complete MCP Mesh stack
kubectl apply -k examples/k8s/base/

# Check deployment status
kubectl get pods -n mcp-mesh

# Check ingress status
kubectl get ingress -n mcp-mesh
```

Wait for all pods to be in `Running` state. The registry may take a few minutes to initialize the database.

### 5. Configure Local Access

Add the ingress hostnames to your `/etc/hosts` file for local access:

```bash
# Get minikube IP
MINIKUBE_IP=$(minikube ip)

# Add hostnames to /etc/hosts
echo "
# MCP Mesh services
$MINIKUBE_IP mcp-mesh.local
$MINIKUBE_IP registry.mcp-mesh.local
$MINIKUBE_IP hello-world.mcp-mesh.local
$MINIKUBE_IP system-agent.mcp-mesh.local
$MINIKUBE_IP fastmcp-agent.mcp-mesh.local
$MINIKUBE_IP dependent-agent.mcp-mesh.local" | sudo tee -a /etc/hosts
```

## Architecture Overview

The deployment includes:

- **PostgreSQL Database** - Persistent storage for registry data
- **MCP Mesh Registry** - Central service registry and discovery
- **Hello World Agent** - Example agent with greeting capabilities
- **System Agent** - System information and time services
- **FastMCP Agent** - Demonstrates FastMCP integration with mesh capabilities
- **Dependent Agent** - Shows dependency injection patterns

## Accessing Services

### Option 1: Host-based Ingress (Recommended)

Each service has its own hostname:

- **Registry**: `http://registry.mcp-mesh.local`
- **Hello World Agent**: `http://hello-world.mcp-mesh.local`
- **System Agent**: `http://system-agent.mcp-mesh.local`
- **FastMCP Agent**: `http://fastmcp-agent.mcp-mesh.local`
- **Dependent Agent**: `http://dependent-agent.mcp-mesh.local`

### Option 2: Path-based Ingress

All services accessible via `http://mcp-mesh.local/SERVICE_NAME/`:

- **Registry**: `http://mcp-mesh.local/registry/`
- **Hello World**: `http://mcp-mesh.local/hello-world/`
- **System Agent**: `http://mcp-mesh.local/system-agent/`
- **FastMCP Agent**: `http://mcp-mesh.local/fastmcp-agent/`
- **Dependent Agent**: `http://mcp-mesh.local/dependent-agent/`

### Configure meshctl for Ingress

Configure meshctl to use the ingress registry:

```bash
# Configure meshctl to use ingress registry
./bin/meshctl config set registry_host registry.mcp-mesh.local
./bin/meshctl config set registry_port 80

# Verify configuration
./bin/meshctl config show

# Test connection
./bin/meshctl list agents
```

### Testing Health Endpoints

All services support both GET and HEAD methods for health checks:

```bash
# Registry health
curl -X HEAD -I http://registry.mcp-mesh.local/health
curl -s http://registry.mcp-mesh.local/health | jq

# Agent health examples
curl -X HEAD -I http://hello-world.mcp-mesh.local/health
curl -s http://hello-world.mcp-mesh.local/health | jq

# Or using path-based routing
curl -s http://mcp-mesh.local/registry/health | jq
curl -s http://mcp-mesh.local/hello-world/health | jq
```

### Testing MCP Tool Endpoints

List available tools on each agent:

```bash
# Hello World Agent
curl -s -X POST http://hello-world.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# System Agent
curl -s -X POST http://system-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# FastMCP Agent
curl -s -X POST http://fastmcp-agent.mcp-mesh.local/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Dependent Agent
curl -s -X POST http://dependent-agent.mcp-mesh.local/mcp/ \
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
        "title": "System Status Report",
        "content": "All systems operational"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.structuredContent'

# Call hello world tool that uses system agent dependency
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
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.structuredContent'

# Test cross-agent dependency injection with data analysis
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
        "data": ["metric1", "metric2", "metric3"]
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.structuredContent'
```

### Registry Agents List

Check which agents are registered:

```bash
curl -s http://registry.mcp-mesh.local/agents | jq '.agents[] | {name: .name, status: .status, capabilities: (.capabilities | length), endpoint: .endpoint}'
```

## Ingress Configuration

The deployment includes two ingress configurations for flexible access:

### Host-based Ingress

- Provides dedicated subdomains for each service
- Easy to remember URLs: `registry.mcp-mesh.local`, `hello-world.mcp-mesh.local`
- Direct access without path prefixes
- Recommended for development and testing

### Path-based Ingress

- Single domain with service paths: `mcp-mesh.local/registry/`
- Uses nginx rewrite rules to strip path prefixes
- Useful for environments with limited hostname management
- Supports the same functionality as host-based routing

### Benefits of Ingress over Port Forwarding

- **No background processes**: No need to manage multiple `kubectl port-forward` commands
- **Persistent access**: Services remain accessible even after kubectl restarts
- **Production-ready**: Ingress is the standard way to expose services in Kubernetes
- **Load balancing**: Native support for multiple replicas
- **SSL termination**: Can easily add HTTPS certificates

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

### 4. **Fast Heartbeat Optimization**

- 5-second heartbeat intervals for rapid health monitoring
- HEAD request optimization for minimal network overhead
- Fast failure detection and recovery
- Configurable via `MCP_MESH_HEALTH_INTERVAL` environment variable

### 5. **Hybrid FastMCP + MCP Mesh Architecture**

- FastMCP decorators (`@app.tool`) for familiar MCP development
- MCP Mesh decorators (`@mesh.tool`) for dependency injection
- No manual server setup required - mesh handles everything

### 6. **Production-Ready Networking**

- Ingress-based routing with both host and path-based access
- No port forwarding required for development
- Native Kubernetes service discovery and load balancing
- Support for multiple replicas and high availability

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

### Ingress Access Issues

Check ingress status and minikube IP:

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
