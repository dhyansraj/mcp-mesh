# Deploying with kubectl

> Deploy MCP Mesh agents to Kubernetes using kubectl and YAML manifests

## Overview

This guide covers deploying MCP Mesh agents to Kubernetes using kubectl commands and YAML manifests. You'll learn how to create Deployments, configure Services, manage ConfigMaps and Secrets, and monitor your agents. We'll start with simple deployments and progress to more complex configurations.

Understanding kubectl deployment is essential even if you plan to use Helm or operators, as it provides the foundation for all Kubernetes operations.

## Key Concepts

- **Deployments**: Manage stateless agent replicas
- **Services**: Expose agents for discovery and load balancing
- **ConfigMaps**: External configuration management
- **Secrets**: Sensitive data like API keys
- **Labels/Selectors**: Organize and select resources

## Step-by-Step Guide

### Step 1: Prepare Agent Container Image

First, ensure your agent is containerized:

```dockerfile
# Dockerfile for MCP Mesh agent
FROM python:3.11-slim

WORKDIR /app

# Install MCP Mesh from source
COPY . .
RUN make install-dev

# Non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

# Agent configuration
ENV MCP_MESH_REGISTRY_URL=http://mcp-mesh-registry:8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8081

CMD ["./bin/meshctl", "start", "examples/simple/my_agent.py"]
```

Build and push the image:

```bash
# For Minikube (local registry)
eval $(minikube docker-env)
docker build -t mcp-mesh/my-agent:0.2 .

# For remote registry
docker build -t myregistry.io/mcp-mesh/my-agent:0.2 .
docker push myregistry.io/mcp-mesh/my-agent:0.2
```

### Step 2: Create Basic Agent Deployment

Create a simple deployment manifest:

```yaml
# my-agent-deployment.yaml - Following actual K8s examples
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-agent
  namespace: mcp-mesh
  labels:
    app.kubernetes.io/name: my-agent # ← Critical: Used for SERVICE_NAME
    app.kubernetes.io/component: agent
    app.kubernetes.io/part-of: mcp-mesh
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: my-agent
      app.kubernetes.io/component: agent
  template:
    metadata:
      labels:
        app.kubernetes.io/name: my-agent # ← Must match for auto-detection
        app.kubernetes.io/component: agent
    spec:
      containers:
        - name: agent
          image: mcpmesh/python-runtime:0.6
          imagePullPolicy: IfNotPresent
          command: ["python", "/app/agent.py"]
          ports:
            - containerPort: 8080 # ← Standard port 8080
              name: http
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
            # HTTP server binding - bind to all interfaces
            - name: HOST
              value: "0.0.0.0"
            # 🎯 Kubernetes service discovery - auto-detect from labels
            - name: SERVICE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.labels['app.kubernetes.io/name']
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            # Fallback pod IP for backward compatibility
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: MCP_MESH_AGENT_NAME
              value: "my-agent"
          envFrom:
            - configMapRef:
                name: mcp-agent-config
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
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
          startupProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 30
```

Deploy the agent:

```bash
# Apply the deployment
kubectl apply -f my-agent-deployment.yaml

# Check deployment status
kubectl get deployment my-agent -n mcp-mesh

# Watch pods come up
kubectl get pods -n mcp-mesh -l app=my-agent -w

# Check logs
kubectl logs -n mcp-mesh -l app=my-agent
```

### Step 3: Configure Agent Service

Expose the agent with a Service:

```yaml
# my-agent-service.yaml - Must match deployment labels exactly
apiVersion: v1
kind: Service
metadata:
  name: my-agent # ← Must match app.kubernetes.io/name for SERVICE_NAME
  namespace: mcp-mesh
  labels:
    app.kubernetes.io/name: my-agent
    app.kubernetes.io/component: agent
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: my-agent # ← Must match deployment selector
    app.kubernetes.io/component: agent
  ports:
    - name: http
      port: 8080 # ← Standard port 8080
      targetPort: http
      protocol: TCP
    - name: metrics
      port: 9090
      targetPort: 9090
      protocol: TCP
```

