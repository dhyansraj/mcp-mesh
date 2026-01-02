# Helm Deployment Troubleshooting

> Comprehensive guide to diagnosing and resolving Helm deployment issues

## Overview

This troubleshooting guide covers common issues encountered when deploying MCP Mesh with Helm. Each issue includes symptoms, root causes, diagnostic steps, and solutions. The guide is organized by issue category to help you quickly find relevant solutions.

## Quick Diagnostics

Run this diagnostic script first:

```bash
#!/bin/bash
# helm-diagnostics.sh

echo "=== Helm Diagnostics for MCP Mesh ==="
echo "Date: $(date)"
echo ""

# Check Helm version
echo "1. Helm Version:"
helm version

# Check Kubernetes connection
echo -e "\n2. Kubernetes Cluster:"
kubectl cluster-info

# List Helm releases
echo -e "\n3. Helm Releases:"
helm list -A | grep mcp-mesh

# Check namespaces
echo -e "\n4. MCP Mesh Namespaces:"
kubectl get namespaces | grep mcp-mesh

# Check pods
echo -e "\n5. MCP Mesh Pods:"
kubectl get pods -A | grep mcp-mesh

# Check recent events
echo -e "\n6. Recent Events:"
kubectl get events -A --sort-by='.lastTimestamp' | grep -E "(mcp-mesh|Error|Failed)" | tail -20

# Check OCI registry access (MCP Mesh uses ghcr.io OCI registry)
echo -e "\n7. OCI Registry Access:"
helm show chart oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry --version 0.7.14 2>&1 | head -5

# Check for common issues
echo -e "\n8. Common Issues Check:"
echo -n "- CRDs installed: "
kubectl get crd | grep -c mcp-mesh || echo "0"
echo -n "- ConfigMap size issues: "
kubectl get configmap -A -o json | jq '.items[] | select(.metadata.name | contains("mcp-mesh")) | .data | tostring | length' | awk '{if($1>1048576) print "WARNING: ConfigMap > 1MB"; else print "OK"}'
```

## Common Issues by Category

### 🚀 Installation Issues

#### Issue 1: Chart Not Found

**Symptoms:**

```
Error: failed to download "oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry"
```

**Cause:** Chart version doesn't exist or network issues

**Solution:**

```bash
# Verify chart exists (OCI charts don't require helm repo add)
helm show chart oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry --version 0.7.1

# List available versions
helm search repo --regexp 'ghcr.io/dhyansraj/mcp-mesh' 2>/dev/null || \
  echo "Use: skopeo list-tags docker://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry"

# If using local charts
helm install my-release ./path/to/chart
```

#### Issue 2: Namespace Already Exists

**Symptoms:**

```
Error: namespaces "mcp-mesh" already exists
```

**Cause:** Namespace exists but not managed by Helm

**Solution:**

```bash
# Option 1: Remove --create-namespace flag
helm install my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --namespace mcp-mesh

# Option 2: Use existing namespace
kubectl label namespace mcp-mesh managed-by=helm

# Option 3: Delete and recreate
kubectl delete namespace mcp-mesh
helm install my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --namespace mcp-mesh \
  --create-namespace
```

#### Issue 3: Release Already Exists

**Symptoms:**

```
Error: INSTALLATION FAILED: cannot re-use a name that is still in use
```

**Cause:** Release name already used

**Solution:**

```bash
# Check existing releases
helm list -A | grep my-release

# Option 1: Upgrade existing release
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core --version 0.7.1

# Option 2: Uninstall and reinstall
helm uninstall my-release -n mcp-mesh
helm install my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core --version 0.7.1

# Option 3: Use different name
helm install my-release-2 oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core --version 0.7.1
```

### 📦 Dependency Issues

#### Issue 4: Dependency Download Failed

**Symptoms:**

```
Error: found in Chart.yaml, but missing in charts/ directory
```

**Cause:** Dependencies not updated

**Solution:**

```bash
# Update dependencies
helm dependency update ./mcp-mesh-platform

# Check dependency status
helm dependency list ./mcp-mesh-platform

# Add missing repositories
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

# Force rebuild
rm -rf ./mcp-mesh-platform/charts
rm ./mcp-mesh-platform/Chart.lock
helm dependency build ./mcp-mesh-platform
```

