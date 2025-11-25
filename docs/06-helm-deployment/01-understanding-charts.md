---
render_with_liquid: false
---

# Understanding MCP Mesh Helm Charts

> Learn the structure and components of MCP Mesh Helm charts

## Overview

MCP Mesh provides two primary Helm charts: `mcp-mesh-registry` for the central registry service and `mcp-mesh-agent` for deploying agents. This guide explains the chart structure, templates, values, and how to use them effectively. Understanding these charts is essential for customizing deployments and creating your own agent charts.
We'll explore each component, explain the templating patterns used, and show how to extend the charts for your specific needs.

## Key Concepts

- **Chart Structure**: Standard Helm chart layout and files
- **Templates**: Go templating for Kubernetes manifests
- **Values**: Configuration options and defaults
- **Helpers**: Reusable template functions
- **Dependencies**: Chart relationships and requirements

## Step-by-Step Guide

### Step 1: Explore Chart Structure

Both MCP Mesh charts follow standard Helm conventions:

```
mcp-mesh-registry/
├── Chart.yaml              # Chart metadata
├── values.yaml             # Default configuration
├── templates/              # Kubernetes manifests
│   ├── _helpers.tpl        # Template helpers
│   ├── statefulset.yaml    # 🎯 StatefulSet (not Deployment)
│   ├── service.yaml        # Service definition
│   ├── service-headless.yaml  # 🎯 Headless service for StatefulSet
│   ├── configmap.yaml      # Configuration
│   ├── secret.yaml         # Sensitive data
│   ├── ingress.yaml        # Ingress rules
│   ├── hpa.yaml            # Autoscaling
│   └── NOTES.txt           # Post-install notes
└── README.md              # Chart documentation
```

### Step 2: Registry Chart Deep Dive

🎯 **Updated**: The registry chart now uses StatefulSet (matches working K8s examples) for data persistence and proper service discovery:

```yaml
# mcp-mesh-registry/templates/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {% raw %}{{ include "mcp-mesh-registry.fullname" . }}{% endraw %}
  labels:
    {% raw %}{{- include "mcp-mesh-registry.labels" . | nindent 4 }}{% endraw %}
spec:
  serviceName: {% raw %}{{ include "mcp-mesh-registry.fullname" . }}{% endraw %}-headless
  replicas: {% raw %}{{ .Values.replicaCount }}{% endraw %}
  selector:
    matchLabels:
      {% raw %}{{- include "mcp-mesh-registry.selectorLabels" . | nindent 6 }}{% endraw %}
  template:
    metadata:
      annotations:
        checksum/config: {% raw %}{{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}{% endraw %}
        {% raw %}{{- with .Values.podAnnotations }}{% endraw %}
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
      labels:
        {% raw %}{{- include "mcp-mesh-registry.selectorLabels" . | nindent 8 }}{% endraw %}
    spec:
      serviceAccountName: {% raw %}{{ include "mcp-mesh-registry.serviceAccountName" . }}{% endraw %}
      securityContext:
        {% raw %}{{- toYaml .Values.podSecurityContext | nindent 8 }}{% endraw %}
      containers:
      - name: {% raw %}{{ .Chart.Name }}{% endraw %}
        securityContext:
          {% raw %}{{- toYaml .Values.securityContext | nindent 12 }}{% endraw %}
        image: "{% raw %}{{ .Values.image.repository }}{% endraw %}:{% raw %}{{ .Values.image.tag | default .Chart.AppVersion }}{% endraw %}"
        imagePullPolicy: {% raw %}{{ .Values.image.pullPolicy }}{% endraw %}
        command: ["/app/bin/registry"]  # 🎯 Matches working examples
        ports:
        - name: http
          containerPort: {% raw %}{{ .Values.registry.port }}{% endraw %}  # 🎯 Default 8000
          protocol: TCP
        - name: metrics
          containerPort: 9090
          protocol: TCP
        env:
        # 🎯 Pod information for registry
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        {% raw %}{{- if ne .Values.registry.database.type "sqlite" }}{% endraw %}
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {% raw %}{{ include "mcp-mesh-registry.fullname" . }}{% endraw %}-secret
              key: database-password
        {% raw %}{{- end }}{% endraw %}
        envFrom:
        - configMapRef:
            name: {% raw %}{{ include "mcp-mesh-registry.fullname" . }}{% endraw %}-config  # 🎯 Updated naming
        livenessProbe:
          httpGet:
            path: /health  # 🎯 Consistent health endpoint
            port: http
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health  # 🎯 Updated to match working examples
            port: http
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        startupProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 30
        resources:
          {% raw %}{{- toYaml .Values.resources | nindent 12 }}{% endraw %}
        volumeMounts:
        - name: data
          mountPath: /data
        {% raw %}{{- if .Values.extraVolumeMounts }}{% endraw %}
        {% raw %}{{- toYaml .Values.extraVolumeMounts | nindent 8 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
      {% raw %}{{- with .Values.nodeSelector }}{% endraw %}
      nodeSelector:
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
      {% raw %}{{- with .Values.affinity }}{% endraw %}
      affinity:
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
      {% raw %}{{- with .Values.tolerations }}{% endraw %}
      tolerations:
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
  {% raw %}{{- if .Values.persistence.enabled }}{% endraw %}
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: {% raw %}{{ .Values.persistence.accessModes }}{% endraw %}
      storageClassName: {% raw %}{{ .Values.persistence.storageClassName }}{% endraw %}
      resources:
        requests:
          storage: {% raw %}{{ .Values.persistence.size }}{% endraw %}
  {% raw %}{{- end }}{% endraw %}
```