Apply and test the service:

```bash
# Create service
kubectl apply -f my-agent-service.yaml

# Check service endpoints
kubectl get endpoints my-agent -n mcp-mesh

# Test service from another pod
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  wget -O- http://my-agent.mcp-mesh:8081/health
```

### Step 4: Manage Configuration with ConfigMaps

Create a ConfigMap for agent configuration:

```yaml
# agent-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-agent-config
  namespace: mcp-mesh
data:
  config.yaml: |
    agent:
      name: my-agent
      capabilities:
        - data_processing
        - analytics
      dependencies:
        - database_query
        - cache_get

    logging:
      level: info
      format: json

    features:
      enable_metrics: true
      enable_tracing: false

  # Additional configuration files
  rules.json: |
    {
      "processing_rules": [
        {"pattern": "*.csv", "handler": "csv_processor"},
        {"pattern": "*.json", "handler": "json_processor"}
      ]
    }
```

Update deployment to use ConfigMap:

```yaml
# Add to deployment spec
spec:
  template:
    spec:
      containers:
        - name: agent
          volumeMounts:
            - name: config
              mountPath: /etc/mcp-mesh
              readOnly: true
          env:
            - name: CONFIG_PATH
              value: /etc/mcp-mesh/config.yaml
      volumes:
        - name: config
          configMap:
            name: my-agent-config
```

Apply configuration:

```bash
# Create ConfigMap
kubectl apply -f agent-config.yaml

# Update deployment
kubectl apply -f my-agent-deployment.yaml

# Verify config is mounted
kubectl exec -it <pod-name> -n mcp-mesh -- ls -la /etc/mcp-mesh/
```

### Step 5: Handle Secrets Securely

Create secrets for sensitive data:

```bash
# Create secret from literals
kubectl create secret generic my-agent-secrets \
  --from-literal=api-key=supersecret123 \
  --from-literal=db-password=dbpass456 \
  -n mcp-mesh

# Or from files
kubectl create secret generic my-agent-certs \
  --from-file=tls.crt=path/to/cert.pem \
  --from-file=tls.key=path/to/key.pem \
  -n mcp-mesh
```

Use secrets in deployment:

```yaml
# Add to deployment spec
spec:
  template:
    spec:
      containers:
        - name: agent
          env:
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: my-agent-secrets
                  key: api-key
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: my-agent-secrets
                  key: db-password
          volumeMounts:
            - name: certs
              mountPath: /etc/ssl/certs
              readOnly: true
      volumes:
        - name: certs
          secret:
            secretName: my-agent-certs
```

## Configuration Options

| kubectl Option | Description           | Example              |
| -------------- | --------------------- | -------------------- |
| `--namespace`  | Target namespace      | `-n mcp-mesh`        |
| `--selector`   | Label selector        | `-l app=my-agent`    |
| `--output`     | Output format         | `-o yaml`, `-o json` |
| `--watch`      | Watch for changes     | `-w`                 |
| `--dry-run`    | Test without applying | `--dry-run=client`   |

## Examples

### Example 1: Multi-Environment Deployment

Deploy the same agent with different configurations:

```bash
# Development environment
kubectl apply -f my-agent-deployment.yaml \
  --dry-run=client -o yaml | \
  sed 's/replicas: 2/replicas: 1/' | \
  kubectl apply -f - -n mcp-mesh-dev

# Production environment with overrides
kubectl apply -f my-agent-deployment.yaml \
  --dry-run=client -o yaml | \
  sed 's/replicas: 2/replicas: 5/' | \
  sed 's/cpu: 100m/cpu: 500m/' | \
  kubectl apply -f - -n mcp-mesh-prod
```

### Example 2: Rolling Update Strategy

