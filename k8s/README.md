# MCP Mesh Kubernetes Manifests

This directory contains Kubernetes manifests for deploying MCP Mesh components.

## Directory Structure

```
k8s/
├── base/                    # Base Kustomize configuration
│   ├── namespace.yaml      # MCP Mesh namespace
│   ├── crds/              # Custom Resource Definitions
│   ├── registry/          # Registry manifests
│   └── agents/            # Agent manifests
├── overlays/              # Environment-specific overlays
│   ├── dev/              # Development environment
│   └── prod/             # Production environment
└── README.md             # This file
```

## Quick Start

### Prerequisites

- Kubernetes 1.19+
- kubectl configured to access your cluster
- kustomize (or kubectl with kustomize support)

### Deploy Everything

```bash
# Deploy base configuration
kubectl apply -k k8s/base/

# Or deploy with environment-specific overlay
kubectl apply -k k8s/overlays/dev/
```

### Deploy Components Separately

```bash
# 1. Create namespace
kubectl apply -f k8s/base/namespace.yaml

# 2. Install CRDs
kubectl apply -f k8s/base/crds/

# 3. Deploy Registry
kubectl apply -f k8s/base/registry/

# 4. Deploy Agents
kubectl apply -f k8s/base/agents/
```

## Components

### Custom Resource Definitions (CRDs)

- **MCPAgent**: Defines MCP agents with their capabilities, dependencies, and deployment configuration

### Registry

The registry is deployed as a StatefulSet with:

- 3 replicas for high availability
- Persistent storage for each replica
- Leader election for coordination
- Automated backups via CronJob

### Agents

Agents can be deployed either as:

1. Standard Deployments using YAML manifests
2. MCPAgent custom resources (recommended)

## Configuration

### ConfigMaps

- `mcp-registry-config`: Registry configuration
- `mcp-agent-config`: Agent configuration templates
- `mcp-agent-code`: Sample agent Python code

### Secrets

- `mcp-registry-secret`: Database credentials and auth tokens
- `mcp-agent-secret`: API keys and service credentials

### Persistent Volumes

- Registry data (StatefulSet volume claims)
- Registry backups
- Agent workspaces
- Shared cache

## Using the MCPAgent CRD

### Basic Example

```yaml
apiVersion: mesh.mcp.io/v1alpha1
kind: MCPAgent
metadata:
  name: hello-world
  namespace: mcp-mesh
spec:
  script: /app/agents/hello_world.py
  replicas: 2
  capabilities:
    - name: greeting
      version: "1.0.0"
```

### Advanced Example

```yaml
apiVersion: mesh.mcp.io/v1alpha1
kind: MCPAgent
metadata:
  name: data-processor
  namespace: mcp-mesh
spec:
  scriptConfigMap: data-processor-code
  replicas: 3
  capabilities:
    - name: data_transformation
      version: "2.0.0"
  dependencies:
    - name: database-service
      version: ">=3.0.0"
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
```

## Monitoring

### Prometheus Metrics

All components expose Prometheus metrics:

- Registry: `http://mcp-mesh-registry:9090/metrics`
- Agents: `http://<agent-service>:8080/metrics`

### Health Checks

- `/health` - Basic health check
- `/ready` - Readiness check
- `/livez` - Liveness check

## Backup and Recovery

### Registry Backups

Automated backups run daily at 2 AM:

```bash
# Check backup status
kubectl get cronjobs -n mcp-mesh

# List backups
kubectl exec -n mcp-mesh -it <registry-pod> -- ls -la /backup/

# Restore from backup
kubectl exec -n mcp-mesh -it <registry-pod> -- \
  sqlite3 /data/registry.db ".restore /backup/20240106-020000/registry.db"
```

### Manual Backup

```bash
# Create manual backup
kubectl create job --from=cronjob/mcp-mesh-registry-backup \
  mcp-mesh-registry-backup-manual -n mcp-mesh
```

## Scaling

### Registry Scaling

```bash
# Scale registry replicas
kubectl scale statefulset mcp-mesh-registry -n mcp-mesh --replicas=5
```

### Agent Scaling

```bash
# Scale agent deployment
kubectl scale deployment <agent-name> -n mcp-mesh --replicas=10

# Or update MCPAgent resource
kubectl patch mcpagent <agent-name> -n mcp-mesh \
  --type merge -p '{"spec":{"replicas":10}}'
```

## Troubleshooting

### Check Component Status

```bash
# Registry status
kubectl get statefulset,pods,svc -n mcp-mesh -l app.kubernetes.io/component=registry

# Agent status
kubectl get mcpagents,pods,svc -n mcp-mesh -l app.kubernetes.io/component=agent

# View logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=<agent-name>
```

### Common Issues

1. **Registry not starting**: Check database connection and credentials
2. **Agents not registering**: Verify registry URL and network connectivity
3. **PVC issues**: Ensure storage class exists and has available capacity

## Security Considerations

1. **Network Policies**: Enable NetworkPolicies for zero-trust networking
2. **Pod Security**: Uses non-root containers with minimal privileges
3. **Secrets**: Store sensitive data in Kubernetes Secrets
4. **TLS**: Enable TLS for production deployments

## Production Recommendations

1. Use external database (PostgreSQL) for registry
2. Enable TLS for all communications
3. Set up monitoring with Prometheus/Grafana
4. Configure resource limits and requests
5. Use anti-affinity rules for high availability
6. Enable network policies
7. Regular backup schedule
8. Use dedicated nodes with appropriate taints/tolerations