### Step 3: Agent Chart Deep Dive

The agent chart is more flexible, supporting various agent configurations:

```yaml
# mcp-mesh-agent/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {% raw %}{{ include "mcp-mesh-agent.fullname" . }}{% endraw %}
  labels:
    {% raw %}{{- include "mcp-mesh-agent.labels" . | nindent 4 }}{% endraw %}
spec:
  replicas: {% raw %}{{ .Values.replicaCount }}{% endraw %}
  selector:
    matchLabels:
      {% raw %}{{- include "mcp-mesh-agent.selectorLabels" . | nindent 6 }}{% endraw %}
  template:
    metadata:
      annotations:
        {% raw %}{{- if .Values.agent.configMap }}{% endraw %}
        checksum/config: {% raw %}{{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- with .Values.podAnnotations }}{% endraw %}
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
      labels:
        {% raw %}{{- include "mcp-mesh-agent.selectorLabels" . | nindent 8 }}{% endraw %}
        {% raw %}{{- with .Values.agent.labels }}{% endraw %}
        {% raw %}{{- toYaml . | nindent 8 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
    spec:
      serviceAccountName: {% raw %}{{ include "mcp-mesh-agent.serviceAccountName" . }}{% endraw %}
      securityContext:
        {% raw %}{{- toYaml .Values.podSecurityContext | nindent 8 }}{% endraw %}
      {% raw %}{{- if .Values.agent.initContainers }}{% endraw %}
      initContainers:
        {% raw %}{{- toYaml .Values.agent.initContainers | nindent 8 }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
      containers:
      - name: {% raw %}{{ .Chart.Name }}{% endraw %}
        securityContext:
          {% raw %}{{- toYaml .Values.securityContext | nindent 12 }}{% endraw %}
        image: "{% raw %}{{ .Values.image.repository }}{% endraw %}:{% raw %}{{ .Values.image.tag | default .Chart.AppVersion }}{% endraw %}"
        imagePullPolicy: {% raw %}{{ .Values.image.pullPolicy }}{% endraw %}
        command: ["python", "/app/agent.py"]  # 🎯 Matches working examples
        ports:
        - name: http
          containerPort: {% raw %}{{ .Values.agent.http.port | default 8080 }}{% endraw %}  # 🎯 Standard port 8080
          protocol: TCP
        {% raw %}{{- if .Values.metrics.enabled }}{% endraw %}
        - name: metrics
          containerPort: 9090
          protocol: TCP
        {% raw %}{{- end }}{% endraw %}
        env:
        - name: AGENT_NAME
          value: {% raw %}{{ .Values.agent.name | quote }}{% endraw %}
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: MCP_MESH_REGISTRY_URL
          value: {% raw %}{{ .Values.agent.registryUrl | quote }}{% endraw %}
        {% raw %}{{- if .Values.agent.capabilities }}{% endraw %}
        - name: MCP_MESH_CAPABILITIES
          value: {% raw %}{{ .Values.agent.capabilities | join "," | quote }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- if .Values.agent.dependencies }}{% endraw %}
        - name: MCP_MESH_DEPENDENCIES
          value: {% raw %}{{ .Values.agent.dependencies | join "," | quote }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- range $key, $value := .Values.agent.env }}{% endraw %}
        - name: {% raw %}{{ $key }}{% endraw %}
          value: {% raw %}{{ $value | quote }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- if or .Values.agent.configMap .Values.agent.secret }}{% endraw %}
        envFrom:
        {% raw %}{{- if .Values.agent.configMap }}{% endraw %}
        - configMapRef:
            name: {% raw %}{{ include "mcp-mesh-agent.fullname" . }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- if .Values.agent.secret }}{% endraw %}
        - secretRef:
            name: {% raw %}{{ include "mcp-mesh-agent.fullname" . }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- if .Values.agent.livenessProbe }}{% endraw %}
        livenessProbe:
          {% raw %}{{- toYaml .Values.agent.livenessProbe | nindent 10 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        {% raw %}{{- if .Values.agent.readinessProbe }}{% endraw %}
        readinessProbe:
          {% raw %}{{- toYaml .Values.agent.readinessProbe | nindent 10 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
        resources:
          {% raw %}{{- toYaml .Values.resources | nindent 12 }}{% endraw %}
        {% raw %}{{- if .Values.agent.volumeMounts }}{% endraw %}
        volumeMounts:
          {% raw %}{{- toYaml .Values.agent.volumeMounts | nindent 10 }}{% endraw %}
        {% raw %}{{- end }}{% endraw %}
      {% raw %}{{- if .Values.agent.volumes }}{% endraw %}
      volumes:
        {% raw %}{{- toYaml .Values.agent.volumes | nindent 8 }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
```

