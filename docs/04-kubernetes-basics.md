# Kubernetes Deployment

> Deploy MCP Mesh to Kubernetes using Helm charts

## Prerequisites

- Kubernetes cluster (minikube, EKS, GKE, AKS, etc.)
- Helm 3.8+ (for OCI registry support)
- kubectl configured
- meshctl installed

## Quick Start

### 1. Deploy Core Infrastructure

The `mcp-mesh-core` chart deploys registry + PostgreSQL + Redis + Grafana + Tempo:

```bash
# Create namespace
kubectl create namespace mcp-mesh

# Deploy core (OCI registry - no "helm repo add" needed)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh

# Wait for registry
kubectl wait --for=condition=available deployment/mcp-core-mcp-mesh-registry \
  -n mcp-mesh --timeout=120s
```

### 2. Build Your Agent Image

Scaffold creates a Dockerfile and helm-values.yaml:

```bash
# Create agent with deployment files
meshctl scaffold --name my-agent --agent-type tool

cd my-agent
# Edit main.py to implement your tool logic
```

Build the image:

=== "Local (minikube)"

    ```bash
    # Use minikube's Docker daemon
    eval $(minikube docker-env)

    # Build image
    docker build -t my-agent:v1 .
    ```

=== "Cloud (push to registry)"

    ```bash
    # Build for amd64 (if on Mac ARM) and push
    docker buildx build --platform linux/amd64 \
      -t your-registry/my-agent:v1 --push .
    ```

### 3. Deploy Agent with Helm

```bash
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=my-agent \
  --set image.tag=v1
```

For cloud deployments, use your full registry path:

```bash
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/my-agent \
  --set image.tag=v1
```

### 4. Verify

```bash
# Check pods
kubectl get pods -n mcp-mesh

# Port forward and test with meshctl
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
meshctl list
```

## Helm Charts

MCP Mesh charts are hosted on GitHub Container Registry as OCI artifacts:

| Chart                                                | Description                                     |
| ---------------------------------------------------- | ----------------------------------------------- |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core`     | Registry + PostgreSQL + Redis + Grafana + Tempo |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent`    | Deploy individual agents                        |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry` | Registry only (lightweight)                     |

## Customizing Deployments

### Using helm-values.yaml

`meshctl scaffold` generates a `helm-values.yaml` ready for deployment:

```yaml
# my-agent/helm-values.yaml (auto-generated)
image:
  repository: your-registry/my-agent
  tag: latest

agent:
  name: my-agent
  # port: 8080 is default, no need to specify

mesh:
  enabled: true
  registryUrl: http://mcp-core-mcp-mesh-registry:8000

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi
```

### Disable Observability Components

```bash
# Core without Grafana/Tempo (lighter footprint)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh \
  --set grafana.enabled=false \
  --set tempo.enabled=false
```

### Registry Only (Minimal)

```bash
# Just the registry, no database or observability
helm install mcp-registry oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh
```

## Common Operations

```bash
# List Helm releases
helm list -n mcp-mesh

# Upgrade an agent
helm upgrade my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh \
  --set image.tag=v2

# Scale replicas
helm upgrade my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.8.0-beta.5 \
  --namespace mcp-mesh \
  --reuse-values \
  --set replicaCount=3

# Uninstall
helm uninstall my-agent -n mcp-mesh

# View agent logs
kubectl logs -f deployment/my-agent-mcp-mesh-agent -n mcp-mesh
```

## Port Strategy

Port configuration differs between environments:

| Environment            | Port Strategy                | Why                           |
| ---------------------- | ---------------------------- | ----------------------------- |
| Local / docker-compose | Unique ports (9001, 9002...) | Containers share host network |
| Kubernetes             | All agents use 8080          | Each pod has its own IP       |

The Helm chart sets `MCP_MESH_HTTP_PORT=8080` automatically. Your code doesn't need to change.

## Troubleshooting

### Pods not starting

```bash
# Check pod status and events
kubectl get pods -n mcp-mesh
kubectl describe pod <pod-name> -n mcp-mesh

# Check logs
kubectl logs <pod-name> -n mcp-mesh
```

### Registry connection issues

```bash
# Test registry health
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
curl http://localhost:8000/health

# Check DNS from agent pod
kubectl exec -it <agent-pod> -n mcp-mesh -- nslookup mcp-core-mcp-mesh-registry
```

### Image pull errors (minikube)

```bash
# Ensure you're using minikube's Docker
eval $(minikube docker-env)
docker images | grep my-agent

# Set imagePullPolicy if needed
helm upgrade my-agent ... --set image.pullPolicy=Never
```

## Next Steps

- `meshctl man deployment` - Full deployment reference
- `meshctl scaffold --help` - Agent scaffolding options
