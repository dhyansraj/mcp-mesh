# Local Registry Configuration

> Deploy and configure the MCP Mesh registry on Kubernetes for agent coordination

## Overview

The MCP Mesh registry is the central coordination point for all agents, managing service discovery, health checks, and capability routing. This guide covers deploying the registry as a StatefulSet on Kubernetes, configuring persistent storage, and setting up high availability.

We'll explore both simple single-instance deployments for development and multi-replica configurations for production readiness.

## Key Concepts

- **StatefulSet**: Provides stable network identities and persistent storage
- **Headless Service**: Enables direct pod-to-pod communication
- **Leader Election**: Ensures consistency in multi-replica deployments
- **Persistent Volumes**: Store registry data across pod restarts
- **ConfigMaps/Secrets**: Externalize configuration and credentials

## Step-by-Step Guide

### Step 1: Create Namespace and Prerequisites

Set up the MCP Mesh namespace and basic resources:

```bash
# Create namespace
kubectl create namespace mcp-mesh

# Set as default namespace
kubectl config set-context --current --namespace=mcp-mesh

# Create RBAC resources
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mcp-mesh-registry-leader-election
  namespace: mcp-mesh
rules:
- apiGroups: ["coordination.k8s.io"]
  resources: ["leases"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: mcp-mesh-registry-leader-election
  namespace: mcp-mesh
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: mcp-mesh-registry-leader-election
subjects:
- kind: ServiceAccount
  name: mcp-mesh-registry
  namespace: mcp-mesh
EOF
```

### Step 2: Configure Registry Storage

Create ConfigMap for registry configuration:

```yaml
# registry-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-registry-config
  namespace: mcp-mesh
data:
  # Database configuration
  DATABASE_TYPE: "sqlite" # Use sqlite for local development
  DATABASE_PATH: "/data/registry.db"

  # Registry settings
  REGISTRY_PORT: "8080"
  METRICS_PORT: "9090"
  LOG_LEVEL: "info"

  # Health check settings
  HEALTH_CHECK_INTERVAL: "30s"
  AGENT_TIMEOUT: "60s"

  # Leader election (for multi-replica)
  ENABLE_LEADER_ELECTION: "true"
  LEADER_ELECTION_LEASE_DURATION: "15s"
  LEADER_ELECTION_RENEW_DEADLINE: "10s"
  LEADER_ELECTION_RETRY_PERIOD: "2s"
---
apiVersion: v1
kind: Secret
metadata:
  name: mcp-registry-secret
  namespace: mcp-mesh
type: Opaque
stringData:
  # Add any sensitive configuration here
  AUTH_TOKEN: "dev-token-change-in-production"
  ENCRYPTION_KEY: "dev-key-32-bytes-change-in-prod!"
```

Apply the configuration:

```bash
kubectl apply -f registry-config.yaml
```

### Step 3: Deploy Registry StatefulSet

Create the registry StatefulSet for development:

```yaml
# registry-statefulset-dev.yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-mesh-registry-headless
  namespace: mcp-mesh
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: mcp-mesh-registry
  ports:
    - name: http
      port: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: mcp-mesh-registry
  ports:
    - name: http
      port: 8080
      targetPort: 8080
    - name: metrics
      port: 9090
      targetPort: 9090
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
spec:
  serviceName: mcp-mesh-registry-headless
  replicas: 1 # Single instance for development
  selector:
    matchLabels:
      app.kubernetes.io/name: mcp-mesh-registry
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mcp-mesh-registry
        app.kubernetes.io/component: registry
    spec:
      serviceAccountName: mcp-mesh-registry
      containers:
        - name: registry
          image: mcp-mesh/registry:latest
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8080
            - name: metrics
              containerPort: 9090
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          envFrom:
            - configMapRef:
                name: mcp-registry-config
            - secretRef:
                name: mcp-registry-secret
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
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
            storage: 5Gi
```

Deploy the registry:

```bash
kubectl apply -f registry-statefulset-dev.yaml

# Wait for registry to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mcp-mesh-registry --timeout=60s

# Check status
kubectl get statefulset,pod,svc,pvc -l app.kubernetes.io/name=mcp-mesh-registry
```

### Step 4: Verify Registry Operation

Test registry health and functionality:

```bash
# Port forward to access registry
kubectl port-forward svc/mcp-mesh-registry 8080:8080 &

# Check health endpoint
curl http://localhost:8080/health

# Check metrics
curl http://localhost:8080/metrics

# View registry logs
kubectl logs -f mcp-mesh-registry-0

# Check API endpoints
curl http://localhost:8080/api/v1/agents
curl http://localhost:8080/api/v1/capabilities
```