### Step 4: Understanding Template Helpers

Helper functions provide consistency across templates:

```yaml
# templates/_helpers.tpl
{{/*
Expand the name of the chart.
*/}}
{% raw %}{{- define "mcp-mesh-registry.name" -}}{% endraw %}
{% raw %}{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}{% endraw %}
{% raw %}{{- end }}{% endraw %}

{{/*
Create a default fully qualified app name.
*/}}
{% raw %}{{- define "mcp-mesh-registry.fullname" -}}{% endraw %}
{% raw %}{{- if .Values.fullnameOverride }}{% endraw %}
{% raw %}{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}{% endraw %}
{% raw %}{{- else }}{% endraw %}
{% raw %}{{- $name := default .Chart.Name .Values.nameOverride }}{% endraw %}
{% raw %}{{- if contains $name .Release.Name }}{% endraw %}
{% raw %}{{- .Release.Name | trunc 63 | trimSuffix "-" }}{% endraw %}
{% raw %}{{- else }}{% endraw %}
{% raw %}{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
{% raw %}{{- end }}{% endraw %}

{{/*
Common labels
*/}}
{% raw %}{{- define "mcp-mesh-registry.labels" -}}{% endraw %}
helm.sh/chart: {% raw %}{{ include "mcp-mesh-registry.chart" . }}{% endraw %}
{% raw %}{{ include "mcp-mesh-registry.selectorLabels" . }}{% endraw %}
{% raw %}{{- if .Chart.AppVersion }}{% endraw %}
app.kubernetes.io/version: {% raw %}{{ .Chart.AppVersion | quote }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
app.kubernetes.io/managed-by: {% raw %}{{ .Release.Service }}{% endraw %}
{% raw %}{{- end }}{% endraw %}

{{/*
Selector labels
*/}}
{% raw %}{{- define "mcp-mesh-registry.selectorLabels" -}}{% endraw %}
app.kubernetes.io/name: {% raw %}{{ include "mcp-mesh-registry.name" . }}{% endraw %}
app.kubernetes.io/instance: {% raw %}{{ .Release.Name }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
```

### Step 5: Values File Structure

Understanding the values structure helps with customization:

