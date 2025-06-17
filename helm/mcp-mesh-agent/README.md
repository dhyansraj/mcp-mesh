# MCP Mesh Agent Helm Chart

This Helm chart deploys MCP Mesh agents with Python runtime on Kubernetes.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- MCP Mesh Registry deployed and accessible
- Python-based MCP agent script

## Installing the Chart

To install the chart with the release name `my-agent`:

```bash
helm install my-agent ./helm/mcp-mesh-agent \
  --set agent.script=/app/agents/hello_world.py \
  --set registry.url=http://mcp-mesh-registry:8080
```

## Uninstalling the Chart

To uninstall the `my-agent` deployment:

```bash
helm uninstall my-agent
```

## Configuration

The following table lists the configurable parameters of the MCP Mesh Agent chart and their default values.

### Required Parameters

| Parameter      | Description                          | Default                           |
| -------------- | ------------------------------------ | --------------------------------- |
| `agent.script` | Python script path to run (REQUIRED) | `""`                              |
| `registry.url` | MCP Mesh Registry URL                | `"http://mcp-mesh-registry:8080"` |

### Agent Configuration

| Parameter                        | Description                         | Default   |
| -------------------------------- | ----------------------------------- | --------- |
| `agent.name`                     | Agent name (uses pod name if empty) | `""`      |
| `agent.version`                  | Agent version                       | `"1.0.0"` |
| `agent.description`              | Agent description                   | `""`      |
| `agent.capabilities`             | List of capabilities provided       | `[]`      |
| `agent.dependencies`             | List of required dependencies       | `[]`      |
| `agent.healthCheck.enabled`      | Enable health checks                | `true`    |
| `agent.healthCheck.interval`     | Health check interval (seconds)     | `30`      |
| `agent.retry.attempts`           | Retry attempts                      | `3`       |
| `agent.retry.delay`              | Retry delay (seconds)               | `5`       |
| `agent.performance.timeout`      | Operation timeout (seconds)         | `30`      |
| `agent.performance.cacheEnabled` | Enable caching                      | `true`    |

### HTTP Configuration

| Parameter                 | Description                 | Default     |
| ------------------------- | --------------------------- | ----------- |
| `agent.http.enabled`      | Enable HTTP wrapper         | `true`      |
| `agent.http.host`         | HTTP host                   | `"0.0.0.0"` |
| `agent.http.port`         | HTTP port (0 = auto-assign) | `0`         |
| `agent.http.cors.enabled` | Enable CORS                 | `true`      |
| `agent.http.cors.origins` | CORS allowed origins        | `["*"]`     |

### Python Configuration

| Parameter                  | Description                               | Default |
| -------------------------- | ----------------------------------------- | ------- |
| `agent.python.interpreter` | Python interpreter (auto-detect if empty) | `""`    |
| `agent.python.packages`    | Additional Python packages                | `[]`    |
| `agent.python.env`         | Python environment variables              | `[]`    |

### Mesh Configuration

| Parameter             | Description                    | Default  |
| --------------------- | ------------------------------ | -------- |
| `mesh.enabled`        | Enable mesh features           | `true`   |
| `mesh.debug`          | Debug mode                     | `false`  |
| `mesh.logLevel`       | Log level                      | `"INFO"` |
| `mesh.tracingEnabled` | Enable distributed tracing     | `false`  |
| `mesh.metricsEnabled` | Enable metrics collection      | `true`   |
| `mesh.decorators`     | Custom decorator configuration | `{}`     |

### Deployment Configuration

| Parameter                   | Description                            | Default          |
| --------------------------- | -------------------------------------- | ---------------- |
| `replicaCount`              | Number of replicas                     | `1`              |
| `image.repository`          | Container image repository             | `mcp-mesh-agent` |
| `image.pullPolicy`          | Image pull policy                      | `IfNotPresent`   |
| `image.tag`                 | Image tag (overrides chart appVersion) | `""`             |
| `resources.limits.cpu`      | CPU limit                              | `1`              |
| `resources.limits.memory`   | Memory limit                           | `1Gi`            |
| `resources.requests.cpu`    | CPU request                            | `100m`           |
| `resources.requests.memory` | Memory request                         | `256Mi`          |

## Examples

### Basic Agent Deployment

```yaml
# values.yaml
agent:
  script: /app/agents/hello_world.py
  name: hello-world-agent
  capabilities:
    - name: greeting
      version: "1.0.0"
      description: "Provides greeting functionality"

registry:
  url: http://mcp-mesh-registry:8080
```

### Agent with Dependencies

```yaml
agent:
  script: /app/agents/translator.py
  name: translator-agent
  capabilities:
    - name: translation
      version: "1.0.0"
  dependencies:
    - name: dictionary-service
      version: ">=1.0.0"
      optional: false

mesh:
  decorators:
    mesh_agent:
      enable_http: true
      health_interval: 30
      fallback_mode: true
```

### Agent with Custom Python Packages

```yaml
agent:
  script: /app/agents/data_processor.py
  python:
    packages:
      - numpy==1.24.0
      - pandas>=1.5.0
      - scikit-learn==1.3.0
    env:
      - name: PYTHONPATH
        value: "/app/lib"
```

### Production Configuration

```yaml
replicaCount: 3

agent:
  script: /app/agents/production_agent.py
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

persistence:
  enabled: true
  size: 10Gi
```

### Using ConfigMap for Agent Code

```yaml
agentCode:
  enabled: true
  configMapName: my-agent-code
  mountPath: /app/agent

agent:
  script: /app/agent/main.py
```

Create the ConfigMap separately:

```bash
kubectl create configmap my-agent-code \
  --from-file=main.py=./my_agent.py \
  --from-file=utils.py=./utils.py
```

### With Secrets

```yaml
secrets:
  API_KEY: "your-api-key"
  DATABASE_PASSWORD: "your-password"

# Or use existing secret
existingSecret: my-secret
```

## Decorators and Metadata

The chart supports MCP Mesh decorators through the `mesh.decorators` configuration:

```yaml
mesh:
  decorators:
    mesh_agent:
      enable_http: true
      health_interval: 30
      timeout: 60
      retry_attempts: 5
      enable_caching: true
      fallback_mode: true
      performance_profile:
        max_concurrent: 10
        queue_size: 100
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
kubectl logs -l app.kubernetes.io/name=mcp-mesh-agent
```

### Registry connection issues

Verify registry is accessible:

```bash
kubectl exec -it <pod-name> -- curl http://mcp-mesh-registry:8080/health
```

### Python package installation

Check init container logs if using custom packages:

```bash
kubectl logs <pod-name> -c init-packages
```

## Advanced Usage

### Multi-Environment Deployment

Deploy the same agent to multiple environments:

```bash
# Development
helm install dev-agent ./helm/mcp-mesh-agent -f values-dev.yaml

# Staging
helm install staging-agent ./helm/mcp-mesh-agent -f values-staging.yaml

# Production
helm install prod-agent ./helm/mcp-mesh-agent -f values-prod.yaml
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
        agent:
          script: /app/agents/my_agent.py
        registry:
          url: http://mcp-mesh-registry:8080
```