#### Issue 5: Version Constraint Conflicts

**Symptoms:**

```
Error: constraint not satisfied: prometheus version "15.x.x" does not match "19.x.x"
```

**Cause:** Incompatible dependency versions

**Solution:**

```yaml
# Update Chart.yaml dependencies
dependencies:
  - name: prometheus
    version: "~19.0.0"  # Use tilde for minor version flexibility
    repository: "https://prometheus-community.github.io/helm-charts"

# Or use exact version
dependencies:
  - name: prometheus
    version: "19.3.3"
    repository: "https://prometheus-community.github.io/helm-charts"
```

### 🔧 Configuration Issues

#### Issue 6: Values Not Applied

**Symptoms:**

- Deployed resources don't match expected configuration
- Default values used instead of custom values

**Cause:** Values file path or syntax issues

**Solution:**

```bash
# Debug values processing
helm template my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  -f values.yaml \
  --debug

# Check values precedence
helm install my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --dry-run \
  -f values-base.yaml \
  -f values-prod.yaml \
  --set image.tag=v2.0.0

# Validate YAML syntax
yamllint values.yaml

# Check final values
helm get values my-release --all
```

#### Issue 7: Template Rendering Errors

**Symptoms:**

```
Error: template: mcp-mesh-agent/templates/deployment.yaml:12:20: executing "..." at <.Values.missingKey>: nil pointer evaluating interface {}.missingKey
```

**Cause:** Missing required values or template errors

**Solution:**

```yaml
# Add defaults in templates
image: "{% raw %}{{ .Values.image.repository }}{% endraw %}:{% raw %}{{ .Values.image.tag | default .Chart.AppVersion }}{% endraw %}"

# Check for nil values
{% raw %}{{- if .Values.agent }}{% endraw %}
{% raw %}{{- if .Values.agent.config }}{% endraw %}
config: {% raw %}{{ .Values.agent.config }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
{% raw %}{{- end }}{% endraw %}

# Use required function
namespace: {% raw %}{{ required "A namespace is required!" .Values.namespace }}{% endraw %}
```

### 🏃 Runtime Issues

#### Issue 8: Pods Not Starting

**Symptoms:**

- Pods stuck in Pending, CrashLoopBackOff, or ImagePullBackOff

**Diagnosis:**

```bash
# Check pod status
kubectl get pods -n mcp-mesh

# Describe pod for events
kubectl describe pod <pod-name> -n mcp-mesh

# Check logs
kubectl logs <pod-name> -n mcp-mesh --previous

# Check resource availability
kubectl top nodes
kubectl describe node <node-name>
```

**Solutions:**

For **ImagePullBackOff**:

```bash
# Check image exists
docker pull <image-name>

# Add image pull secrets
kubectl create secret docker-registry regcred \
  --docker-server=<registry> \
  --docker-username=<username> \
  --docker-password=<password> \
  -n mcp-mesh

# Update values
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --set imagePullSecrets[0].name=regcred
```

For **CrashLoopBackOff**:

```bash
# Check container logs
kubectl logs <pod-name> -n mcp-mesh -c <container-name>

# Check liveness probe
kubectl get pod <pod-name> -n mcp-mesh -o yaml | grep -A10 livenessProbe

# Increase initial delay
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --set livenessProbe.initialDelaySeconds=60
```

For **Pending** pods:

```bash
# Check for PVC issues
kubectl get pvc -n mcp-mesh

# Check node selectors
kubectl get pod <pod-name> -n mcp-mesh -o yaml | grep -A5 nodeSelector

# Check resource requests
kubectl describe pod <pod-name> -n mcp-mesh | grep -A10 Requests
```

#### Issue 9: Service Connection Issues

**Symptoms:**

- Agents can't connect to registry
- Service discovery not working

**Diagnosis:**

```bash
# Test service DNS
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  nslookup mcp-mesh-registry.mcp-mesh.svc.cluster.local

# Check service endpoints
kubectl get endpoints -n mcp-mesh

# Test connectivity
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://mcp-mesh-registry.mcp-mesh.svc.cluster.local:8080/health
```

**Solution:**