```yaml
# values.yaml structure
# Global settings
global:
  imageRegistry: ""
  imagePullSecrets: []

# Image configuration (updated to match working examples)
image:
  repository: mcp-mesh-base  # 🎯 Updated from mcp-mesh/registry
  tag: "0.6.2"  # 🎯 Updated for local development
  pullPolicy: Never  # 🎯 For local development

# Deployment settings
replicaCount: 1
updateStrategy:
  type: RollingUpdate

# Pod configuration
podAnnotations: {}
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 65534

# Container configuration
securityContext:
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true

# Service configuration (updated ports)
service:
  type: ClusterIP
  port: 8000  # 🎯 Registry uses port 8000
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: "/metrics"

# Ingress configuration
ingress:
  enabled: false
  className: nginx
  hosts:
    - host: mcp-mesh.example.com
      paths:
        - path: /
          pathType: Prefix

# Resource limits
resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi

# Autoscaling
autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80

# Registry-specific configuration (updated to match working examples)
registry:
  host: "0.0.0.0"
  port: 8000  # 🎯 Updated from 8080 to 8000
  database:
    type: postgres  # 🎯 Default to postgres like working examples
    host: "mcp-mesh-postgres"
    port: 5432
    name: "mcpmesh"
    username: "mcpmesh"
    path: /data/registry.db  # For SQLite fallback

# Agent-specific configuration (updated to match working examples)
agent:
  name: "hello-world"  # 🎯 Default agent name
  script: "/app/agent.py"  # 🎯 Updated path
  http:
    enabled: true
    port: 8080  # 🎯 Standard agent port
    host: "0.0.0.0"
  capabilities:
    - greeting
    - translation
  dependencies:
    - dictionary-service
    - cache-service

# Registry configuration for agents
registry:
  host: "mcp-mesh-registry"
  port: "8000"
  url: "http://mcp-mesh-registry:8000"

# Mesh configuration
mesh:
  enabled: true
  debug: false
  logLevel: "INFO"
```

## Configuration Options

| Section        | Key          | Description        | Default (Updated) |
| -------------- | ------------ | ------------------ | ----------------- |
| `image`        | `repository` | Container image    | mcp-mesh-base     |
| `image`        | `tag`        | Image version      | 0.5               |
| `image`        | `pullPolicy` | Pull policy        | Never             |
| `replicaCount` | -            | Number of replicas | 1                 |
| `service`      | `type`       | Service type       | ClusterIP         |
| `service`      | `port`       | Service port       | 8000 (registry)   |
| `agent.http`   | `port`       | Agent HTTP port    | 8080 (agents)     |
| `persistence`  | `enabled`    | Enable PVC         | true              |
| `persistence`  | `size`       | Volume size        | 5Gi               |

## Examples

### Example 1: Custom Agent Chart

Create your own agent chart based on mcp-mesh-agent:

```yaml
# my-weather-agent/Chart.yaml
apiVersion: v2
name: weather-agent
description: Weather service agent for MCP Mesh
type: application
version: 1.0.0
appVersion: "1.0.0"
dependencies:
  - name: mcp-mesh-agent
    version: "0.6.2"
    repository: "https://charts.mcp-mesh.io"
```

Override values:

```yaml
# my-weather-agent/values.yaml (updated to match new chart structure)
mcp-mesh-agent:
  agent:
    name: weather-service
    http:
      enabled: true
      port: 8080
    capabilities:
      - weather_forecast
      - weather_history
    dependencies:
      - location_service
  registry:
    host: "mcp-mesh-registry"
    port: "8000"
  mesh:
    enabled: true
    logLevel: "INFO"
  env:
    API_KEY: "your-weather-api-key"
    CACHE_TTL: "3600"
```

### Example 2: Template Customization

Add custom templates to extend functionality:

```yaml
# templates/custom-job.yaml
{% raw %}{{- if .Values.agent.migrations.enabled }}{% endraw %}
apiVersion: batch/v1
kind: Job
metadata:
  name: {% raw %}{{ include "mcp-mesh-agent.fullname" . }}{% endraw %}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-1"
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: "{% raw %}{{ .Values.image.repository }}{% endraw %}:{% raw %}{{ .Values.image.tag }}{% endraw %}"
        command: ["python", "-m", "migrations.run"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: {% raw %}{{ include "mcp-mesh-agent.fullname" . }}{% endraw %}
              key: database-url
{% raw %}{{- end }}{% endraw %}
```

## Best Practices

1. **Use Subchart Pattern**: Create specific charts that depend on base charts
2. **Template Everything**: Avoid hardcoded values in templates
3. **Validate Values**: Use JSON schema for values validation
4. **Document Options**: Include comprehensive values documentation
5. **Test Templates**: Use `helm template` to verify output

## Common Pitfalls

