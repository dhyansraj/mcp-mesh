# Multi-Agent Deployment

> Deploy multiple MCP Mesh agents with the registry using individual charts

## Overview

While MCP Mesh doesn't currently have an umbrella chart, you can deploy multiple agents alongside the registry using the individual charts. This guide shows how to deploy a complete platform using the existing `mcp-mesh-registry` and `mcp-mesh-agent` charts, and provides a template for creating your own umbrella chart.

We'll show how to deploy the registry and multiple agents systematically, and then show how to create an umbrella chart for automated deployment.

## Key Concepts

- **Multi-Chart Deployment**: Using individual charts to build a platform
- **Dependency Management**: Deploying components in the correct order
- **Value Consistency**: Ensuring compatible configuration across charts
- **Service Discovery**: Connecting agents to the registry
- **Chart Aliases**: Deploying multiple instances of the same chart

## Step-by-Step Guide

### Step 1: Deploy the Registry First

Start by deploying the registry service:

```bash
# From the project root/helm directory
cd helm

# Create namespace
kubectl create namespace mcp-mesh

# Deploy the registry
helm install mcp-registry ./mcp-mesh-registry \
  --namespace mcp-mesh \
  --values values-registry.yaml

# Wait for registry to be ready
kubectl wait --for=condition=available deployment/mcp-registry \
  -n mcp-mesh --timeout=300s

# Verify registry is running
kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry
```

Create registry values file:

```yaml
# values-registry.yaml
replicaCount: 1

image:
  repository: mcp-mesh-base
  tag: "0.5"
  pullPolicy: Never

service:
  port: 8000

registry:
  host: "0.0.0.0"
  port: 8000
  database:
    type: sqlite
    path: /data/registry.db

persistence:
  enabled: true
  size: 5Gi

resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### Step 2: Deploy Multiple Agents

Deploy various agents that connect to the registry:

```bash
# Deploy hello-world agent
helm install hello-world-agent ./mcp-mesh-agent \
  --namespace mcp-mesh \
  --values values-hello-world.yaml

# Deploy system agent
helm install system-agent ./mcp-mesh-agent \
  --namespace mcp-mesh \
  --values values-system.yaml

# Deploy weather agent
helm install weather-agent ./mcp-mesh-agent \
  --namespace mcp-mesh \
  --values values-weather.yaml

# Verify all agents are running
kubectl get pods -n mcp-mesh
```

Create agent values files:

```yaml
# values-hello-world.yaml
agent:
  name: hello-world-agent
  script: hello_world.py
  http:
    port: 8080
  registryUrl: "http://mcp-registry-mcp-mesh-registry:8000"
  capabilities:
    - greeting
    - translation

image:
  repository: mcp-mesh-base
  tag: "0.5"
  pullPolicy: Never

resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "256Mi"
    cpu: "100m"
```

```yaml
# values-system.yaml
agent:
  name: system-agent
  script: system_agent.py
  http:
    port: 8080
  registryUrl: "http://mcp-registry-mcp-mesh-registry:8000"
  capabilities:
    - file_operations
    - system_info

image:
  repository: mcp-mesh-base
  tag: "0.5"
  pullPolicy: Never

resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "200m"
```

```yaml
# values-weather.yaml
agent:
  name: weather-agent
  script: weather_agent.py
  http:
    port: 8080
  registryUrl: "http://mcp-registry-mcp-mesh-registry:8000"
  capabilities:
    - weather_forecast
    - weather_current
  dependencies:
    - location_service

image:
  repository: mcp-mesh-base
  tag: "0.5"
  pullPolicy: Never

env:
  WEATHER_API_KEY: "your-api-key"
  CACHE_TTL: "300"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "512Mi"
    cpu: "200m"
```

### Step 3: Create an Umbrella Chart (Optional)

For future use, you can create an umbrella chart to deploy everything together:

```bash
# Create umbrella chart directory
mkdir mcp-mesh-platform
cd mcp-mesh-platform

# Create Chart.yaml
cat > Chart.yaml << 'EOF'
apiVersion: v2
name: mcp-mesh-platform
description: Complete MCP Mesh platform deployment
type: application
version: 1.0.0
appVersion: "1.0.0"
keywords:
  - mcp-mesh
  - platform
  - microservices

dependencies:
  # Core registry
  - name: mcp-mesh-registry
    version: "0.5.5"
    repository: "file://../mcp-mesh-registry"
    condition: registry.enabled

  # Agents using aliases for multiple instances
  - name: mcp-mesh-agent
    version: "0.5.5"
    repository: "file://../mcp-mesh-agent"
    alias: hello-world-agent
    condition: agents.helloWorld.enabled

  - name: mcp-mesh-agent
    version: "0.5.5"
    repository: "file://../mcp-mesh-agent"
    alias: system-agent
    condition: agents.system.enabled

  - name: mcp-mesh-agent
    version: "0.5.5"
    repository: "file://../mcp-mesh-agent"
    alias: weather-agent
    condition: agents.weather.enabled
