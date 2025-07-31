# Troubleshooting K8s Deployments

> Comprehensive guide to diagnosing and fixing common MCP Mesh deployment issues on Kubernetes

## Overview

This troubleshooting guide addresses the most common issues encountered when deploying MCP Mesh on Kubernetes. Each issue includes symptoms, diagnostic steps, root cause analysis, and proven solutions. We'll cover pod failures, networking issues, storage problems, and performance bottlenecks.

## Quick Diagnostics

Run this comprehensive diagnostic script:

```bash
#!/bin/bash
# mcp-mesh-k8s-diagnostics.sh

NAMESPACE=${1:-mcp-mesh}

echo "MCP Mesh Kubernetes Diagnostics for namespace: $NAMESPACE"
echo "======================================================="

# Check namespace exists
echo -e "\n1. Checking namespace..."
kubectl get namespace $NAMESPACE || {
    echo "ERROR: Namespace $NAMESPACE not found"
    exit 1
}

# Check pods
echo -e "\n2. Pod Status:"
kubectl get pods -n $NAMESPACE -o wide
echo -e "\nProblematic pods:"
kubectl get pods -n $NAMESPACE --field-selector=status.phase!=Running,status.phase!=Succeeded

# Check services
echo -e "\n3. Service Status:"
kubectl get svc -n $NAMESPACE
echo -e "\nService endpoints:"
kubectl get endpoints -n $NAMESPACE

# Check registry
echo -e "\n4. Registry Status:"
kubectl get statefulset,pod,svc -n $NAMESPACE -l app.kubernetes.io/name=mcp-mesh-registry

# Check events
echo -e "\n5. Recent Events:"
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20

# Check resource usage
echo -e "\n6. Resource Usage:"
kubectl top nodes
kubectl top pods -n $NAMESPACE

# Check persistent volumes
echo -e "\n7. Storage:"
kubectl get pvc -n $NAMESPACE

# Network connectivity test
echo -e "\n8. Network Test:"
kubectl run test-network --rm -it --image=busybox --restart=Never -n $NAMESPACE -- \
    sh -c "nslookup mcp-mesh-registry && echo 'DNS OK' || echo 'DNS FAILED'"
```

## Common Issues and Solutions

### Issue 1: Pods Stuck in Pending State

**Symptoms:**

```
NAME                          READY   STATUS    RESTARTS   AGE
mcp-mesh-registry-0           0/1     Pending   0          5m
weather-agent-abc123          0/1     Pending   0          3m
```

**Diagnosis:**

```bash
# Check pod events
kubectl describe pod <pod-name> -n mcp-mesh

# Check node resources
kubectl describe nodes
kubectl top nodes

# Check PVC status
kubectl get pvc -n mcp-mesh
```

**Common Causes and Solutions:**

1. **Insufficient Resources**

   ```bash
   # Check resource requests
   kubectl describe pod <pod-name> -n mcp-mesh | grep -A10 Requests

   # Solution: Scale down other pods or add nodes
   kubectl scale deployment <other-deployment> --replicas=0 -n mcp-mesh

   # Or reduce resource requests
   kubectl patch deployment <deployment-name> -n mcp-mesh -p '
   {
     "spec": {
       "template": {
         "spec": {
           "containers": [{
             "name": "agent",
             "resources": {
               "requests": {
                 "cpu": "50m",
                 "memory": "64Mi"
               }
             }
           }]
         }
       }
     }
   }'
   ```

2. **PVC Not Bound**

   ```bash
   # Check PVC status
   kubectl get pvc -n mcp-mesh

   # Check available storage classes
   kubectl get storageclass

   # Create PVC with correct storage class
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

3. **Node Selector/Affinity Not Satisfied**

   ```bash
   # Check node labels
   kubectl get nodes --show-labels

   # Remove node selector temporarily
   kubectl patch deployment <deployment-name> -n mcp-mesh --type='json' -p='[
     {"op": "remove", "path": "/spec/template/spec/nodeSelector"}
   ]'
   ```

### Issue 2: Pods in CrashLoopBackOff

**Symptoms:**

```
NAME                          READY   STATUS             RESTARTS   AGE
analytics-agent-xyz789        0/1     CrashLoopBackOff   5          10m
```

**Diagnosis:**

```bash
# Check logs from current run
kubectl logs <pod-name> -n mcp-mesh

# Check logs from previous run
kubectl logs <pod-name> -n mcp-mesh --previous