### Pitfall 1: Incorrect Indentation

**Problem**: YAML indentation errors in templates

**Solution**: Use nindent for consistent indentation:

```yaml
labels: { { - include "mcp-mesh-agent.labels" . | nindent 4 } }
```

### Pitfall 2: Missing Quotes

**Problem**: Special characters breaking YAML

**Solution**: Always quote string values:

```yaml
- name: { { .Values.name | quote } }
```

## Testing

### Template Testing

```bash
# Test template rendering
helm template my-release ./mcp-mesh-registry \
  --values values-test.yaml \
  --debug

# Validate against Kubernetes
helm template my-release ./mcp-mesh-registry | kubectl apply --dry-run=client -f -

# Use kubeval for validation
helm template my-release ./mcp-mesh-registry | kubeval
```

### Unit Testing with Helm

```yaml
# tests/deployment_test.yaml
suite: test deployment
templates:
  - deployment.yaml
tests:
  - it: should create deployment with correct replicas
    set:
      replicaCount: 3
    asserts:
      - equal:
          path: spec.replicas
          value: 3

  - it: should have correct image
    set:
      image.repository: custom/image
      image.tag: v2.0.0
    asserts:
      - equal:
          path: spec.template.spec.containers[0].image
          value: custom/image:v2.0.0
```

## Monitoring and Debugging

### Debug Helm Installations

```bash
# Get release values
helm get values my-release -n mcp-mesh

# Get generated manifests
helm get manifest my-release -n mcp-mesh

# Debug installation issues
helm install my-release ./mcp-mesh-registry \
  --debug \
  --dry-run

# Check hooks
helm get hooks my-release -n mcp-mesh
```

### Monitor Chart Usage

```bash
# List all releases
helm list -A

# Get release history
helm history my-release -n mcp-mesh

# Check release status
helm status my-release -n mcp-mesh
```

## 🔧 Troubleshooting

### Issue 1: Template Function Not Found

**Symptoms**: `function "x" not defined`

**Cause**: Missing or incorrectly named helper

**Solution**:

```yaml
# Ensure helper is defined in _helpers.tpl
{% raw %}{{- define "mcp-mesh-agent.name" -}}{% endraw %}
{% raw %}{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}{% endraw %}
{% raw %}{{- end }}{% endraw %}

# Use correct name in template
{% raw %}{{ include "mcp-mesh-agent.name" . }}{% endraw %}
```

### Issue 2: Values Not Propagating

**Symptoms**: Default values used instead of custom values

**Cause**: Incorrect values path or missing defaults

**Solution**:

```yaml
# Use default function
value: {% raw %}{{ .Values.agent.port | default 8080 }}{% endraw %}

# Check values path
helm get values my-release -n mcp-mesh
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **ConfigMap Size**: Limited to 1MB for values
- **Template Complexity**: Go templates can be hard to debug
- **CRD Handling**: CRDs need special treatment in Helm 3
- **Nested Dependencies**: Limited to one level of dependencies

## 📝 TODO

- [ ] Add JSON schema for values validation
- [ ] Create chart testing CI pipeline
- [ ] Add more helper functions
- [ ] Document advanced templating patterns
- [ ] Create chart development guide

## Summary

You now understand the updated structure and components of MCP Mesh Helm charts:

Key takeaways:

- 🔑 **Registry chart**: Uses StatefulSet with port 8000, matches working K8s examples
- 🔑 **Agent chart**: Includes automatic service discovery from `app.kubernetes.io/name` labels
- 🔑 **Service discovery**: Auto-detects SERVICE_NAME and NAMESPACE from Kubernetes metadata
- 🔑 **Image consistency**: Both charts use `mcp-mesh-base:0.2` with `Never` pull policy
- 🔑 **Port standardization**: Registry=8000, Agents=8080
- 🔑 **Health endpoints**: All use `/health` for startup, liveness, and readiness probes

## Next Steps

Let's create a platform umbrella chart to deploy everything together.

Continue to [Platform Umbrella Chart](./02-umbrella-chart.md) →

---

💡 **Tip**: Use `helm lint` to check your charts for common issues before deployment

📚 **Reference**: [Helm Chart Best Practices](https://helm.sh/docs/chart_best_practices/)

🧪 **Try It**: Create a custom chart for your agent that extends the base mcp-mesh-agent chart
