# MCP Mesh Core Infrastructure

This umbrella chart deploys the core MCP Mesh infrastructure components:

- **MCP Mesh Registry** - Central service registry and discovery
- **PostgreSQL** - Database for registry data
- **Redis** - Distributed tracing stream
- **Tempo** - Trace collection and storage (observability)
- **Grafana** - Observability dashboard (observability)

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
  enabled: true # Required for distributed tracing

registry:
  enabled: true # Core component, usually always enabled

grafana:
  enabled: true # Set to false to skip observability UI

tempo:
  enabled: true # Set to false to skip trace collection
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
| `grafana.enabled`  | bool   | `true`       | Enable Grafana deployment            |
| `tempo.enabled`    | bool   | `true`       | Enable Tempo deployment              |
| `namespaceCreate`  | bool   | `true`       | Create namespace if it doesn't exist |

## Service Discovery

After installation, agents can connect using these endpoints:

| Service  | Internal URL                      |
| -------- | --------------------------------- |
| Registry | `mcp-core-mcp-mesh-registry:8000` |
| Redis    | `mcp-core-mcp-mesh-redis:6379`    |
| Tempo    | `mcp-core-mcp-mesh-tempo:4317`    |
| Grafana  | `mcp-core-mcp-mesh-grafana:3000`  |

See individual component charts for detailed configuration options.