EOF
```

Create umbrella chart values:

```yaml
# values.yaml
# Global settings
global:
  imageRegistry: ""
  namespace: mcp-mesh

# Registry configuration
registry:
  enabled: true

mcp-mesh-registry:
  replicaCount: 1
  image:
    repository: mcp-mesh-base
    tag: "0.5"
    pullPolicy: Never
  service:
    port: 8000
  persistence:
    enabled: true
    size: 5Gi

# Agent configurations
agents:
  helloWorld:
    enabled: true
  system:
    enabled: true
  weather:
    enabled: true

hello-world-agent:
  agent:
    name: hello-world-agent
    script: hello_world.py
    registryUrl: "http://mcp-mesh-platform-mcp-mesh-registry:8000"
    capabilities:
      - greeting
      - translation
  image:
    repository: mcp-mesh-base
    tag: "0.5"
    pullPolicy: Never

system-agent:
  agent:
    name: system-agent
    script: system_agent.py
    registryUrl: "http://mcp-mesh-platform-mcp-mesh-registry:8000"
    capabilities:
      - file_operations
      - system_info
  image:
    repository: mcp-mesh-base
    tag: "0.5"
    pullPolicy: Never

weather-agent:
  agent:
    name: weather-agent
    script: weather_agent.py
    registryUrl: "http://mcp-mesh-platform-mcp-mesh-registry:8000"
    capabilities:
      - weather_forecast
      - weather_current
  image:
    repository: mcp-mesh-base
    tag: "0.5"
    pullPolicy: Never
  env:
    WEATHER_API_KEY: "your-api-key"
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
```

Deploy the platform:

```bash
# Update dependencies
helm dependency update ./mcp-mesh-platform

# Deploy the complete platform
helm install mcp-platform ./mcp-mesh-platform \
  --namespace mcp-mesh \
  --create-namespace
```

Platform-wide labels
\*/}}
{{- define "mcp-mesh-platform.labels" -}}
app.kubernetes.io/part-of: mcp-mesh-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ include "mcp-mesh-platform.chart" . }}
{{- end }}

{{/*
Registry URL for agents
*/}}
{{- define "mcp-mesh-platform.registryUrl" -}}
{{- if .Values.registry.externalUrl -}}
{{- .Values.registry.externalUrl -}}
{{- else -}}
http://{{ .Release.Name }}-mcp-mesh-registry:{{ .Values.registry.service.port | default 8080 }}
{{- end -}}
{{- end }}

{{/*
Database connection string
*/}}
{{- define "mcp-mesh-platform.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
postgresql://{{ .Values.global.postgresql.auth.username | default "postgres" }}:{{ .Values.global.postgresql.auth.postgresPassword }}@{{ .Release.Name }}-postgresql:5432/{{ .Values.global.postgresql.auth.database }}
{{- else -}}
{{- required "External database URL required when postgresql.enabled=false" .Values.registry.database.externalUrl -}}
{{- end -}}
{{- end }}

````

### Step 4: Add Platform-Level Resources

Create additional resources for the platform:

```yaml
# templates/namespace.yaml
{{- if .Values.createNamespace }}
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .Release.Namespace }}
  labels:
    {{- include "mcp-mesh-platform.labels" . | nindent 4 }}
{{- end }}

---
# templates/resourcequota.yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ .Release.Name }}-quota
  namespace: {{ .Release.Namespace }}
spec:
  hard:
    {{- toYaml .Values.resourceQuota.hard | nindent 4 }}
{{- end }}

---
# templates/networkpolicy.yaml
{{- if .Values.networkPolicies.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ .Release.Name }}-default-deny
  namespace: {{ .Release.Namespace }}
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  egress:
  # Allow DNS
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # Allow intra-namespace
  {{- if .Values.networkPolicies.allowIntraNamespace }}
  - to:
    - podSelector: {}
  {{- end }}
  ingress:
  # Allow from allowed namespaces
  {{- range .Values.networkPolicies.allowedNamespaces }}
  - from:
    - namespaceSelector:
        matchLabels:
          name: {{ . }}
  {{- end }}
  # Allow intra-namespace
  {{- if .Values.networkPolicies.allowIntraNamespace }}
  - from:
    - podSelector: {}
  {{- end }}
{{- end }}
````

### Step 5: Create Deployment Scripts

Add convenient deployment scripts:

