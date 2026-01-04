# Helm Deployment

> Deploy MCP Mesh using Helm charts for simplified, repeatable Kubernetes deployments

## Overview

Helm is the package manager for Kubernetes, making it easy to deploy, upgrade, and manage MCP Mesh installations. This section covers using the official MCP Mesh Helm charts, customizing deployments with values files, and managing multi-environment configurations.

With Helm, you can deploy a complete MCP Mesh system with a single command, manage configuration changes declaratively, and easily upgrade or rollback deployments.

## What You'll Learn

By the end of this section, you will:

- ✅ Install and configure Helm for MCP Mesh deployments
- ✅ Deploy the registry and agents using Helm charts
- ✅ Customize deployments with values files
- ✅ Manage multi-environment configurations
- ✅ Perform upgrades and rollbacks
- ✅ Create your own Helm charts for custom agents

## Why Helm for MCP Mesh?

Helm provides significant advantages for MCP Mesh deployments:

1. **Templating**: Reuse configurations across environments
2. **Dependency Management**: Automatically deploy required components
3. **Versioning**: Track and rollback configuration changes
4. **Values Management**: Separate configuration from templates
5. **Hooks**: Automate pre/post deployment tasks
6. **Package Distribution**: Share agents as Helm charts

## MCP Mesh Helm Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Mesh Helm Charts                         │
│                                                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐      │
│  │  mcp-mesh-registry/      │  │  mcp-mesh-agent/         │      │
│  │  ├── Chart.yaml          │  │  ├── Chart.yaml          │      │
│  │  ├── values.yaml         │  │  ├── values.yaml         │      │
│  │  └── templates/          │  │  └── templates/          │      │
│  │      ├── statefulset.yaml│  │      ├── deployment.yaml │      │
│  │      ├── service.yaml    │  │      ├── service.yaml    │      │
│  │      ├── configmap.yaml  │  │      ├── configmap.yaml  │      │
│  │      ├── secret.yaml     │  │      ├── secret.yaml     │      │
│  │      ├── hpa.yaml        │  │      ├── hpa.yaml        │      │
│  │      └── ingress.yaml    │  │      └── ingress.yaml    │      │
│  └─────────────────────────┘  └─────────────────────────┘      │
│                                                                  │
│  Multiple agent instances can be deployed:                       │
│  helm install hello-world ./mcp-mesh-agent --set agent.name=... │
│  helm install system-agent ./mcp-mesh-agent --set agent.name=...│
│  helm install weather-agent ./mcp-mesh-agent --set agent.name...│
└─────────────────────────────────────────────────────────────────┘
```

## Section Contents

1. **[Understanding MCP Mesh Helm Charts](./06-helm-deployment/01-understanding-charts.md)** - Chart structure and components
2. **[Multi-Agent Deployment](./06-helm-deployment/02-umbrella-chart.md)** - Deploy multiple agents with registry
3. **[Customizing Values](./06-helm-deployment/03-customizing-values.md)** - Configuration management
4. **[Multi-Environment Deployment](./06-helm-deployment/04-multi-environment.md)** - Dev, staging, production
5. **[Helm Best Practices](./06-helm-deployment/05-best-practices.md)** - Production-ready deployments
6. **[Troubleshooting](./06-helm-deployment/troubleshooting.md)** - Common issues and solutions

## Quick Start Example

Deploy MCP Mesh with Helm using local charts:

```bash
# From the project root directory
cd helm

# Install the registry first
helm install mcp-registry ./mcp-mesh-registry \
  --namespace mcp-mesh \
  --create-namespace

# Wait for registry to be ready
kubectl wait --for=condition=available deployment/mcp-registry -n mcp-mesh --timeout=300s

# Install an agent
helm install hello-world-agent ./mcp-mesh-agent \
  --namespace mcp-mesh \
  --set agent.name=hello-world-agent \
  --set agent.script=hello_world.py

# Or install multiple agents
helm install system-agent ./mcp-mesh-agent \
  --namespace mcp-mesh \
  --set agent.name=system-agent \
  --set agent.script=system_agent.py
```

## Key Helm Concepts for MCP Mesh

### 1. Values Files

Customize deployments without modifying charts:

```yaml
# registry-production.yaml
replicaCount: 3
persistence:
  enabled: true
  size: 50Gi
  storageClass: "fast-ssd"
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "1000m"

# agent-production.yaml
replicaCount: 5
autoscaling:
  enabled: true
  minReplicas: 5
  maxReplicas: 20
  targetCPUUtilizationPercentage: 80
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### 2. Chart Dependencies

The MCP Mesh charts can optionally include external dependencies:

```yaml
# Chart.yaml for mcp-mesh-registry
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled

  - name: prometheus
    version: "15.x.x"
    repository: "https://prometheus-community.github.io/helm-charts"
    condition: monitoring.prometheus.enabled
```

### 3. Helm Hooks

Automate deployment tasks:

```yaml
# templates/pre-install-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: registry-init
          image: "{% raw %}{{ .Values.image.repository }}{% endraw %}:{% raw %}{{ .Values.image.tag }}{% endraw %}"
          command: ["sh", "-c", "echo 'Initializing MCP Mesh Registry...'"]
      restartPolicy: Never
```

## Best Practices

- 📋 **Use Values Files**: Never edit templates directly
- 🔐 **Manage Secrets**: Use Helm secrets or external secret managers
- 📦 **Version Everything**: Pin chart and image versions
- 🏷️ **Label Consistently**: Use Helm's standard labels
- 📊 **Monitor Releases**: Track deployment history

## Ready to Deploy with Helm?

Start with [Understanding MCP Mesh Helm Charts](./06-helm-deployment/01-understanding-charts.md) →

## 🔧 Troubleshooting

### Common Helm Issues

1. **Release already exists**

   ```bash
   # List releases
   helm list -n mcp-mesh

   # Upgrade existing release
   helm upgrade mcp-registry oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry \
     --version 0.7.18 -n mcp-mesh
   ```

2. **Values not taking effect**

   ```bash
   # Debug with dry-run
   helm install mcp-registry ./mcp-mesh-registry \
     --dry-run --debug \
     -f values.yaml
   ```

3. **Chart dependencies not found**
   ```bash
   # Update dependencies (if any)
   helm dependency update ./mcp-mesh-registry
   helm dependency update ./mcp-mesh-agent
   ```

For detailed solutions, see our [Helm Troubleshooting Guide](./06-helm-deployment/troubleshooting.md).

## ⚠️ Known Limitations

- **CRD Management**: CRDs require special handling in Helm 3
- **Large Releases**: Kubernetes ConfigMap size limits
- **Helm 2 vs 3**: Significant differences in behavior
- **Namespace Handling**: Cross-namespace resources need care

## 📝 TODO

- [ ] Add Helmfile examples for multi-cluster
- [ ] Create Helm operator documentation
- [ ] Add GitOps integration with Flux/ArgoCD
- [ ] Document Helm plugin development
- [ ] Add chart testing automation

---

💡 **Tip**: Use `helm diff` plugin to preview changes before upgrading: `helm plugin install https://github.com/databus23/helm-diff`

📚 **Reference**: [Helm Documentation](https://helm.sh/docs/)

🎯 **Next Step**: Ready to understand the charts? Start with [Understanding MCP Mesh Helm Charts](./06-helm-deployment/01-understanding-charts.md)