# Check container exit code
kubectl describe pod <pod-name> -n mcp-mesh | grep -A10 "Last State"
```

**Common Causes and Solutions:**

1. **Missing Environment Variables**

   ```bash
   # Check current env vars
   kubectl exec <pod-name> -n mcp-mesh -- env

   # Add missing variables
   kubectl set env deployment/<deployment-name> \
     MCP_MESH_REGISTRY_URL=http://mcp-mesh-registry:8000 \
     -n mcp-mesh
   ```

2. **Registry Connection Failed**

   ```yaml
   # Add init container to wait for registry
   spec:
     initContainers:
       - name: wait-for-registry
         image: busybox:1.35
         command: ["sh", "-c"]
         args:
           - |
             until nc -z mcp-mesh-registry 8000; do
               echo "Waiting for registry..."
               sleep 2
             done
   ```

3. **Permission Errors**
   ```yaml
   # Fix file permissions
   spec:
     securityContext:
       runAsUser: 1000
       runAsGroup: 1000
       fsGroup: 1000
     containers:
       - name: agent
         securityContext:
           allowPrivilegeEscalation: false
           runAsNonRoot: true
   ```

### Issue 3: Service Discovery Not Working

**Symptoms:**

- Agents can't find registry
- "connection refused" errors
- DNS resolution failures

**Diagnosis:**

```bash
# Test DNS from pod
kubectl exec -it <pod-name> -n mcp-mesh -- nslookup mcp-mesh-registry

# Check service endpoints
kubectl get endpoints mcp-mesh-registry -n mcp-mesh

# Test connectivity
kubectl exec -it <pod-name> -n mcp-mesh -- wget -O- http://mcp-mesh-registry:8000/health
```

**Solutions:**

1. **DNS Issues**

   ```yaml
   # Configure pod DNS
   spec:
     dnsPolicy: ClusterFirst
     dnsConfig:
       options:
         - name: ndots
           value: "1"
   ```

2. **Service Selector Mismatch**

   ```bash
   # Verify labels match
   kubectl get svc mcp-mesh-registry -o yaml | grep -A5 selector
   kubectl get pods -l app.kubernetes.io/name=mcp-mesh-registry --show-labels
   ```

3. **Network Policy Blocking**

   ```bash
   # Check network policies
   kubectl get networkpolicy -n mcp-mesh

   # Temporarily disable
   kubectl delete networkpolicy --all -n mcp-mesh
   ```

### Issue 4: High Memory/CPU Usage

**Symptoms:**

- Pods getting OOMKilled
- Slow response times
- Node pressure

**Diagnosis:**

```bash
# Check resource usage
kubectl top pods -n mcp-mesh
kubectl describe pod <pod-name> -n mcp-mesh | grep -A20 Containers

# Check for memory leaks
kubectl exec <pod-name> -n mcp-mesh -- ps aux
```

**Solutions:**

1. **Increase Resource Limits**

   ```yaml
   resources:
     requests:
       memory: "256Mi"
       cpu: "100m"
     limits:
       memory: "1Gi"
       cpu: "1000m"
   ```

2. **Enable Horizontal Pod Autoscaling**

   ```bash
   kubectl autoscale deployment <deployment-name> \
     --min=2 --max=10 \
     --cpu-percent=70 \
     -n mcp-mesh
   ```

3. **Optimize Application**
   ```yaml
   env:
     - name: GOGC
       value: "50" # More aggressive garbage collection
     - name: GOMEMLIMIT
       value: "900MiB" # Soft memory limit
   ```

### Issue 5: Persistent Volume Issues

**Symptoms:**

- Data loss after pod restart
- Permission denied errors
- Disk full errors

**Diagnosis:**

```bash
# Check PVC status
kubectl get pvc -n mcp-mesh
kubectl describe pvc <pvc-name> -n mcp-mesh

# Check disk usage in pod
kubectl exec <pod-name> -n mcp-mesh -- df -h
```

**Solutions:**

1. **Expand PVC**

   ```bash
   # For expandable storage classes
   kubectl patch pvc <pvc-name> -n mcp-mesh -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
   ```

2. **Fix Permissions**
   ```yaml
   # Add init container to fix permissions
   initContainers:
     - name: fix-permissions
       image: busybox
       command: ["sh", "-c", "chown -R 1000:1000 /data"]
       volumeMounts:
         - name: data
           mountPath: /data
   ```

### Issue 6: Image Pull Errors

**Symptoms:**

```
Failed to pull image "mcpmesh/python-runtime:0.4": rpc error: code = Unknown desc = Error response from daemon: pull access denied
```

**Solutions:**

1. **For Minikube Local Images**

   ```bash
   # Use Minikube's Docker
   eval $(minikube docker-env)
   docker build -t mcp-mesh/agent:0.2 .

   # Set imagePullPolicy
   kubectl patch deployment <deployment-name> -n mcp-mesh -p '
   {
     "spec": {
       "template": {
         "spec": {
           "containers": [{
             "name": "agent",
             "imagePullPolicy": "Never"
           }]
         }
       }
     }
   }'
   ```

2. **For Private Registry**

   ```bash
   # Create pull secret
   kubectl create secret docker-registry regcred \
     --docker-server=myregistry.io \
     --docker-username=user \
     --docker-password=pass \
     --docker-email=email@example.com \
     -n mcp-mesh

   # Add to deployment
   kubectl patch deployment <deployment-name> -n mcp-mesh -p '
   {
     "spec": {
       "template": {
         "spec": {
           "imagePullSecrets": [{"name": "regcred"}]
         }
       }
     }
   }'
   ```

## Performance Troubleshooting

### Slow Agent Startup

**Diagnosis:**

```bash
# Check startup time
kubectl logs <pod-name> -n mcp-mesh | grep -E "started|ready"

