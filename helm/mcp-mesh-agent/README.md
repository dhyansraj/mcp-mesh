# MCP Mesh Agent Helm Chart

This Helm chart deploys MCP Mesh agents on Kubernetes. It supports Python, TypeScript, and Java runtimes.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- MCP Mesh Registry deployed and accessible
- An MCP agent packaged as a Docker image

## Quick Start

### Python Agent

```bash
helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-python-agent \
  --set image.tag=v1.0.0 \
  --set agent.name=my-agent
```

Default image is `mcpmesh/python-runtime` — Python-specific env vars (`PYTHONUNBUFFERED`, `PYTHONPATH`, `UVICORN_*`) are auto-injected when the runtime is detected as Python (see [Runtime Detection](#runtime-detection)).

### TypeScript Agent

```bash
helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-ts-agent \
  --set image.tag=v1.0.0 \
  --set agent.name=my-agent
```

### Java Agent

```bash
helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-java-agent \
  --set image.tag=v1.0.0 \
  --set agent.name=my-agent
```

### Using a Values File

```bash
helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh -f my-values.yaml
```

## Uninstalling the Chart

```bash
helm uninstall my-agent -n mcp-mesh
```

## Configuration

### Key Parameters

| Parameter          | Description                                         | Default                        |
| ------------------ | --------------------------------------------------- | ------------------------------ |
| `image.repository` | Container image repository                          | `"mcpmesh/python-runtime"`     |
| `image.tag`        | Image tag (overrides chart appVersion)              | `"0.9"`                        |
| `agent.name`       | Agent name for registry                             | `""`                           |
| `agent.command`    | Container command override (empty = use Docker CMD) | `[]`                           |
| `registry.host`    | MCP Mesh Registry host                              | `"mcp-core-mcp-mesh-registry"` |
| `registry.port`    | MCP Mesh Registry port                              | `"8000"`                       |

### Agent Configuration

| Parameter                   | Description                                       | Default   |
| --------------------------- | ------------------------------------------------- | --------- |
| `agent.name`                | Agent name override (empty = use from decorator)  | `""`      |
| `agent.runtime`             | Runtime override (empty = auto-detect from image) | `""`      |
| `agent.version`             | Agent version                                     | `"1.0.0"` |
| `agent.description`         | Agent description                                 | `""`      |
| `agent.capabilities`        | List of capabilities provided                     | `[]`      |
| `agent.dependencies`        | List of required dependencies                     | `[]`      |
| `agent.healthCheck.enabled` | Enable health checks                              | `true`    |
| `agent.command`             | Container command override                        | `[]`      |
| `agent.advertisedHost`      | Hostname advertised to registry                   | `""`      |

### HTTP Configuration

| Parameter                 | Description          | Default     |
| ------------------------- | -------------------- | ----------- |
| `agent.http.enabled`      | Enable HTTP wrapper  | `true`      |
| `agent.http.host`         | HTTP host            | `"0.0.0.0"` |
| `agent.http.port`         | HTTP port            | `8080`      |
| `agent.http.cors.enabled` | Enable CORS          | `true`      |
| `agent.http.cors.origins` | CORS allowed origins | `["*"]`     |

### Mesh Configuration

| Parameter       | Description          | Default  |
| --------------- | -------------------- | -------- |
| `mesh.enabled`  | Enable mesh features | `true`   |
| `mesh.debug`    | Debug mode           | `false`  |
| `mesh.logLevel` | Log level            | `"INFO"` |

### Deployment Configuration

| Parameter                   | Description                            | Default                    |
| --------------------------- | -------------------------------------- | -------------------------- |
| `replicaCount`              | Number of replicas                     | `1`                        |
| `image.repository`          | Container image repository             | `"mcpmesh/python-runtime"` |
| `image.pullPolicy`          | Image pull policy                      | `IfNotPresent`             |
| `image.tag`                 | Image tag (overrides chart appVersion) | `"0.9"`                    |
| `resources.limits.cpu`      | CPU limit                              | `1`                        |
| `resources.limits.memory`   | Memory limit                           | `1Gi`                      |
| `resources.requests.cpu`    | CPU request                            | `100m`                     |
| `resources.requests.memory` | Memory request                         | `256Mi`                    |

### Agent Code Configuration

| Parameter                 | Description                               | Default        |
| ------------------------- | ----------------------------------------- | -------------- |
| `agentCode.enabled`       | Enable mounting agent code from ConfigMap | `false`        |
| `agentCode.configMapName` | External ConfigMap name                   | `""`           |
| `agentCode.scriptPath`    | Script path for auto-generated ConfigMap  | `""`           |
| `agentCode.mountPath`     | Mount path for agent code                 | `"/app/agent"` |

## Runtime Detection

The chart detects the runtime in two ways:

1. **Explicit**: Set `agent.runtime` to `"python"`, `"typescript"`, or `"java"`
2. **Auto-detect**: If `agent.runtime` is empty, checks if `image.repository` contains "python"

When Python runtime is detected:

- `PYTHONUNBUFFERED`, `PYTHONPATH`, and `UVICORN_*` env vars are injected
- Non-Python runtimes (TypeScript, Java, other) get no Python-specific env vars

Scaffold-generated `helm-values.yaml` files set `agent.runtime` explicitly, so auto-detection is mainly for manual deployments using the default `mcpmesh/python-runtime` image.

## Examples

### Python Agent with Custom Packages

```yaml
# values.yaml
image:
  repository: myregistry/my-python-agent
  tag: v1.0.0

agent:
  name: data-processor

env:
  - name: PYTHONPATH
    value: "/app/lib"
```

### TypeScript Agent

```yaml
# values.yaml
image:
  repository: myregistry/my-ts-agent
  tag: v1.0.0

agent:
  name: ts-greeter
```

### Java Agent

```yaml
# values.yaml
image:
  repository: myregistry/my-java-agent
  tag: v1.0.0

agent:
  name: java-greeter
```

### Production Configuration

```yaml
replicaCount: 3

image:
  repository: myregistry/my-agent
  tag: v1.0.0

agent:
  name: production-agent
  healthCheck:
    interval: 15
  performance:
    timeout: 60
    maxConcurrent: 20

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
  targetCPUUtilizationPercentage: 70

podDisruptionBudget:
  enabled: true
  minAvailable: 2

networkPolicy:
  enabled: true
```

### With Secrets

```yaml
secrets:
  API_KEY: "your-api-key"
  DATABASE_PASSWORD: "your-password"

# Or use existing secret
existingSecret: my-secret
```

## Building Custom Agent Images

### Python

```dockerfile
FROM mcpmesh/python-runtime:0.9

COPY . /app/
CMD ["-m", "myagent"]
```

### TypeScript

```dockerfile
FROM mcpmesh/typescript-runtime:0.9

COPY . /app/
CMD ["src/index.ts"]
```

### Java

```dockerfile
FROM mcpmesh/java-runtime:0.9

COPY target/myagent.jar /app/
CMD ["/app/myagent.jar"]
```

Build and deploy:

```bash
docker build -t myregistry/my-agent:v1.0.0 .
docker push myregistry/my-agent:v1.0.0

helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-agent \
  --set image.tag=v1.0.0 \
  --set agent.name=my-agent
```

## Monitoring

Enable Prometheus monitoring:

```yaml
serviceMonitor:
  enabled: true
  interval: 30s
  labels:
    prometheus: kube-prometheus

mesh:
  metricsEnabled: true
```

## Troubleshooting

### Agent not starting

Check pod logs:

```bash
kubectl logs -l app.kubernetes.io/name=mcp-mesh-agent -n mcp-mesh
```

### Registry connection issues

Verify registry is accessible:

```bash
kubectl exec -it <pod-name> -n mcp-mesh -- curl http://mcp-core-mcp-mesh-registry:8000/health
```

## Advanced Usage

### Multi-Environment Deployment

```bash
# Development
helm install dev-agent ./helm/mcp-mesh-agent -n mcp-mesh -f values-dev.yaml

# Staging
helm install staging-agent ./helm/mcp-mesh-agent -n mcp-mesh -f values-staging.yaml

# Production
helm install prod-agent ./helm/mcp-mesh-agent -n mcp-mesh -f values-prod.yaml
```

### GitOps Integration

Example ArgoCD Application:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mcp-agent
spec:
  source:
    repoURL: https://github.com/dhyansraj/mcp-mesh
    targetRevision: main
    path: helm/mcp-mesh-agent
    helm:
      values: |
        image:
          repository: myregistry/my-agent
          tag: v1.0.0
        agent:
          name: my-agent
```