Configure zero-downtime updates:

```yaml
# rolling-update-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: analytics-agent
  namespace: mcp-mesh
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1 # One extra pod during update
      maxUnavailable: 0 # No pods down during update
  minReadySeconds: 30 # Wait 30s before considering pod ready
  selector:
    matchLabels:
      app: analytics-agent
  template:
    metadata:
      labels:
        app: analytics-agent
        version: v2.0.0
    spec:
      containers:
        - name: agent
          image: mcp-mesh/analytics-agent:v2.0.0
          # Graceful shutdown
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 15"]
```

Perform rolling update:

```bash
# Update image
kubectl set image deployment/analytics-agent \
  agent=mcp-mesh/analytics-agent:v2.1.0 \
  -n mcp-mesh

# Monitor rollout
kubectl rollout status deployment/analytics-agent -n mcp-mesh

# Rollback if needed
kubectl rollout undo deployment/analytics-agent -n mcp-mesh
```

## Best Practices

1. **Use Declarative Configuration**: Always use YAML files, not imperative commands
2. **Label Consistently**: Follow Kubernetes labeling conventions
3. **Set Resource Limits**: Prevent agents from consuming too many resources
4. **Configure Health Checks**: Ensure Kubernetes knows when pods are healthy
5. **Use Namespaces**: Isolate environments and teams

## Common Pitfalls

### Pitfall 1: Image Pull Errors

**Problem**: Pods stuck in ImagePullBackOff

**Solution**: Check image availability and pull secrets:

```bash
# Check pod events
kubectl describe pod <pod-name> -n mcp-mesh

# For private registries, create pull secret
kubectl create secret docker-registry regcred \
  --docker-server=myregistry.io \
  --docker-username=user \
  --docker-password=pass \
  -n mcp-mesh

# Add to deployment
spec:
  template:
    spec:
      imagePullSecrets:
      - name: regcred
```

### Pitfall 2: Service Discovery Not Working

**Problem**: Agents can't find each other

**Solution**: Verify service DNS:

```bash
# Test DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  nslookup my-agent.mcp-mesh.svc.cluster.local

# Check service endpoints
kubectl get endpoints -n mcp-mesh

# Ensure pods have correct labels
kubectl get pods -n mcp-mesh --show-labels
```

## Testing

### Deployment Validation Script

```bash
#!/bin/bash
# validate_deployment.sh

NAMESPACE=mcp-mesh
DEPLOYMENT=my-agent

echo "Validating deployment: $DEPLOYMENT"

# Check deployment exists
if ! kubectl get deployment $DEPLOYMENT -n $NAMESPACE &>/dev/null; then
  echo "ERROR: Deployment not found"
  exit 1
fi

# Check desired replicas
DESIRED=$(kubectl get deployment $DEPLOYMENT -n $NAMESPACE -o jsonpath='{.spec.replicas}')
READY=$(kubectl get deployment $DEPLOYMENT -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')

if [ "$READY" != "$DESIRED" ]; then
  echo "WARNING: Only $READY/$DESIRED replicas ready"
fi

# Check pod health
kubectl get pods -n $NAMESPACE -l app=$DEPLOYMENT -o wide

# Test service connectivity
SERVICE_IP=$(kubectl get svc $DEPLOYMENT -n $NAMESPACE -o jsonpath='{.spec.clusterIP}')
kubectl run test-curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://$SERVICE_IP:8080/health

echo "Deployment validation complete"
```

### Load Testing Deployed Agents

