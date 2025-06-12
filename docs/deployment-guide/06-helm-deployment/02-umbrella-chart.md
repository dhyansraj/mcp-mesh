# Platform Umbrella Chart

> Deploy the complete MCP Mesh platform with a single Helm chart

## Overview

An umbrella chart (also called a meta-chart) combines multiple charts into a single deployable unit. The MCP Mesh platform umbrella chart orchestrates the deployment of the registry, multiple agents, and supporting infrastructure with a single `helm install` command. This guide shows how to create and use umbrella charts for consistent platform deployments.

We'll build a complete platform chart that includes the registry, several agents, monitoring components, and proper dependency management.

## Key Concepts

- **Umbrella Charts**: Parent charts that include other charts as dependencies
- **Dependency Management**: Controlling deployment order and relationships
- **Value Propagation**: Passing configuration to sub-charts
- **Conditional Dependencies**: Enabling/disabling components
- **Alias Usage**: Deploying the same chart multiple times

## Step-by-Step Guide

### Step 1: Create Platform Chart Structure

Create a new umbrella chart:

```bash
# Create chart directory
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
maintainers:
  - name: Platform Team
    email: platform@example.com

dependencies:
  # Core components
  - name: mcp-mesh-registry
    version: "0.1.0"
    repository: "https://charts.mcp-mesh.io"
    condition: registry.enabled

  # Database for registry
  - name: postgresql
    version: "12.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled

  # Agents - using aliases for multiple instances
  - name: mcp-mesh-agent
    version: "0.1.0"
    repository: "https://charts.mcp-mesh.io"
    alias: weather-agent
    condition: agents.weather.enabled

  - name: mcp-mesh-agent
    version: "0.1.0"
    repository: "https://charts.mcp-mesh.io"
    alias: analytics-agent
    condition: agents.analytics.enabled

  - name: mcp-mesh-agent
    version: "0.1.0"
    repository: "https://charts.mcp-mesh.io"
    alias: notification-agent
    condition: agents.notification.enabled

  # Monitoring stack
  - name: prometheus
    version: "19.x.x"
    repository: "https://prometheus-community.github.io/helm-charts"
    condition: monitoring.prometheus.enabled

  - name: grafana
    version: "6.x.x"
    repository: "https://grafana.github.io/helm-charts"
    condition: monitoring.grafana.enabled
EOF
```

### Step 2: Create Platform Values

Define comprehensive platform configuration:

```yaml
# values.yaml
# Global configuration shared across all subcharts
global:
  imageRegistry: ""
  imagePullSecrets: []
  storageClass: ""

  # Shared database configuration
  postgresql:
    auth:
      postgresPassword: "changeme"
      database: "mcp_mesh"

# Registry configuration
registry:
  enabled: true
  replicaCount: 3

  image:
    repository: mcp-mesh/registry
    tag: "latest"

  persistence:
    enabled: true
    size: 20Gi

  database:
    type: postgresql
    host: "{{ .Release.Name }}-postgresql"
    port: 5432
    name: "mcp_mesh"
    username: "postgres"

  ingress:
    enabled: true
    className: nginx
    hosts:
      - host: registry.mcp-mesh.local
        paths:
          - path: /
            pathType: Prefix

  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "1Gi"
      cpu: "500m"

# PostgreSQL configuration
postgresql:
  enabled: true
  auth:
    enablePostgresUser: true
    postgresPassword: "changeme"
    database: "mcp_mesh"
  primary:
    persistence:
      enabled: true
      size: 10Gi

# Agent configurations
agents:
  # Weather service agent
  weather:
    enabled: true
    replicaCount: 2

    image:
      repository: mcp-mesh/weather-agent
      tag: "latest"

    agent:
      name: weather-service
      registryUrl: "http://{{ .Release.Name }}-mcp-mesh-registry:8080"
      capabilities:
        - weather_forecast
        - weather_current
        - weather_historical
      dependencies:
        - location_service
      env:
        WEATHER_API_KEY: "your-api-key"
        CACHE_TTL: "300"

    resources:
      requests:
        memory: "128Mi"
        cpu: "50m"
      limits:
        memory: "512Mi"
        cpu: "200m"

    autoscaling:
      enabled: true
      minReplicas: 2
      maxReplicas: 10
      targetCPUUtilizationPercentage: 70

  # Analytics agent
  analytics:
    enabled: true
    replicaCount: 3

    image:
      repository: mcp-mesh/analytics-agent
      tag: "latest"

    agent:
      name: analytics-service
      registryUrl: "http://{{ .Release.Name }}-mcp-mesh-registry:8080"
      capabilities:
        - data_aggregation
        - report_generation
        - trend_analysis
      dependencies:
        - database_service
        - cache_service
      env:
        BATCH_SIZE: "1000"
        PROCESSING_INTERVAL: "60"

    persistence:
      enabled: true
      size: 50Gi
      mountPath: /data

    resources:
      requests:
        memory: "512Mi"
        cpu: "250m"
      limits:
        memory: "2Gi"
        cpu: "1000m"

  # Notification agent
  notification:
    enabled: true
    replicaCount: 2

    image:
      repository: mcp-mesh/notification-agent
      tag: "latest"

    agent:
      name: notification-service
      registryUrl: "http://{{ .Release.Name }}-mcp-mesh-registry:8080"
      capabilities:
        - email_send
        - sms_send
        - push_notification
      dependencies:
        - template_service
        - user_service
      env:
        SMTP_HOST: "smtp.example.com"
        SMTP_PORT: "587"
      secret:
        SMTP_PASSWORD: "smtp-password"
        SMS_API_KEY: "sms-api-key"

# Monitoring configuration
monitoring:
  prometheus:
    enabled: true
    alertmanager:
      enabled: true
    server:
      persistentVolume:
        enabled: true
        size: 20Gi
      retention: "15d"

    # Scrape configs for MCP Mesh components
    extraScrapeConfigs: |
      - job_name: 'mcp-mesh-registry'
        kubernetes_sd_configs:
          - role: endpoints
            namespaces:
              names:
                - {{ .Release.Namespace }}
        relabel_configs:
          - source_labels: [__meta_kubernetes_service_name]
            regex: '.*registry.*'
            action: keep

      - job_name: 'mcp-mesh-agents'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names:
                - {{ .Release.Namespace }}
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_component]
            regex: 'agent'
            action: keep

  grafana:
    enabled: true
    adminPassword: "changeme"
    persistence:
      enabled: true
      size: 5Gi

    datasources:
      datasources.yaml:
        apiVersion: 1
        datasources:
          - name: Prometheus
            type: prometheus
            url: http://{{ .Release.Name }}-prometheus-server
            isDefault: true

    dashboardProviders:
      dashboardproviders.yaml:
        apiVersion: 1
        providers:
          - name: "mcp-mesh"
            orgId: 1
            folder: "MCP Mesh"
            type: file
            disableDeletion: false
            updateIntervalSeconds: 10
            allowUiUpdates: true
            options:
              path: /var/lib/grafana/dashboards/mcp-mesh

    dashboards:
      mcp-mesh:
        platform-overview:
          url: https://raw.githubusercontent.com/mcp-mesh/dashboards/main/platform-overview.json
        agent-metrics:
          url: https://raw.githubusercontent.com/mcp-mesh/dashboards/main/agent-metrics.json

# Network policies
networkPolicies:
  enabled: true
  # Allow traffic between agents and registry
  allowIntraNamespace: true
  # Allow ingress from specific namespaces
  allowedNamespaces:
    - ingress-nginx
    - monitoring

# Resource quotas for the namespace
resourceQuota:
  enabled: true
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    persistentvolumeclaims: "20"
    pods: "100"

# Pod disruption budgets
podDisruptionBudgets:
  enabled: true
  registry:
    minAvailable: 2
  agents:
    minAvailable: 1
```

### Step 3: Create Helper Templates

Add platform-specific helpers:

```yaml
# templates/_helpers.tpl
{{/*
Platform-wide labels
*/}}
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
```

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
```

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