```bash
# Verify service selector matches pods
kubectl get svc mcp-mesh-registry -n mcp-mesh -o yaml | grep -A5 selector
kubectl get pods -n mcp-mesh --show-labels

# Check network policies
kubectl get networkpolicy -n mcp-mesh

# Restart CoreDNS if needed
kubectl rollout restart deployment/coredns -n kube-system
```

### 📈 Performance Issues

#### Issue 10: Slow Deployments

**Symptoms:**

- Helm install/upgrade takes too long
- Timeouts during deployment

**Diagnosis:**

```bash
# Time the template rendering
time helm template my-release ./mcp-mesh-platform > /dev/null

# Check manifest size
helm template my-release ./mcp-mesh-platform | wc -c

# Monitor deployment progress
kubectl rollout status deployment/mcp-mesh-registry -n mcp-mesh --watch
```

**Solution:**

```bash
# Increase timeout
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --timeout 15m \
  --wait

# Use atomic deployments
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --atomic \
  --cleanup-on-fail

# Optimize resource requests
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --set resources.requests.cpu=100m \
  --set resources.requests.memory=128Mi
```

#### Issue 11: High Memory Usage

**Symptoms:**

- OOMKilled pods
- Nodes running out of memory

**Solution:**

```yaml
# Increase memory limits
resources:
  requests:
    memory: "512Mi"
  limits:
    memory: "1Gi"

# Add JVM heap settings for Java agents
env:
  - name: JAVA_OPTS
    value: "-Xmx768m -Xms256m"

# Enable vertical pod autoscaling
vpa:
  enabled: true
  updateMode: "Auto"
```

### 🔐 Security Issues

#### Issue 12: RBAC Permissions

**Symptoms:**

```
Error from server (Forbidden): pods is forbidden: User "system:serviceaccount:mcp-mesh:default" cannot list resource "pods"
```

**Solution:**

```yaml
# Create service account with proper permissions
serviceAccount:
  create: true
  name: mcp-mesh-agent
  annotations: {}

# Add RBAC rules
rbac:
  create: true
  rules:
    - apiGroups: [""]
      resources: ["pods", "services"]
      verbs: ["get", "list", "watch"]
```

#### Issue 13: Secret Management

**Symptoms:**

- Secrets visible in helm values
- Failed to decrypt secrets

**Solution:**

```bash
# Use Helm secrets plugin
helm plugin install https://github.com/jkroepke/helm-secrets

# Encrypt values
helm secrets enc values-secrets.yaml

# Install with encrypted values
helm secrets install my-release ./mcp-mesh-platform \
  -f values.yaml \
  -f values-secrets.yaml

# Or use external secrets
kubectl create secret generic mcp-mesh-secrets \
  --from-literal=api-key=secret123 \
  -n mcp-mesh
```

### 🔄 Upgrade Issues

#### Issue 14: Failed Upgrade

**Symptoms:**

```
Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress
```

**Solution:**

```bash
# Check for stuck operations
helm history my-release -n mcp-mesh

# Fix stuck release
kubectl delete secret sh.helm.release.v1.my-release.v2 -n mcp-mesh

# Or rollback
helm rollback my-release 1 -n mcp-mesh

# Force upgrade
helm upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  --force \
  --reset-values
```

#### Issue 15: Breaking Changes

**Symptoms:**

- Upgrade fails due to incompatible changes
- Resources can't be updated

**Solution:**

```bash
# Check for breaking changes
helm diff upgrade my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core --version 0.7.1

# Backup current state
helm get values my-release -n mcp-mesh > backup-values.yaml
kubectl get all -n mcp-mesh -o yaml > backup-resources.yaml

# Uninstall and reinstall if needed
helm uninstall my-release -n mcp-mesh
kubectl delete pvc -n mcp-mesh --all  # If keeping data
helm install my-release oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.7.14 \
  -f backup-values.yaml
```

## Advanced Debugging

### Enable Debug Logging

```yaml
# values-debug.yaml
global:
  debug: true

logging:
  level: DEBUG

# Add debug sidecars
sidecars:
  - name: debug
    image: busybox
    command: ["sh", "-c", "while true; do sleep 30; done;"]
```