```python
# load_test_k8s.py
import asyncio
import aiohttp
import kubernetes
from kubernetes import client, config

async def test_agent_endpoint(session, endpoint):
    """Test agent health endpoint"""
    try:
        async with session.get(f"http://{endpoint}/health") as resp:
            return resp.status == 200
    except:
        return False

async def load_test_k8s_agents():
    """Load test all agents in namespace"""
    # Load Kubernetes config
    config.load_incluster_config()  # If running in cluster
    # or config.load_kube_config()  # If running locally

    v1 = client.CoreV1Api()

    # Get all agent services
    services = v1.list_namespaced_service("mcp-mesh")

    async with aiohttp.ClientSession() as session:
        tasks = []
        for svc in services.items:
            if "agent" in svc.metadata.name:
                endpoint = f"{svc.spec.cluster_ip}:8080"
                # Test each endpoint 100 times
                for _ in range(100):
                    tasks.append(test_agent_endpoint(session, endpoint))

        results = await asyncio.gather(*tasks)
        success_rate = sum(results) / len(results)
        print(f"Success rate: {success_rate * 100:.1f}%")

asyncio.run(load_test_k8s_agents())
```

## Monitoring and Debugging

### Monitor Deployments

```bash
# Watch deployment status
kubectl get deployments -n mcp-mesh -w

# View deployment details
kubectl describe deployment my-agent -n mcp-mesh

# Check rollout history
kubectl rollout history deployment/my-agent -n mcp-mesh

# View pod logs
kubectl logs -f deployment/my-agent -n mcp-mesh
```

### Debug Pod Issues

```bash
# Get pod details
kubectl get pods -n mcp-mesh -o wide

# Describe problematic pod
kubectl describe pod <pod-name> -n mcp-mesh

# Execute commands in pod
kubectl exec -it <pod-name> -n mcp-mesh -- /bin/sh

# Copy files from pod
kubectl cp <pod-name>:/path/to/file ./local-file -n mcp-mesh
```

## 🔧 Troubleshooting

### Issue 1: Pods Crashing on Startup

**Symptoms**: CrashLoopBackOff status

**Cause**: Application errors or missing dependencies

**Solution**:

```bash
# Check logs from previous run
kubectl logs <pod-name> -n mcp-mesh --previous

# Common fixes:
# 1. Check environment variables
kubectl get deployment my-agent -o yaml | grep -A20 env:

# 2. Verify ConfigMap/Secret exists
kubectl get configmap,secret -n mcp-mesh

# 3. Test with debug pod
kubectl run -it debug --image=mcp-mesh/my-agent:0.2 --rm -- /bin/sh
```

### Issue 2: Deployment Stuck Updating

**Symptoms**: Rollout not progressing

**Cause**: New pods failing health checks

**Solution**:

```bash
# Check rollout status
kubectl rollout status deployment/my-agent -n mcp-mesh

# Pause rollout
kubectl rollout pause deployment/my-agent -n mcp-mesh

# Fix issues and resume
kubectl rollout resume deployment/my-agent -n mcp-mesh

# Or rollback
kubectl rollout undo deployment/my-agent -n mcp-mesh
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **kubectl apply**: Limited to 1MB manifests
- **Port forwarding**: Single connection only
- **Exec**: Requires container shell
- **Windows**: Some commands require PowerShell

## 📝 TODO

- [ ] Add Kustomize examples
- [ ] Document kubectl plugins for MCP Mesh
- [ ] Add GitOps deployment patterns
- [ ] Create kubectl cheat sheet
- [ ] Add multi-cluster deployment

## Summary

You can now deploy MCP Mesh agents using kubectl:

Key takeaways:

- 🔑 Create and manage Deployments for agents
- 🔑 Configure Services for agent discovery
- 🔑 Use ConfigMaps and Secrets for configuration
- 🔑 Implement rolling updates and rollbacks

## Next Steps

Let's explore service discovery in Kubernetes.

Continue to [Service Discovery in K8s](./04-service-discovery.md) →

---

💡 **Tip**: Use `kubectl diff -f manifest.yaml` to preview changes before applying

📚 **Reference**: [kubectl Reference Documentation](https://kubernetes.io/docs/reference/kubectl/)

🧪 **Try It**: Deploy an agent with 3 replicas and perform a zero-downtime rolling update