```yaml
# templates/NOTES.txt
{{- $registryUrl := include "mcp-mesh-platform.registryUrl" . -}}
MCP Mesh Platform has been deployed!

Registry URL: {{ $registryUrl }}

To access the services:

1. Registry:
   {{- if .Values.registry.ingress.enabled }}
   URL: http://{{ (index .Values.registry.ingress.hosts 0).host }}
   {{- else }}
   kubectl port-forward -n {{ .Release.Namespace }} svc/{{ .Release.Name }}-mcp-mesh-registry 8080:8080
   {{- end }}

2. Grafana Dashboard:
   {{- if .Values.monitoring.grafana.enabled }}
   kubectl port-forward -n {{ .Release.Namespace }} svc/{{ .Release.Name }}-grafana 3000:80
   Username: admin
   Password: {{ .Values.monitoring.grafana.adminPassword }}
   {{- end }}

3. Prometheus:
   {{- if .Values.monitoring.prometheus.enabled }}
   kubectl port-forward -n {{ .Release.Namespace }} svc/{{ .Release.Name }}-prometheus-server 9090:80
   {{- end }}

Deployed Agents:
{{- if .Values.agents.weather.enabled }}
- Weather Agent: {{ .Values.agents.weather.replicaCount }} replicas
{{- end }}
{{- if .Values.agents.analytics.enabled }}
- Analytics Agent: {{ .Values.agents.analytics.replicaCount }} replicas
{{- end }}
{{- if .Values.agents.notification.enabled }}
- Notification Agent: {{ .Values.agents.notification.replicaCount }} replicas
{{- end }}

To check platform status:
  helm status {{ .Release.Name }} -n {{ .Release.Namespace }}

To view all platform resources:
  kubectl get all -n {{ .Release.Namespace }} -l app.kubernetes.io/part-of=mcp-mesh-platform
```

## Configuration Options

| Section        | Key             | Description                   | Default |
| -------------- | --------------- | ----------------------------- | ------- |
| `global`       | `imageRegistry` | Override all image registries | ""      |
| `registry`     | `enabled`       | Deploy registry               | true    |
| `postgresql`   | `enabled`       | Deploy PostgreSQL             | true    |
| `agents.*`     | `enabled`       | Enable specific agents        | varies  |
| `monitoring.*` | `enabled`       | Enable monitoring components  | false   |

## Examples

### Example 1: Minimal Platform Deployment

```yaml
# values-minimal.yaml
# Deploy only registry and one agent
registry:
  enabled: true
  replicaCount: 1
  persistence:
    enabled: false

postgresql:
  enabled: false

registry:
  database:
    type: sqlite

agents:
  weather:
    enabled: true
    replicaCount: 1
  analytics:
    enabled: false
  notification:
    enabled: false

monitoring:
  prometheus:
    enabled: false
  grafana:
    enabled: false
```

Deploy:

```bash
helm install minimal-platform ./mcp-mesh-platform -f values-minimal.yaml
```

### Example 2: Production Platform

```yaml
# values-production.yaml
global:
  imageRegistry: "myregistry.io"
  imagePullSecrets:
    - name: regcred

registry:
  enabled: true
  replicaCount: 5

  persistence:
    enabled: true
    size: 100Gi
    storageClass: fast-ssd

  resources:
    requests:
      memory: "2Gi"
      cpu: "1"
    limits:
      memory: "4Gi"
      cpu: "2"

  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values:
                  - mcp-mesh-registry
          topologyKey: kubernetes.io/hostname

postgresql:
  enabled: true
  auth:
    postgresPassword: "${POSTGRES_PASSWORD}"
  primary:
    persistence:
      size: 200Gi
      storageClass: fast-ssd
  metrics:
    enabled: true

agents:
  weather:
    enabled: true
    replicaCount: 10
    autoscaling:
      enabled: true
      minReplicas: 10
      maxReplicas: 50

  analytics:
    enabled: true
    replicaCount: 20
    persistence:
      enabled: true
      size: 1Ti
      storageClass: standard

monitoring:
  prometheus:
    enabled: true
    server:
      persistentVolume:
        size: 100Gi
      retention: "30d"

  grafana:
    enabled: true
    persistence:
      enabled: true
      size: 20Gi
```

## Best Practices

1. **Use Dependency Conditions**: Make components optional with conditions
2. **Global Values**: Share common configuration in global section
3. **Value Validation**: Add schema validation for complex values
4. **Atomic Deployments**: Use `--atomic` flag for all-or-nothing deploys
5. **Version Lock**: Pin all dependency versions for reproducibility

## Common Pitfalls

### Pitfall 1: Circular Dependencies

**Problem**: Charts depend on each other causing deadlock

**Solution**: Design clear dependency hierarchy:

```yaml
# Good: Clear hierarchy
postgresql -> registry -> agents

# Bad: Circular dependency
agentA -> agentB -> agentA
```

### Pitfall 2: Value Conflicts

**Problem**: Sub-chart values override each other

**Solution**: Use proper nesting:

