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

# 2. Deploy base infrastructure (registry + database)
kubectl apply -k k8s/base/

# 3. Wait for registry to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mcp-mesh-registry -n mcp-mesh --timeout=300s

# 4. Add agents using examples (optional)
# Create agent code ConfigMap from examples
kubectl create configmap agent-code-examples \
  --from-file=hello_world.py=examples/simple/hello_world.py \
  --from-file=system_agent.py=examples/simple/system_agent.py \
  -n mcp-mesh

# Copy and deploy agent templates
cp k8s/base/agents/example-hello-world-deployment.yaml.template hello-world-deployment.yaml
cp k8s/base/agents/example-system-agent-deployment.yaml.template system-agent-deployment.yaml
kubectl apply -f hello-world-deployment.yaml
kubectl apply -f system-agent-deployment.yaml

# 5. Check deployment status
kubectl get all -n mcp-mesh

# 6. Test connectivity (port forward and test)
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 &
./bin/meshctl list agents
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

The registry uses StatefulSet for stable network identity and persistent storage. Based on the actual K8s examples:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
  labels:
    app.kubernetes.io/name: mcp-mesh-registry
    app.kubernetes.io/component: registry
spec:
  serviceName: mcp-mesh-registry-headless
  replicas: 1 # Can be scaled for HA
  selector:
    matchLabels:
      app.kubernetes.io/name: mcp-mesh-registry
      app.kubernetes.io/component: registry
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mcp-mesh-registry
        app.kubernetes.io/component: registry
    spec:
      serviceAccountName: mcp-mesh-registry
      containers:
        - name: registry
          image: mcp-mesh-base:latest
          ports:
            - name: http
              containerPort: 8000 # Registry uses port 8000
            - name: metrics
              containerPort: 9090
          env:
            # Registry connection - configurable for federated networks
            - name: MCP_MESH_REGISTRY_HOST
              valueFrom:
                configMapKeyRef:
                  name: mcp-agent-config
                  key: REGISTRY_HOST
            - name: MCP_MESH_REGISTRY_PORT
              valueFrom:
                configMapKeyRef:
                  name: mcp-agent-config
                  key: REGISTRY_PORT
            # 🎯 Kubernetes service discovery - auto-detect from labels
            - name: SERVICE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.labels['app.kubernetes.io/name']
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: DATABASE_TYPE
              value: "postgres" # Or sqlite for simple deployments
            - name: DATABASE_HOST
              value: "mcp-mesh-postgres"
          envFrom:
            - configMapRef:
                name: mcp-agent-config
          volumeMounts:
            - name: data
              mountPath: /data
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
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

Manage configuration separately from code. Based on actual K8s examples:

```yaml
# mcp-agent-config ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-agent-config
  namespace: mcp-mesh
data:
  REGISTRY_HOST: "mcp-mesh-registry" # Service name for registry
  REGISTRY_PORT: "8000" # Registry service port
  MCP_MESH_REGISTRY_URL: "http://mcp-mesh-registry:8000"
  LOG_LEVEL: "info"
  HEALTH_CHECK_INTERVAL: "30s"
```

Create configuration using kubectl:

```bash
# Create config from YAML
kubectl apply -f mcp-agent-config.yaml

# Create secrets for sensitive data
kubectl create secret generic mcp-agent-secrets \
  --from-literal=api-key=secret123 \
  --from-literal=auth-token=dev-token-change-in-production \
  -n mcp-mesh

# Create agent code ConfigMap from examples
kubectl create configmap agent-code-examples \
  --from-file=hello_world.py=examples/simple/hello_world.py \
  --from-file=system_agent.py=examples/simple/system_agent.py \
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

### Quick Diagnostic Commands

Run this comprehensive diagnostic script to identify issues:

```bash
#!/bin/bash
# mcp-mesh-k8s-diagnostics.sh
NAMESPACE=${1:-mcp-mesh}

echo "MCP Mesh Kubernetes Diagnostics for namespace: $NAMESPACE"
echo "======================================================="

