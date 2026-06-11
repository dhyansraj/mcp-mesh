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

Datastore endpoints and credentials are declared once under `global.*` and
inherited by every consumer: the registry, the UI (when enabled), and the
bundled PostgreSQL provisioning. Per-subchart values (e.g.
`mcp-mesh-registry.registry.database.host`) override the global for that
component only.

```yaml
# values.yaml
global:
  postgres:
    name: "mcpmesh"
    username: "mcpmesh"
    password: "change-me" # Change in production

mcp-mesh-postgres:
  persistence:
    enabled: true
    size: 20Gi
    storageClass: "fast-ssd"
```

### External managed datastores

To use a managed PostgreSQL/Redis (RDS, Cloud SQL, ElastiCache, ...), disable
the bundled subcharts and point `global.*` at the managed endpoints — every
consumer inherits them, no per-subchart overrides needed.

Disabling the bundled subcharts (`postgres.enabled: false`,
`redis.enabled: false`) is required, not optional: leaving them enabled
alongside external credentials fails at template time, because the bundled
Redis runs without AUTH and the bundled PostgreSQL provisions with the inline
password — `global.redis.password` / `global.redis.existingSecret` /
`global.postgres.existingSecret` could never work against them.

```yaml
# values.yaml
postgres:
  enabled: false
redis:
  enabled: false

global:
  postgres:
    host: "mydb.abc123.us-east-1.rds.amazonaws.com"
    port: 5432
    name: "mcpmesh"
    username: "mcpmesh"
    sslmode: "require"
    # Credential from an existing secret: either a key holding a full
    # postgres:// DSN (existingSecretUrlKey) or just the password
    existingSecret: "pg-credentials"
    existingSecretPasswordKey: "password"
  redis:
    host: "myredis.abc123.cache.amazonaws.com"
    port: 6379
    tls:
      enabled: true # rediss://
    existingSecret: "redis-credentials"
    existingSecretPasswordKey: "redis-password"
```

```bash
helm install mcp-core ./mcp-mesh-core -n mcp-mesh -f values.yaml
```

The separate `mcp-mesh-agent` chart is standalone (not an umbrella subchart),
so Helm does not propagate these globals to it automatically — pass the same
`global.redis` values (e.g. the same values file) to each agent release to
point its trace publishing at the managed Redis.

### Registry Configuration

```yaml
# values.yaml
mcp-mesh-registry:
  registry:
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
| `global.postgres.*` | object | bundled postgres | PostgreSQL endpoint/credentials inherited by all consumers (`host`, `port`, `name`, `username`, `password`, `sslmode`, `existingSecret`, `existingSecretUrlKey`, `existingSecretPasswordKey`, `tls.caSecret`, `tls.caKey`) |
| `global.redis.*`   | object | bundled redis | Redis endpoint/credentials inherited by all consumers (`host`, `port`, `password`, `existingSecret`, `existingSecretUrlKey`, `existingSecretPasswordKey`, `tls.enabled`) |
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
