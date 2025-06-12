# Kubernetes Basics

> Deploy MCP Mesh to Kubernetes for production-grade container orchestration

## Overview

Kubernetes provides the ideal platform for running MCP Mesh at scale. This section covers deploying MCP Mesh components to Kubernetes, from local development with Minikube to production-ready configurations. You'll learn about Custom Resource Definitions (CRDs), StatefulSets for the registry, and best practices for agent deployment.

By the end of this section, you'll be able to deploy a complete MCP Mesh system on Kubernetes with high availability, automatic scaling, and proper resource management.

## What You'll Learn

By the end of this section, you will:

- ✅ Set up a local Kubernetes environment with Minikube
- ✅ Deploy the MCP Mesh registry as a StatefulSet
- ✅ Deploy agents using kubectl and manifests
- ✅ Configure service discovery in Kubernetes
- ✅ Implement health checks and resource limits
- ✅ Troubleshoot common Kubernetes deployment issues

## Why Kubernetes for MCP Mesh?

Kubernetes excels at running distributed systems like MCP Mesh:

1. **Orchestration**: Automatic placement and scaling of agents
2. **Service Discovery**: Built-in DNS and service abstractions
3. **Self-Healing**: Automatic restarts and rescheduling
4. **Resource Management**: CPU and memory limits per agent
5. **Configuration Management**: ConfigMaps and Secrets
6. **Rolling Updates**: Zero-downtime deployments

## Kubernetes Architecture for MCP Mesh

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                           │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                        mcp-mesh namespace                     │   │
│  │                                                               │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │   │
│  │  │ Registry         │  │ Weather Agent    │  │ System Agent │ │   │
│  │  │ StatefulSet      │  │ Deployment       │  │ Deployment   │ │   │
│  │  │                  │  │                  │  │              │ │   │
│  │  │ ┌─────────────┐  │  │ ┌─────────────┐  │  │ ┌──────────┐ │ │   │
│  │  │ │ Pod 0       │  │  │ │ Pod 1       │  │  │ │ Pod 1    │ │ │   │
│  │  │ │ Leader      │  │  │ │ Replica     │  │  │ │ Replica  │ │ │   │
│  │  │ └─────────────┘  │  │ └─────────────┘  │  │ └──────────┘ │ │   │
│  │  │ ┌─────────────┐  │  │ ┌─────────────┐  │  │ ┌──────────┐ │ │   │
│  │  │ │ Pod 1       │  │  │ │ Pod 2       │  │  │ │ Pod 2    │ │ │   │
│  │  │ │ Follower    │  │  │ │ Replica     │  │  │ │ Replica  │ │ │   │
│  │  │ └─────────────┘  │  │ └─────────────┘  │  │ └──────────┘ │ │   │
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘ │   │
│  │                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐ │   │
│  │  │                    Services & Ingress                    │ │   │
│  │  │  - mcp-mesh-registry (ClusterIP)                         │ │   │
│  │  │  - weather-agent (ClusterIP)                             │ │   │
│  │  │  - mcp-mesh-ingress (LoadBalancer/NodePort)            │ │   │
│  │  └─────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Section Contents

1. **[Minikube Setup](./04-kubernetes-basics/01-minikube-setup.md)** - Local Kubernetes development
2. **[Local Registry Configuration](./04-kubernetes-basics/02-local-registry.md)** - Deploy registry to K8s
3. **[Deploying with kubectl](./04-kubernetes-basics/03-kubectl-deployment.md)** - Manual deployment process
4. **[Service Discovery in K8s](./04-kubernetes-basics/04-service-discovery.md)** - DNS and service communication
5. **[Troubleshooting K8s Deployments](./04-kubernetes-basics/05-troubleshooting.md)** - Common issues and solutions

## Quick Start Example

Deploy MCP Mesh to Kubernetes in minutes:

```bash
# 1. Start Minikube (or use existing cluster)
minikube start --cpus=4 --memory=8192

# 2. Create namespace
kubectl create namespace mcp-mesh

# 3. Deploy using Kustomize
kubectl apply -k k8s/base/

# 4. Wait for registry to be ready
kubectl wait --for=condition=ready pod -l app=mcp-mesh-registry -n mcp-mesh

# 5. Deploy example agents
kubectl apply -f k8s/examples/hello-world-agent.yaml
kubectl apply -f k8s/examples/system-agent.yaml

# 6. Check deployment status
kubectl get all -n mcp-mesh
```

## Key Kubernetes Concepts for MCP Mesh

### 1. Custom Resource Definitions (CRDs)

MCP Mesh provides a CRD for defining agents:

```yaml
apiVersion: mesh.mcp.io/v1alpha1
kind: MCPAgent
metadata:
  name: weather-agent
  namespace: mcp-mesh
spec:
  script: /app/agents/weather_agent.py
  replicas: 3
  capabilities:
    - name: weather_forecast
      version: "1.0.0"
  dependencies:
    - name: system_time
      version: ">=1.0.0"
```

### 2. StatefulSets for Registry

The registry uses StatefulSet for stable network identity:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry
spec:
  serviceName: mcp-mesh-registry
  replicas: 3
  selector:
    matchLabels:
      app: mcp-mesh-registry
  template:
    spec:
      containers:
        - name: registry
          image: mcp-mesh/registry:latest
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### 3. ConfigMaps and Secrets

Manage configuration separately from code:

```bash
# Create config
kubectl create configmap mcp-agent-config \
  --from-file=config.yaml \
  -n mcp-mesh

# Create secrets
kubectl create secret generic mcp-agent-secrets \
  --from-literal=api-key=secret123 \
  -n mcp-mesh
```

## Best Practices

- 📦 **Use Namespaces**: Isolate MCP Mesh in its own namespace
- 🏷️ **Label Everything**: Consistent labels for resource selection
- 💾 **Persistent Storage**: Use PVCs for stateful components
- 🔒 **RBAC**: Implement proper role-based access control
- 📊 **Resource Limits**: Set requests and limits for all containers

## Ready to Deploy?

Start with [Minikube Setup](./04-kubernetes-basics/01-minikube-setup.md) →

## 🔧 Troubleshooting

### Common Kubernetes Issues

1. **Pods stuck in Pending**

   - Check resource availability: `kubectl describe nodes`
   - Verify PVC binding: `kubectl get pvc -n mcp-mesh`

2. **Service discovery not working**

   - Check DNS: `kubectl exec -it <pod> -- nslookup mcp-mesh-registry`
   - Verify service endpoints: `kubectl get endpoints -n mcp-mesh`

3. **Registry not accessible**
   - Check pod status: `kubectl get pods -n mcp-mesh`
   - View logs: `kubectl logs -f <registry-pod> -n mcp-mesh`

For detailed solutions, see our [Kubernetes Troubleshooting Guide](./04-kubernetes-basics/05-troubleshooting.md).

## ⚠️ Known Limitations

- **Minikube**: Limited resources compared to real clusters
- **Windows**: Some networking features require WSL2
- **ARM64**: Limited support for some container images
- **PersistentVolumes**: Local storage limitations in development

## 📝 TODO

- [ ] Add Helm chart deployment option
- [ ] Document multi-cluster deployment
- [ ] Add service mesh integration guide
- [ ] Create automated testing for K8s deployments
- [ ] Add GPU support documentation

---

💡 **Tip**: Use `kubectl explain` to understand any Kubernetes resource: `kubectl explain deployment.spec`

📚 **Reference**: [Kubernetes Documentation](https://kubernetes.io/docs/)

🎯 **Next Step**: Ready to deploy locally? Start with [Minikube Setup](./04-kubernetes-basics/01-minikube-setup.md)