### Helm Debug Commands

```bash
# Full debug output
helm install my-release ./chart \
  --debug \
  --dry-run \
  --disable-openapi-validation

# Trace template execution
helm template my-release ./chart \
  --debug 2>&1 | grep -E "^---$|Error"

# Validate chart
helm lint ./chart --strict --with-subcharts

# Get all resources created by release
helm get manifest my-release -n mcp-mesh | \
  kubectl get -f - -o wide
```

### Kubernetes Debug Tools

```bash
# Deploy debug pod
kubectl run debug \
  --image=nicolaka/netshoot \
  --rm -it \
  --namespace mcp-mesh \
  -- /bin/bash

# Inside debug pod:
# DNS debugging
nslookup mcp-mesh-registry
dig mcp-mesh-registry.mcp-mesh.svc.cluster.local

# Network debugging
curl -v http://mcp-mesh-registry:8080/health
tcpdump -i eth0 host mcp-mesh-registry

# Process debugging
ps aux
netstat -tulpn
```

## Recovery Procedures

### Complete Reset

```bash
#!/bin/bash
# reset-mcp-mesh.sh

NAMESPACE="mcp-mesh"
RELEASE="my-release"

echo "WARNING: This will delete all MCP Mesh resources!"
read -p "Continue? (yes/no): " confirm

if [[ "$confirm" == "yes" ]]; then
  # Uninstall Helm release
  helm uninstall $RELEASE -n $NAMESPACE || true

  # Delete namespace
  kubectl delete namespace $NAMESPACE --grace-period=0 --force || true

  # Delete CRDs if any
  kubectl delete crd -l app.kubernetes.io/part-of=mcp-mesh || true

  # Clean up finalizers
  kubectl get namespace $NAMESPACE -o json | \
    jq '.spec.finalizers = []' | \
    kubectl replace --raw /api/v1/namespaces/$NAMESPACE/finalize -f -

  echo "Reset complete. You can now reinstall MCP Mesh."
fi
```

### Data Recovery

```bash
# Backup PVCs before deletion
kubectl get pvc -n mcp-mesh -o yaml > pvc-backup.yaml

# Restore PVCs
kubectl apply -f pvc-backup.yaml

# Verify data integrity
kubectl exec -it mcp-mesh-registry-0 -n mcp-mesh -- \
  sqlite3 /data/registry.db "SELECT COUNT(*) FROM agents;"
```

## Prevention Best Practices

1. **Always Test First**

   ```bash
   helm install --dry-run --debug
   helm diff upgrade
   ```

2. **Use Atomic Deployments**

   ```bash
   helm upgrade --atomic --cleanup-on-fail
   ```

3. **Version Everything**

   ```yaml
   image:
     tag: "1.0.0" # Never use 'latest'
   ```

4. **Monitor Deployments**

   ```bash
   helm upgrade --wait --timeout 10m
   ```

5. **Keep Backups**
   ```bash
   helm get values > values-backup.yaml
   ```

## Getting Help

If you're still experiencing issues:

1. **Check Documentation**
   - [Helm Deployment Guide](../06-helm-deployment.md)
   - [Helm Best Practices](./05-best-practices.md)

2. **Gather Information**

   ```bash
   ./helm-diagnostics.sh > diagnostics.txt
   helm get all my-release > release-info.txt
   kubectl logs -n mcp-mesh -l app.kubernetes.io/part-of=mcp-mesh --tail=100 > logs.txt
   ```

3. **Community Support**
   - GitHub Issues: https://github.com/mcp-mesh/mcp-mesh/issues
   - Slack: #mcp-mesh-help
   - Stack Overflow: [mcp-mesh] tag

## Summary

This guide covered the most common Helm deployment issues:

Key takeaways:

- 🔍 Always gather diagnostic information first
- 🔧 Most issues have straightforward solutions
- 📋 Follow systematic troubleshooting steps
- 🛡️ Implement preventive measures

---

💡 **Remember**: When in doubt, use `--dry-run` and `--debug` flags

📚 **Reference**: [Helm Troubleshooting Guide](https://helm.sh/docs/faq/troubleshooting/)

🆘 **Emergency**: If production is down, prioritize `helm rollback` over debugging
