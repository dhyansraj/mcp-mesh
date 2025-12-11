# Multi-Agent Deployment

> Deploy MCP Mesh core infrastructure and agents using Helm charts

## Overview

MCP Mesh provides two types of Helm charts:

1. **`mcp-mesh-core`** - Umbrella chart for core infrastructure (registry, postgres, redis, grafana, tempo)
2. **`mcp-mesh-agent`** - Individual chart for deploying agents (install once per agent)

## Quick Start

### 1. Deploy Core Infrastructure

The `mcp-mesh-core` chart deploys the complete infrastructure stack:

```bash
# Create namespace
kubectl create namespace mcp-mesh

# Deploy core infrastructure (OCI registry - no helm repo add needed)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.1 \
  --namespace mcp-mesh
```

This deploys:

- **Registry** - Service discovery and agent coordination
- **PostgreSQL** - Persistent storage for registry
- **Redis** - Session storage and caching
- **Grafana** - Dashboards and visualization
- **Tempo** - Distributed tracing

### 2. Deploy Agents

Deploy each agent using the `mcp-mesh-agent` chart:

```bash
# Deploy hello-world agent
helm install hello-world oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.1 \
  --namespace mcp-mesh \
  --set agent.name=hello-world \
  --set agent.script=hello_world.py

# Deploy system agent
helm install system-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.1 \
  --namespace mcp-mesh \
  --set agent.name=system-agent \
  --set agent.script=system_agent.py

# Deploy weather agent
helm install weather-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.1 \
  --namespace mcp-mesh \
  --set agent.name=weather-agent \
  --set agent.script=weather_agent.py
```

### 3. Verify Deployment

```bash
# Check all pods
kubectl get pods -n mcp-mesh

# Check registered agents
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
meshctl list
```

## Core Infrastructure Configuration

### Enable/Disable Components

```yaml
# core-values.yaml
postgres:
  enabled: true

redis:
  enabled: true

registry:
  enabled: true

grafana:
  enabled: true # Set false if using external Grafana

tempo:
  enabled: true # Set false if using external tracing
```

### Minimal Setup (Development)

```yaml
# core-minimal.yaml
postgres:
  enabled: false # Use SQLite

redis:
  enabled: false

grafana:
  enabled: false

tempo:
  enabled: false

mcp-mesh-registry:
  registry:
    database:
      type: "sqlite"
```

```bash
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.1 \
  --namespace mcp-mesh \
  -f core-minimal.yaml
```

## Agent Configuration

### Basic Agent Values

```yaml
# my-agent-values.yaml
agent:
  name: my-agent
  script: my_agent.py
  capabilities:
    - data_processing
    - analysis
  dependencies:
    - database_query

image:
  repository: mcpmesh/python-runtime
  tag: "0.7"

resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "512Mi"
    cpu: "200m"
```

```bash
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.1 \
  --namespace mcp-mesh \
  -f my-agent-values.yaml
```

### Agent with Autoscaling

```yaml
# high-traffic-agent.yaml
agent:
  name: api-gateway
  script: api_gateway.py

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

## Common Operations

```bash
# List all releases
helm list -n mcp-mesh

# Upgrade core infrastructure
helm upgrade mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.1 \
  --namespace mcp-mesh \
  -f core-values.yaml

# Scale an agent
helm upgrade weather-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.1 \
  --namespace mcp-mesh \
  --set agent.replicas=3

# Uninstall an agent
helm uninstall weather-agent -n mcp-mesh

# Uninstall everything
helm uninstall mcp-core -n mcp-mesh
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      mcp-mesh-core (umbrella)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Registry   │  │  PostgreSQL │  │    Redis    │  │   Tempo   │ │
│  │   :8000     │  │   :5432     │  │   :6379     │  │   :4317   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────────────┘
         ▲
         │ Register/Discover
         │
┌────────┼────────────────────────────────────────────────────────────┐
│        │            mcp-mesh-agent (per agent)                      │
│  ┌─────┴─────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │
│  │ Agent A   │  │  Agent B  │  │  Agent C  │  │  Agent D  │       │
│  │  :8080    │  │   :8080   │  │   :8080   │  │   :8080   │       │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Registry not ready

```bash
# Check registry pod
kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry

# Check logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry
```

### Agent can't connect to registry

```bash
# Check registry service
kubectl get svc -n mcp-mesh | grep registry

# Test connectivity from agent pod
kubectl exec -it <agent-pod> -n mcp-mesh -- \
  curl http://mcp-core-mcp-mesh-registry:8000/health
```

## Next Steps

- [Customizing Values](./03-customizing-values.md) - Advanced configuration options
- [Multi-Environment](./04-multi-environment.md) - Dev, staging, production setups