# Profile startup
kubectl exec <pod-name> -n mcp-mesh -- python -m cProfile -o profile.stats agent.py
```

**Solutions:**

1. Add startup probe with longer timeout
2. Optimize imports and initialization
3. Use init containers for pre-warming

### High Latency Between Agents

**Diagnosis:**

```bash
# Test network latency
kubectl exec -it <pod-name> -n mcp-mesh -- ping <other-pod-ip>

# Check service mesh metrics (if using Istio)
kubectl exec -it <pod-name> -c istio-proxy -n mcp-mesh -- curl localhost:15000/stats/prometheus
```

**Solutions:**

1. Use node affinity to colocate related agents
2. Enable pod topology spread constraints
3. Optimize serialization/deserialization

## Debugging Tools and Commands

### Essential kubectl Commands

```bash
# Get comprehensive pod info
kubectl get pod <pod-name> -n mcp-mesh -o yaml

# Watch pod status changes
kubectl get pods -n mcp-mesh -w

# Get all resources in namespace
kubectl get all -n mcp-mesh

# Describe problematic resources
kubectl describe pod/deployment/service <name> -n mcp-mesh

# Check RBAC permissions
kubectl auth can-i --list --namespace=mcp-mesh
```

### Advanced Debugging

```bash
# Enable verbose logging
kubectl set env deployment/<deployment-name> LOG_LEVEL=DEBUG -n mcp-mesh

# Port forward for direct access
kubectl port-forward pod/<pod-name> 8080:8080 -n mcp-mesh

# Copy files from pod
kubectl cp <pod-name>:/path/to/file ./local-file -n mcp-mesh

# Run debug container
kubectl debug <pod-name> -it --image=busybox -n mcp-mesh
```

### Monitoring Commands

```bash
# Real-time resource monitoring
watch -n 2 'kubectl top pods -n mcp-mesh'

# Check cluster events
kubectl get events -n mcp-mesh --sort-by='.lastTimestamp' -w

# View audit logs (if enabled)
kubectl logs -n kube-system -l component=kube-apiserver | grep mcp-mesh
```

## Recovery Procedures

### Emergency Pod Recovery

```bash
#!/bin/bash
# emergency-recovery.sh

NAMESPACE=mcp-mesh

echo "Starting emergency recovery..."

# Delete stuck pods
kubectl delete pods --field-selector=status.phase=Failed -n $NAMESPACE
kubectl delete pods --field-selector=status.phase=Unknown -n $NAMESPACE

# Restart all deployments
kubectl rollout restart deployment -n $NAMESPACE

# Force delete stuck PVCs
kubectl patch pvc <pvc-name> -n $NAMESPACE -p '{"metadata":{"finalizers":null}}'

# Reset failed jobs
kubectl delete jobs --field-selector=status.successful=0 -n $NAMESPACE

echo "Recovery complete. Checking status..."
kubectl get all -n $NAMESPACE
```

### Data Recovery

```bash
# Backup registry data
kubectl exec mcp-mesh-registry-0 -n mcp-mesh -- \
  tar czf /tmp/backup.tar.gz /data

kubectl cp mcp-mesh-registry-0:/tmp/backup.tar.gz ./registry-backup.tar.gz -n mcp-mesh

# Restore registry data
kubectl cp ./registry-backup.tar.gz mcp-mesh-registry-0:/tmp/backup.tar.gz -n mcp-mesh
kubectl exec mcp-mesh-registry-0 -n mcp-mesh -- \
  tar xzf /tmp/backup.tar.gz -C /
```

## Prevention Strategies

### Resource Management

```yaml
# Set up ResourceQuota
apiVersion: v1
kind: ResourceQuota
metadata:
  name: mcp-mesh-quota
  namespace: mcp-mesh
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    persistentvolumeclaims: "10"
    pods: "50"
```

### Pod Disruption Budgets

```yaml
# Ensure availability during updates
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: registry-pdb
  namespace: mcp-mesh
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: mcp-mesh-registry
```

### Monitoring Setup

```yaml
# ServiceMonitor for Prometheus
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mcp-mesh-agents
  namespace: mcp-mesh
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: agent
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

## Getting Help

If these solutions don't resolve your issue:

1. **Collect Diagnostics:**

   ```bash
   kubectl cluster-info dump --namespace=mcp-mesh > cluster-dump.txt
   ```

2. **Check MCP Mesh Logs:**

   ```bash
   kubectl logs -l app.kubernetes.io/part-of=mcp-mesh -n mcp-mesh > mcp-mesh-logs.txt
   ```

3. **Community Resources:**
   - GitHub Issues: https://github.com/dhyansraj/mcp-mesh/issues
   - Kubernetes Slack: #mcp-mesh channel

---

💡 **Tip**: Always check `kubectl get events -n mcp-mesh` first - most issues are explained there

📚 **Reference**: [Kubernetes Troubleshooting Guide](https://kubernetes.io/docs/tasks/debug/)

🔍 **Debug Mode**: Set `MCP_MESH_DEBUG=true` in pod environment for verbose logging