### Step 5: Configure for High Availability

For production, deploy with multiple replicas:

```yaml
# registry-ha.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
spec:
  serviceName: mcp-mesh-registry-headless
  replicas: 3 # High availability with 3 replicas
  podManagementPolicy: Parallel
  updateStrategy:
    type: RollingUpdate
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app.kubernetes.io/name: mcp-mesh-registry
              topologyKey: kubernetes.io/hostname
      containers:
        - name: registry
          env:
            - name: ENABLE_LEADER_ELECTION
              value: "true"
            - name: REGISTRY_INSTANCE_ID
              value: "$(POD_NAME)"
          # ... rest of container spec
```

Apply HA configuration:

```bash
# Scale up existing StatefulSet
kubectl scale statefulset mcp-mesh-registry --replicas=3

# Or apply new configuration
kubectl apply -f registry-ha.yaml

# Monitor rollout
kubectl rollout status statefulset mcp-mesh-registry
```

## Configuration Options

| Environment Variable     | Description                  | Default           | Example            |
| ------------------------ | ---------------------------- | ----------------- | ------------------ |
| `DATABASE_TYPE`          | Database backend             | sqlite            | postgresql, mysql  |
| `DATABASE_PATH`          | SQLite file path             | /data/registry.db | /data/mesh.db      |
| `REGISTRY_PORT`          | HTTP service port            | 8080              | 9000               |
| `LOG_LEVEL`              | Logging verbosity            | info              | debug, warn, error |
| `ENABLE_LEADER_ELECTION` | Enable HA mode               | false             | true               |
| `HEALTH_CHECK_INTERVAL`  | Agent health check frequency | 30s               | 60s                |

## Examples

### Example 1: Development Setup with Local Image

```bash
# Build registry image locally in Minikube
eval $(minikube docker-env)
docker build -t mcp-mesh/registry:dev ./cmd/registry

# Deploy with local image
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry-dev
  namespace: mcp-mesh
spec:
  replicas: 1
  serviceName: registry-dev
  selector:
    matchLabels:
      app: registry-dev
  template:
    metadata:
      labels:
        app: registry-dev
    spec:
      containers:
      - name: registry
        image: mcp-mesh/registry:dev
        imagePullPolicy: Never  # Use local image
        env:
        - name: LOG_LEVEL
          value: debug
        - name: DATABASE_TYPE
          value: sqlite
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
          storage: 1Gi
EOF
```

### Example 2: Production Setup with PostgreSQL

```yaml
# postgres-registry.yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: mcp-mesh
stringData:
  POSTGRES_USER: mcpmesh
  POSTGRES_PASSWORD: changeme
  POSTGRES_DB: registry
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: mcp-mesh
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:15-alpine
          envFrom:
            - secretRef:
                name: postgres-secret
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: postgres-pvc
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-registry-config
  namespace: mcp-mesh
data:
  DATABASE_TYPE: postgresql
  DATABASE_HOST: postgres
  DATABASE_PORT: "5432"
  DATABASE_NAME: registry
  DATABASE_USER: mcpmesh
```

## Best Practices

1. **Use StatefulSet**: Provides stable network identity and storage
2. **Configure Anti-Affinity**: Spread replicas across nodes
3. **Set Resource Limits**: Prevent registry from consuming too many resources
4. **Enable Monitoring**: Export metrics for Prometheus
5. **Backup Data**: Regular backups of registry database

## Common Pitfalls

### Pitfall 1: PVC Stuck in Pending

**Problem**: PersistentVolumeClaim won't bind

**Solution**: Check StorageClass availability:

```bash
# List available storage classes
kubectl get storageclass

# Create PVC with specific storage class
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: registry-data
  namespace: mcp-mesh
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: standard  # Use available class
  resources:
    requests:
      storage: 5Gi
EOF
```

### Pitfall 2: Registry Pods Not Starting

**Problem**: Pods stuck in CrashLoopBackOff

**Solution**: Check logs and events:

```bash
# View pod logs
kubectl logs mcp-mesh-registry-0 -p

# Check events
kubectl describe pod mcp-mesh-registry-0

# Common fixes:
# 1. Fix image name/tag
# 2. Correct environment variables
# 3. Ensure volume permissions
```

## Testing

### Registry Health Check Script