```yaml
# Correct: Each chart has its own section
weather-agent:
  agent:
    name: weather

analytics-agent:
  agent:
    name: analytics
```

## Testing

### Test Platform Deployment

```bash
#!/bin/bash
# test-platform.sh

NAMESPACE="mcp-mesh-test"

echo "Testing platform deployment..."

# Create namespace
kubectl create namespace $NAMESPACE

# Dry run first
helm install test-platform ./mcp-mesh-platform \
  --namespace $NAMESPACE \
  --dry-run --debug

# Install with atomic flag
helm install test-platform ./mcp-mesh-platform \
  --namespace $NAMESPACE \
  --atomic \
  --timeout 10m

# Wait for all pods
kubectl wait --for=condition=ready pod --all -n $NAMESPACE --timeout=300s

# Run tests
helm test test-platform -n $NAMESPACE

# Cleanup
helm uninstall test-platform -n $NAMESPACE
kubectl delete namespace $NAMESPACE
```

### Validate Platform Health

```python
# test_platform_health.py
import requests
import kubernetes
from kubernetes import client, config

def test_platform_components():
    """Verify all platform components are healthy"""
    config.load_kube_config()
    v1 = client.CoreV1Api()

    namespace = "mcp-mesh"

    # Check registry
    registry_pods = v1.list_namespaced_pod(
        namespace,
        label_selector="app.kubernetes.io/name=mcp-mesh-registry"
    )
    assert len(registry_pods.items) >= 1
    assert all(p.status.phase == "Running" for p in registry_pods.items)

    # Check agents
    for agent in ["weather", "analytics", "notification"]:
        agent_pods = v1.list_namespaced_pod(
            namespace,
            label_selector=f"app.kubernetes.io/name={agent}-agent"
        )
        assert len(agent_pods.items) >= 1

    # Check monitoring
    prometheus_pods = v1.list_namespaced_pod(
        namespace,
        label_selector="app.kubernetes.io/name=prometheus"
    )
    assert len(prometheus_pods.items) >= 1

    print("All platform components healthy!")

if __name__ == "__main__":
    test_platform_components()
```

## Monitoring and Debugging

### Monitor Platform Deployment

```bash
# Watch deployment progress
watch -n 2 'helm status test-platform -n mcp-mesh'

# View all platform resources
kubectl get all -n mcp-mesh -l app.kubernetes.io/part-of=mcp-mesh-platform

# Check dependency status
helm dependency list ./mcp-mesh-platform

# View rendered templates
helm template test-platform ./mcp-mesh-platform | less
```

### Debug Deployment Issues

```bash
# Check events
kubectl get events -n mcp-mesh --sort-by='.lastTimestamp'

# View helm release details
helm get all test-platform -n mcp-mesh

# Check values being used
helm get values test-platform -n mcp-mesh

# Debug specific subchart
helm template test-platform ./mcp-mesh-platform \
  --show-only charts/mcp-mesh-registry/templates/statefulset.yaml
```

## 🔧 Troubleshooting

### Issue 1: Dependency Download Failures

**Symptoms**: `Error: failed to download "postgresql"`

**Cause**: Repository not added or network issues

**Solution**:

```bash
# Add required repositories
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Update dependencies
helm dependency update ./mcp-mesh-platform
```

### Issue 2: Resource Conflicts

**Symptoms**: `Error: rendered manifests contain a resource that already exists`

**Cause**: Previous installation remnants

**Solution**:

```bash
# Check existing resources
kubectl get all -n mcp-mesh -l app.kubernetes.io/managed-by=Helm

# Force upgrade
helm upgrade --install test-platform ./mcp-mesh-platform \
  --force \
  --namespace mcp-mesh
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Large Deployments**: May hit ConfigMap size limits with many agents
- **Cross-Namespace**: Umbrella charts work best in single namespace
- **Dependency Versions**: Must manually update subchart versions
- **Values Complexity**: Deep nesting can be hard to manage

## 📝 TODO

- [ ] Add backup/restore jobs to platform
- [ ] Create platform operator for dynamic agent management
- [ ] Add service mesh integration
- [ ] Document disaster recovery procedures
- [ ] Add cost optimization configurations

## Summary

You can now deploy the complete MCP Mesh platform with an umbrella chart:

Key takeaways:

- 🔑 Single chart deploys entire platform
- 🔑 Dependencies managed automatically
- 🔑 Flexible configuration through values
- 🔑 Production-ready with monitoring included

## Next Steps

Let's explore customizing deployments with values files.

Continue to [Customizing Values](./03-customizing-values.md) →

---

💡 **Tip**: Use `helm dependency build` instead of `update` to use local Chart.lock file for reproducible builds

📚 **Reference**: [Helm Dependencies Documentation](https://helm.sh/docs/helm/helm_dependency/)

🧪 **Try It**: Create a custom platform chart that includes your own agents alongside the standard ones
