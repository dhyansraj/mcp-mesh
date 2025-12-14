# MCP Mesh Helm Charts

Kubernetes deployment charts for MCP Mesh - a distributed agent orchestration framework.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      mcp-mesh-core                          │
│  ┌──────────┐ ┌───────┐ ┌──────────┐ ┌───────┐ ┌─────────┐  │
│  │ Registry │ │ Redis │ │ Postgres │ │ Tempo │ │ Grafana │  │
│  └──────────┘ └───────┘ └──────────┘ └───────┘ └─────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │  Agent   │    │  Agent   │    │  Agent   │
        │ (hello)  │    │ (system) │    │ (avatar) │
        └──────────┘    └──────────┘    └──────────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    ┌─────────────────┐
                    │ mcp-mesh-ingress│
                    └─────────────────┘
```

## Quick Start

### Prerequisites

- Kubernetes 1.21+
- Helm 3.8+

### Installation

```bash
# Create namespace
kubectl create namespace mcp-mesh

# 1. Install core infrastructure (registry + observability)
helm dependency update helm/mcp-mesh-core
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh

# 2. Install agents (repeat for each agent)
helm install hello-world helm/mcp-mesh-agent -n mcp-mesh \
  --set agent.name=hello-world \
  --set agent.command='["/app/agent.py"]'

# 3. (Optional) Install ingress for external access
helm install mcp-ingress helm/mcp-mesh-ingress -n mcp-mesh
```

## Charts

| Chart                                   | Description                                 | Documentation                          |
| --------------------------------------- | ------------------------------------------- | -------------------------------------- |
| [mcp-mesh-core](./mcp-mesh-core/)       | Registry, PostgreSQL, Redis, Grafana, Tempo | [README](./mcp-mesh-core/README.md)    |
| [mcp-mesh-agent](./mcp-mesh-agent/)     | Deploy MCP agents                           | [README](./mcp-mesh-agent/README.md)   |
| [mcp-mesh-ingress](./mcp-mesh-ingress/) | Ingress routing for services                | [README](./mcp-mesh-ingress/README.md) |

## Configuration

### Disable Optional Components

```bash
# Core without observability
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh \
  --set grafana.enabled=false \
  --set tempo.enabled=false

# Core without PostgreSQL (in-memory registry)
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh \
  --set postgres.enabled=false
```

### Custom Agent Images

```bash
# Multi-file agent with custom Docker image
helm install my-agent helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-agent \
  --set image.tag=v1.0.0 \
  --set agent.name=my-agent \
  --set agent.script=""
```

## Verify Installation

```bash
# Check all pods are running
kubectl get pods -n mcp-mesh

# Test registry health
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
curl http://localhost:8000/health

# List registered agents
curl http://localhost:8000/agents
```

## Uninstall

```bash
helm uninstall mcp-ingress -n mcp-mesh
helm uninstall hello-world -n mcp-mesh
helm uninstall mcp-core -n mcp-mesh
kubectl delete namespace mcp-mesh
```

## Service Discovery

Agents auto-register with the registry using these default endpoints:

| Service  | Internal URL                      |
| -------- | --------------------------------- |
| Registry | `mcp-core-mcp-mesh-registry:8000` |
| Redis    | `mcp-core-mcp-mesh-redis:6379`    |
| Tempo    | `mcp-core-mcp-mesh-tempo:4317`    |
| Grafana  | `mcp-core-mcp-mesh-grafana:3000`  |
