# MCP Mesh Environment Variables

## Logging & Debug

- `MCP_MESH_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) - default: INFO
- `MCP_MESH_DEBUG_MODE`: Enable debug mode (true/false, 1/0, yes/no) - forces DEBUG level

## Registry Configuration

- `MCP_MESH_REGISTRY_URL`: Complete registry server URL - default: http://localhost:8000
- `MCP_MESH_REGISTRY_HOST`: Registry hostname for connection - default: localhost
- `MCP_MESH_REGISTRY_PORT`: Registry port for connection - default: 8000

## HTTP Server Configuration

### Server Binding (Local Interface)

- `HOST`: HTTP server binding address (what interface to bind to) - default: 0.0.0.0
- `MCP_MESH_HTTP_PORT`: HTTP server port - default: 8080
- `MCP_MESH_HTTP_ENABLED`: Enable HTTP transport (true/false) - default: true

### Agent Advertisement (External Address)

- `MCP_MESH_HTTP_HOST`: Agent's external hostname/address announced to registry - default: auto-detected
- `MCP_MESH_HTTP_ENDPOINT`: Complete HTTP endpoint URL announced to registry - default: auto-assigned
- `POD_IP`: Pod IP address (Kubernetes fallback) - default: auto-detected

## Service Discovery (Kubernetes)

- `SERVICE_NAME`: Kubernetes service name (auto-detected from app.kubernetes.io/name label)
- `NAMESPACE`: Kubernetes namespace (auto-detected from metadata.namespace)
- `POD_NAME`: Pod name (auto-detected from metadata.name)
- `NODE_NAME`: Node name (auto-detected from spec.nodeName)

## Agent Configuration

- `MCP_MESH_AGENT_NAME`: Agent name override - default: auto-detected
- `MCP_MESH_NAMESPACE`: Agent namespace - default: default
- `MCP_MESH_ENABLED`: Enable MCP Mesh globally - default: true

## Auto-Run Configuration

- `MCP_MESH_AUTO_RUN`: Enable auto-run service (true/false) - default: true
- `MCP_MESH_AUTO_RUN_INTERVAL`: Auto-run heartbeat interval in seconds - default: 30

## Health & Monitoring

- `MCP_MESH_HEALTH_INTERVAL`: Health check interval in seconds - default: 30

## Update Strategy

- `MCP_MESH_DYNAMIC_UPDATES`: Enable dynamic updates - default: true
- `MCP_MESH_UPDATE_STRATEGY`: Update strategy (immediate, graceful) - default: immediate
- `MCP_MESH_UPDATE_GRACE_PERIOD`: Grace period for updates in seconds - default: 30

## Python Runtime

- `PYTHONUNBUFFERED`: Force Python stdout/stderr unbuffered - default: 1
- `PYTHONPATH`: Python module search path - default: /app/lib:/app/agents

## Performance Tuning

- `UVICORN_WORKERS`: Number of worker processes - default: 1
- `UVICORN_LOOP`: Event loop implementation - default: auto
- `UVICORN_LIFESPAN`: Enable lifespan events - default: on

## Docker Compose Examples

### Registry Service

```yaml
registry:
  environment:
    - HOST=0.0.0.0 # Bind to all interfaces
    - PORT=8000 # Registry port
    - MCP_MESH_LOG_LEVEL=INFO
```

### Agent Service

```yaml
hello-world-agent:
  environment:
    - HOST=0.0.0.0 # HTTP server binding
    - MCP_MESH_HTTP_HOST=hello-world-agent # Address announced to registry
    - MCP_MESH_HTTP_PORT=8080 # Agent HTTP port
    - MCP_MESH_REGISTRY_URL=http://registry:8000
```

## Kubernetes Examples

### Auto-Detection Pattern

```yaml
env:
  # Service discovery - auto-detect from labels
  - name: SERVICE_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['app.kubernetes.io/name']
  - name: NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # HTTP server binding
  - name: HOST
    value: "0.0.0.0"
```

## Legacy/Deprecated Variables

- `MCP_MESH_HTTP_ENDPOINT`: Use SERVICE_NAME + NAMESPACE in K8s, or MCP_MESH_HTTP_HOST in Docker
- `MCP_MESH_ENABLE_HTTP`: Use MCP_MESH_HTTP_ENABLED instead
