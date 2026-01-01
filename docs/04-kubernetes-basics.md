# Kubernetes Deployment

> Deploy MCP Mesh to Kubernetes using Helm charts

## Overview

MCP Mesh provides official Helm charts for Kubernetes deployment. This is the recommended way to deploy to any Kubernetes cluster (minikube, EKS, GKE, AKS, etc.).

## Quick Start

### 1. Set Up Minikube (for local development)

```bash
# Install minikube (macOS)
brew install minikube

# Start cluster
minikube start --cpus=4 --memory=8192

# Verify
kubectl get nodes
```

### 2. Deploy with Helm

MCP Mesh charts are hosted on GitHub Container Registry (ghcr.io) as OCI artifacts.

```bash
# Create namespace
kubectl create namespace mcp-mesh

# Install registry (no "helm repo add" needed with OCI)
helm install mcp-registry oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry \
  --version 0.7.13 \
  --namespace mcp-mesh

# Wait for registry
kubectl wait --for=condition=available deployment/mcp-registry-mcp-mesh-registry \
  -n mcp-mesh --timeout=120s

# Install agents
helm install hello-world oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.13 \
  --namespace mcp-mesh \
  --set agent.name=hello-world \
  --set agent.script=hello_world.py

helm install system-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.13 \
  --namespace mcp-mesh \
  --set agent.name=system-agent \
  --set agent.script=system_agent.py
```

### 3. Verify Deployment

```bash
# Check pods
kubectl get pods -n mcp-mesh

# Check services
kubectl get svc -n mcp-mesh

# Port forward and test
kubectl port-forward -n mcp-mesh svc/mcp-registry-mcp-mesh-registry 8000:8000 &
meshctl list
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   mcp-mesh namespace                        ││
│  │                                                              ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      ││
│  │  │   Registry   │  │ Hello World  │  │ System Agent │      ││
│  │  │   (Helm)     │◄─│   (Helm)     │  │   (Helm)     │      ││
│  │  │   :8000      │  │   :8080      │◄►│   :8080      │      ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘      ││
│  │         ▲                                  │                ││
│  │         └──────────────────────────────────┘                ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Customizing Deployments

Use a values file for custom configuration:

```yaml
# my-agent-values.yaml
agent:
  name: my-custom-agent
  script: my_agent.py
  replicas: 2

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

```bash
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.13 \
  --namespace mcp-mesh \
  -f my-agent-values.yaml
```

## Common Operations

```bash
# List Helm releases
helm list -n mcp-mesh

# Upgrade a release
helm upgrade hello-world oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.7.13 \
  --namespace mcp-mesh \
  --set agent.replicas=3

# Uninstall
helm uninstall hello-world -n mcp-mesh

# View logs
kubectl logs -f deployment/hello-world-mcp-mesh-agent -n mcp-mesh
```

## Troubleshooting

### Pods not starting

```bash
# Check pod status
kubectl get pods -n mcp-mesh

# Check events
kubectl get events -n mcp-mesh --sort-by='.lastTimestamp'

# Check logs
kubectl logs <pod-name> -n mcp-mesh
```

### Registry connection issues

```bash
# Test registry health
kubectl port-forward -n mcp-mesh svc/mcp-registry-mcp-mesh-registry 8000:8000 &
curl http://localhost:8000/health

# Check DNS resolution from agent pod
kubectl exec -it <agent-pod> -n mcp-mesh -- nslookup mcp-registry-mcp-mesh-registry
```

## Next Steps

- [Helm Deployment Guide](06-helm-deployment.md) - Full Helm configuration options
- [Customizing Values](06-helm-deployment/03-customizing-values.md) - Advanced configuration
- [Multi-Environment](06-helm-deployment/04-multi-environment.md) - Dev, staging, production
