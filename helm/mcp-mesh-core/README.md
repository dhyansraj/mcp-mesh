# MCP Mesh Core Infrastructure

This umbrella chart deploys the core MCP Mesh infrastructure components:

- **PostgreSQL** - Database for registry data
- **Redis** - Cache for session storage (optional)
- **MCP Mesh Registry** - Central service registry and discovery

## Quick Start

### Prerequisites

- Kubernetes 1.19+
- Helm 3.0+

### Installation

```bash
# Install core infrastructure
helm install mcp-mesh-core ./mcp-mesh-core

# Or with custom values
helm install mcp-mesh-core ./mcp-mesh-core -f my-values.yaml
```

### Access Registry

```bash
# Port forward to access registry
kubectl port-forward -n mcp-mesh svc/mcp-mesh-core-mcp-mesh-registry 8000:8000

# Check health
curl http://localhost:8000/health
```

### Deploy Agents

After core infrastructure is running, deploy agents:

```bash
# Deploy an agent
helm install my-agent ../mcp-mesh-agent --set agent.script=my_script.py
```

## Configuration

### Enable/Disable Components

```yaml
# values.yaml
postgres:
  enabled: true # Set to false to use external PostgreSQL

redis:
  enabled: true # Set to false to disable Redis

registry:
  enabled: true # Set to false to not deploy registry
```

### Database Configuration

```yaml
# values.yaml
mcp-mesh-postgres:
  postgres:
    database: "mcpmesh"
    username: "mcpmesh"
    password: "mcpmesh123" # Change in production

  persistence:
    enabled: true
    size: 20Gi
    storageClass: "fast-ssd"
```

### Registry Configuration

```yaml
# values.yaml
mcp-mesh-registry:
  registry:
    database:
      type: "postgres"
      host: "mcp-mesh-core-mcp-mesh-postgres"
      port: 5432
      name: "mcpmesh"
      username: "mcpmesh"
      password: "mcpmesh123"

    logging:
      level: "DEBUG"
      format: "json"

  ingress:
    enabled: true
    className: "nginx"
    hosts:
      - host: registry.example.com
        paths:
          - path: /
            pathType: Prefix
```

## Architecture

The core infrastructure follows this deployment pattern:

1. **Namespace** - Creates `mcp-mesh` namespace
2. **PostgreSQL** - StatefulSet with persistent storage
3. **Redis** - Deployment with emptyDir (cache-only)
4. **Registry** - StatefulSet connected to PostgreSQL

## Monitoring

Enable monitoring with:

```yaml
# values.yaml
serviceMonitors:
  enabled: true
```

## Security

Production security recommendations:

```yaml
# values.yaml
mcp-mesh-postgres:
  postgres:
    password: "your-secure-password"

mcp-mesh-registry:
  registry:
    security:
      auth:
        enabled: true
        type: "token"
        tokens:
          - "your-secure-token"
```

## Uninstall

```bash
helm uninstall mcp-mesh-core
```

Note: This will delete all data in PostgreSQL. Back up data before uninstalling.

## Values

| Key                | Type   | Default      | Description                          |
| ------------------ | ------ | ------------ | ------------------------------------ |
| `global.namespace` | string | `"mcp-mesh"` | Namespace for all components         |
| `postgres.enabled` | bool   | `true`       | Enable PostgreSQL deployment         |
| `redis.enabled`    | bool   | `true`       | Enable Redis deployment              |
| `registry.enabled` | bool   | `true`       | Enable Registry deployment           |
| `namespaceCreate`  | bool   | `true`       | Create namespace if it doesn't exist |

See individual component charts for detailed configuration options.
