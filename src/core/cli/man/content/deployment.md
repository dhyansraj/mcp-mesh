# Deployment Patterns

> Local, Docker, and Kubernetes deployment options

## Overview

MCP Mesh supports multiple deployment patterns from local development to production Kubernetes clusters. This guide covers common deployment scenarios.

## Local Development

### Quick Start

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug

# Terminal 2: Start agent
meshctl start my_agent.py --debug --auto-restart

# Terminal 3: Monitor
watch 'meshctl list'
```

### Multiple Agents

```bash
# Start multiple agents
meshctl start agent1.py agent2.py agent3.py

# Or with specific ports
MCP_MESH_HTTP_PORT=8081 python agent1.py &
MCP_MESH_HTTP_PORT=8082 python agent2.py &
MCP_MESH_HTTP_PORT=8083 python agent3.py &
```

### Hot Reload

```bash
# Auto-restart on file changes
meshctl start my_agent.py --auto-restart --watch-pattern "*.py,*.json"
```

## Docker Deployment

### Single Agent Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV HOST=0.0.0.0
ENV MCP_MESH_HTTP_HOST=my-agent
ENV MCP_MESH_REGISTRY_URL=http://registry:8000

CMD ["python", "main.py"]
```

### Docker Compose

```yaml
version: "3.8"

services:
  registry:
    image: ghcr.io/dhyansraj/mcp-mesh-registry:latest
    ports:
      - "8000:8000"
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - MCP_MESH_LOG_LEVEL=INFO

  system-agent:
    build: ./agents/system
    environment:
      - HOST=0.0.0.0
      - MCP_MESH_HTTP_HOST=system-agent
      - MCP_MESH_REGISTRY_URL=http://registry:8000
    depends_on:
      - registry

  hello-agent:
    build: ./agents/hello
    environment:
      - HOST=0.0.0.0
      - MCP_MESH_HTTP_HOST=hello-agent
      - MCP_MESH_REGISTRY_URL=http://registry:8000
    depends_on:
      - registry
      - system-agent
```

### Running

```bash
docker-compose up -d
docker-compose logs -f
docker-compose ps
```

## Kubernetes Deployment

### Registry Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-mesh-registry
  template:
    metadata:
      labels:
        app: mcp-mesh-registry
    spec:
      containers:
        - name: registry
          image: ghcr.io/dhyansraj/mcp-mesh-registry:latest
          ports:
            - containerPort: 8000
          env:
            - name: HOST
              value: "0.0.0.0"
            - name: PORT
              value: "8000"
            - name: MCP_MESH_LOG_LEVEL
              value: "INFO"
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
spec:
  selector:
    app: mcp-mesh-registry
  ports:
    - port: 8000
      targetPort: 8000
```

### Agent Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-agent
  namespace: mcp-mesh
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-agent
  template:
    metadata:
      labels:
        app: my-agent
    spec:
      containers:
        - name: agent
          image: my-registry/my-agent:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST
              value: "0.0.0.0"
            - name: MCP_MESH_HTTP_PORT
              value: "8080"
            - name: MCP_MESH_HTTP_HOST
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: MCP_MESH_REGISTRY_URL
              value: "http://mcp-mesh-registry:8000"
            - name: MCP_MESH_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 20
```

### Service Discovery

In Kubernetes, agents can discover each other via:

1. **Registry**: Standard MCP Mesh discovery
2. **K8s DNS**: `service-name.namespace.svc.cluster.local`
3. **Environment**: Injected service endpoints

## Helm Deployment

```bash
# Add MCP Mesh Helm repo
helm repo add mcp-mesh https://dhyansraj.github.io/mcp-mesh/charts

# Install registry
helm install registry mcp-mesh/registry -n mcp-mesh

# Install agent
helm install my-agent mcp-mesh/agent \
  --set image.repository=my-registry/my-agent \
  --set image.tag=latest \
  --set registryUrl=http://registry:8000
```

## Best Practices

### Health Checks

Always configure health checks:

```python
async def health_check() -> dict:
    return {
        "status": "healthy",
        "checks": {"database": True},
        "errors": [],
    }

@mesh.agent(
    name="my-service",
    health_check=health_check,
    health_check_ttl=30,
)
class MyAgent:
    pass
```

### Resource Limits

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Graceful Shutdown

```bash
# Configure shutdown timeout
meshctl start my_agent.py --shutdown-timeout 60
```

### Logging

```bash
# Structured logging for production
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false
```

## See Also

- `meshctl man environment` - Configuration options
- `meshctl man health` - Health monitoring
- `meshctl man registry` - Registry setup
