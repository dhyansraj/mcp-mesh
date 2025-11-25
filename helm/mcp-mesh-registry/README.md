# MCP Mesh Registry Helm Chart

This Helm chart deploys the MCP Mesh Registry service on Kubernetes.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support in the underlying infrastructure (if persistence is enabled)

## Installing the Chart

To install the chart with the release name `mcp-registry`:

```bash
helm install mcp-registry ./helm/mcp-mesh-registry
```

## Uninstalling the Chart

To uninstall the `mcp-registry` deployment:

```bash
helm uninstall mcp-registry
```

## Configuration

The following table lists the configurable parameters of the MCP Mesh Registry chart and their default values.

### General Configuration

| Parameter          | Description                            | Default             |
| ------------------ | -------------------------------------- | ------------------- |
| `replicaCount`     | Number of registry replicas            | `1`                 |
| `image.repository` | Registry image repository              | `mcp-mesh-registry` |
| `image.pullPolicy` | Image pull policy                      | `IfNotPresent`      |
| `image.tag`        | Image tag (overrides chart appVersion) | `""`                |
| `imagePullSecrets` | Docker registry secret names           | `[]`                |
| `nameOverride`     | Override chart name                    | `""`                |
| `fullnameOverride` | Override full name                     | `""`                |

### Service Configuration

| Parameter             | Description         | Default     |
| --------------------- | ------------------- | ----------- |
| `service.type`        | Service type        | `ClusterIP` |
| `service.port`        | Service port        | `8080`      |
| `service.targetPort`  | Target port         | `8080`      |
| `service.annotations` | Service annotations | `{}`        |

### Registry Configuration

| Parameter                          | Description                                       | Default               |
| ---------------------------------- | ------------------------------------------------- | --------------------- |
| `registry.host`                    | Registry host address                             | `"0.0.0.0"`           |
| `registry.port`                    | Registry port                                     | `8080`                |
| `registry.database.type`           | Database type (sqlite, postgres, mysql)           | `"sqlite"`            |
| `registry.database.path`           | SQLite database path                              | `"/data/registry.db"` |
| `registry.database.host`           | External database host                            | `""`                  |
| `registry.database.port`           | External database port                            | `5432`                |
| `registry.database.name`           | Database name                                     | `"mcp_mesh"`          |
| `registry.database.username`       | Database username                                 | `""`                  |
| `registry.database.password`       | Database password                                 | `""`                  |
| `registry.database.existingSecret` | Existing secret for DB credentials                | `""`                  |
| `registry.logging.level`           | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `"INFO"`              |
| `registry.logging.format`          | Log format (json or text)                         | `"json"`              |

### Persistence

| Parameter                   | Description        | Default         |
| --------------------------- | ------------------ | --------------- |
| `persistence.enabled`       | Enable persistence | `true`          |
| `persistence.storageClass`  | Storage class name | `""`            |
| `persistence.accessMode`    | Access mode        | `ReadWriteOnce` |
| `persistence.size`          | Volume size        | `10Gi`          |
| `persistence.existingClaim` | Use existing PVC   | `""`            |
| `persistence.mountPath`     | Mount path         | `/data`         |

### Security

| Parameter                               | Description                      | Default   |
| --------------------------------------- | -------------------------------- | --------- |
| `registry.security.tls.enabled`         | Enable TLS                       | `false`   |
| `registry.security.tls.existingSecret`  | Existing TLS secret              | `""`      |
| `registry.security.auth.enabled`        | Enable authentication            | `false`   |
| `registry.security.auth.type`           | Auth type (token, basic, oauth2) | `"token"` |
| `registry.security.cors.enabled`        | Enable CORS                      | `true`    |
| `registry.security.cors.allowedOrigins` | Allowed origins                  | `["*"]`   |

### Ingress

| Parameter             | Description                 | Default         |
| --------------------- | --------------------------- | --------------- |
| `ingress.enabled`     | Enable ingress              | `false`         |
| `ingress.className`   | Ingress class name          | `""`            |
| `ingress.annotations` | Ingress annotations         | `{}`            |
| `ingress.hosts`       | Ingress hosts configuration | See values.yaml |
| `ingress.tls`         | TLS configuration           | `[]`            |

### Resources

| Parameter                   | Description    | Default |
| --------------------------- | -------------- | ------- |
| `resources.limits.cpu`      | CPU limit      | `500m`  |
| `resources.limits.memory`   | Memory limit   | `512Mi` |
| `resources.requests.cpu`    | CPU request    | `100m`  |
| `resources.requests.memory` | Memory request | `128Mi` |

### Autoscaling

| Parameter                                       | Description               | Default |
| ----------------------------------------------- | ------------------------- | ------- |
| `autoscaling.enabled`                           | Enable HPA                | `false` |
| `autoscaling.minReplicas`                       | Minimum replicas          | `1`     |
| `autoscaling.maxReplicas`                       | Maximum replicas          | `10`    |
| `autoscaling.targetCPUUtilizationPercentage`    | Target CPU utilization    | `80`    |
| `autoscaling.targetMemoryUtilizationPercentage` | Target memory utilization | `80`    |

### Monitoring

| Parameter                      | Description                          | Default |
| ------------------------------ | ------------------------------------ | ------- |
| `serviceMonitor.enabled`       | Create ServiceMonitor for Prometheus | `false` |
| `serviceMonitor.interval`      | Scrape interval                      | `30s`   |
| `serviceMonitor.scrapeTimeout` | Scrape timeout                       | `10s`   |

## Examples

### Using PostgreSQL Database

```yaml
registry:
  database:
    type: postgres
    host: postgres.database.svc.cluster.local
    port: 5432
    name: mcp_registry
    username: mcp_user
    password: supersecret
```

### Using Existing Secret for Database

```yaml
registry:
  database:
    type: postgres
    existingSecret: my-db-secret
    existingSecretUsernameKey: username
    existingSecretPasswordKey: password
```

### Enabling TLS

```yaml
registry:
  security:
    tls:
      enabled: true
      existingSecret: my-tls-secret
```

### Production Configuration

```yaml
replicaCount: 3

persistence:
  enabled: true
  storageClass: fast-ssd
  size: 50Gi

resources:
  limits:
    cpu: 2
    memory: 4Gi
  requests:
    cpu: 500m
    memory: 1Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10

podDisruptionBudget:
  enabled: true
  minAvailable: 2

networkPolicy:
  enabled: true

registry:
  database:
    type: postgres
    host: postgres.database.svc.cluster.local
  security:
    tls:
      enabled: true
    auth:
      enabled: true
      type: token
```

## Upgrading

To upgrade the chart:

```bash
helm upgrade mcp-registry ./helm/mcp-mesh-registry
```

## Troubleshooting

### Registry not starting

Check the pod logs:

```bash
kubectl logs -l app.kubernetes.io/name=mcp-mesh-registry
```

### Database connection issues

Verify database credentials and connectivity:

```bash
kubectl exec -it <pod-name> -- nc -zv <database-host> <database-port>
```

### Persistence issues

Check PVC status:

```bash
kubectl get pvc -l app.kubernetes.io/name=mcp-mesh-registry
```