# Check namespace and pods
kubectl get namespace $NAMESPACE
kubectl get pods -n $NAMESPACE -o wide
kubectl get pods -n $NAMESPACE --field-selector=status.phase!=Running,status.phase!=Succeeded

# Check services and registry
kubectl get svc,endpoints -n $NAMESPACE
kubectl get statefulset,pod,svc -n $NAMESPACE -l app.kubernetes.io/name=mcp-mesh-registry

# Check recent events and resource usage
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20
kubectl top nodes
kubectl top pods -n $NAMESPACE
```

### Common Issues

1. **Pods stuck in Pending**

   - Check resource availability: `kubectl describe nodes`
   - Verify PVC binding: `kubectl get pvc -n mcp-mesh`
   - Check storage classes: `kubectl get storageclass`

2. **Service discovery not working**

   - Test DNS: `kubectl exec -it <pod> -- nslookup mcp-mesh-registry`
   - Check service endpoints: `kubectl get endpoints -n mcp-mesh`
   - Verify labels match: `kubectl get pods --show-labels -n mcp-mesh`

3. **Registry connection failures**

   - Check registry status: `kubectl get pods -l app.kubernetes.io/name=mcp-mesh-registry -n mcp-mesh`
   - View registry logs: `kubectl logs -f mcp-mesh-registry-0 -n mcp-mesh`
   - Test registry health: `kubectl port-forward svc/mcp-mesh-registry 8000:8000 && curl localhost:8000/health`

4. **Pods in CrashLoopBackOff**
   - Check logs: `kubectl logs <pod-name> -n mcp-mesh --previous`
   - Check environment variables: `kubectl exec <pod-name> -n mcp-mesh -- env`
   - Verify ConfigMap/Secret exists: `kubectl get configmap,secret -n mcp-mesh`

For comprehensive troubleshooting, see [Troubleshooting K8s Deployments](./04-kubernetes-basics/05-troubleshooting.md).

## ⚠️ Known Limitations

- **Minikube**: Limited resources compared to real clusters
- **Windows**: Some networking features require WSL2
- **ARM64**: Limited support for some container images
- **PersistentVolumes**: Local storage limitations in development

## Key Kubernetes Patterns for MCP Mesh

### Service Naming and Auto-Detection

Based on the actual K8s examples, MCP Mesh follows these critical patterns:

- **Service Names**: `mcp-mesh-registry` (port 8000), `mcp-mesh-hello-world` (port 8080), `mcp-mesh-system-agent` (port 8080)
- **Label Matching**: Service name MUST exactly match `app.kubernetes.io/name` label value for auto-detection
- **Environment Injection**: `SERVICE_NAME` and `NAMESPACE` auto-detected from pod metadata
- **ConfigMap-based Registry Config**: Registry host/port configurable via `mcp-agent-config`

### Essential Environment Variables

```yaml
env:
  # 🎯 Kubernetes service discovery - auto-detect from labels
  - name: SERVICE_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['app.kubernetes.io/name']
  - name: NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # Registry connection - configurable for federated networks
  - name: MCP_MESH_REGISTRY_HOST
    valueFrom:
      configMapKeyRef:
        name: mcp-agent-config
        key: REGISTRY_HOST
  - name: MCP_MESH_REGISTRY_PORT
    valueFrom:
      configMapKeyRef:
        name: mcp-agent-config
        key: REGISTRY_PORT
```

## 📝 TODO

- [ ] Add Helm chart deployment option (see Helm deployment guide)
- [ ] Document multi-cluster deployment patterns
- [ ] Add service mesh integration guide (Istio/Linkerd)
- [ ] Create automated testing for K8s deployments
- [ ] Add GPU support documentation
- [ ] Document backup and disaster recovery procedures

---

💡 **Tip**: Use `kubectl explain` to understand any Kubernetes resource: `kubectl explain deployment.spec`

📚 **Reference**: [Kubernetes Documentation](https://kubernetes.io/docs/)

🎯 **Next Step**: Ready to deploy locally? Start with [Minikube Setup](./04-kubernetes-basics/01-minikube-setup.md)