```bash
#!/bin/bash
# test_registry_health.sh

NAMESPACE=mcp-mesh
REGISTRY_SVC=mcp-mesh-registry

echo "Testing MCP Mesh Registry deployment..."

# Check StatefulSet
if ! kubectl get statefulset mcp-mesh-registry -n $NAMESPACE &>/dev/null; then
  echo "ERROR: Registry StatefulSet not found"
  exit 1
fi

# Check all pods are ready
READY_PODS=$(kubectl get statefulset mcp-mesh-registry -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
DESIRED_PODS=$(kubectl get statefulset mcp-mesh-registry -n $NAMESPACE -o jsonpath='{.spec.replicas}')

if [ "$READY_PODS" != "$DESIRED_PODS" ]; then
  echo "ERROR: Only $READY_PODS/$DESIRED_PODS pods ready"
  exit 1
fi

# Test service endpoint
kubectl run test-curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://$REGISTRY_SVC.$NAMESPACE:8080/health

echo "Registry health check passed!"
```

### Load Test Registry

```python
# test_registry_load.py
import asyncio
import aiohttp
import time

async def register_agent(session, agent_id):
    """Register a test agent"""
    data = {
        "id": f"test-agent-{agent_id}",
        "capabilities": ["test"],
        "endpoint": f"http://agent-{agent_id}:8080"
    }

    async with session.post(
        "http://localhost:8080/api/v1/agents",
        json=data
    ) as response:
        return response.status == 200

async def load_test():
    """Test registry under load"""
    async with aiohttp.ClientSession() as session:
        start = time.time()

        # Register 100 agents concurrently
        tasks = [register_agent(session, i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        duration = time.time() - start
        success_rate = sum(results) / len(results)

        print(f"Registered {len(results)} agents in {duration:.2f}s")
        print(f"Success rate: {success_rate * 100:.1f}%")

if __name__ == "__main__":
    asyncio.run(load_test())
```

## Monitoring and Debugging

### View Registry Metrics

```bash
# Port forward to metrics port
kubectl port-forward svc/mcp-mesh-registry 9090:9090

# Query metrics
curl http://localhost:9090/metrics | grep mcp_

# Common metrics:
# mcp_registry_agents_total - Total registered agents
# mcp_registry_requests_total - API request count
# mcp_registry_errors_total - Error count
```

### Debug Registry Issues

```bash
# Enter registry pod
kubectl exec -it mcp-mesh-registry-0 -- sh

# Inside pod:
# Check database
sqlite3 /data/registry.db "SELECT * FROM agents;"

# Test internal endpoints
wget -O- http://localhost:8080/health

# Check disk usage
df -h /data
```

## 🔧 Troubleshooting

### Issue 1: Leader Election Failures

**Symptoms**: Multiple registry instances think they're leader

**Cause**: Network partitions or timeout issues

**Solution**:

```yaml
# Adjust leader election timeouts
env:
  - name: LEADER_ELECTION_LEASE_DURATION
    value: "30s" # Increase from 15s
  - name: LEADER_ELECTION_RENEW_DEADLINE
    value: "20s" # Increase from 10s
```

### Issue 2: Slow Registry Queries

**Symptoms**: Agent registration/discovery taking too long

**Cause**: Database performance or resource constraints

**Solution**:

```bash
# Increase resources
kubectl patch statefulset mcp-mesh-registry --type='json' -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value":"256Mi"},
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value":"1Gi"}
]'

# Add database indexes (PostgreSQL)
kubectl exec -it postgres-0 -- psql -U mcpmesh -d registry -c "
CREATE INDEX idx_agents_capability ON agents(capability);
CREATE INDEX idx_agents_last_seen ON agents(last_seen);
"
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **SQLite**: Not suitable for high-concurrency production use
- **Storage**: StatefulSet volumes can't be easily resized
- **Minikube**: Limited to single-node storage
- **Leader Election**: Requires Kubernetes 1.14+

## 📝 TODO

- [ ] Add Helm chart for registry deployment
- [ ] Document external database setup
- [ ] Add backup/restore procedures
- [ ] Create registry operator
- [ ] Add multi-region deployment guide

## Summary

You've successfully deployed the MCP Mesh registry on Kubernetes:

Key takeaways:

- 🔑 Registry running as StatefulSet with persistent storage
- 🔑 Services configured for internal and external access
- 🔑 High availability options for production
- 🔑 Monitoring and health checks enabled

## Next Steps

Now let's deploy agents using kubectl.

Continue to [Deploying with kubectl](./03-kubectl-deployment.md) →

---

💡 **Tip**: Use `kubectl logs -f statefulset/mcp-mesh-registry --all-containers=true` to stream logs from all registry pods

📚 **Reference**: [Kubernetes StatefulSet Documentation](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)

🧪 **Try It**: Scale the registry to 3 replicas and observe leader election in action
