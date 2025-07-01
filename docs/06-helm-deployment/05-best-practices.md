# Helm Best Practices

> Production-ready patterns and practices for MCP Mesh Helm deployments

## Overview

This guide covers best practices for using Helm with MCP Mesh in production environments. You'll learn about chart development standards, security practices, performance optimization, and operational excellence. These practices are derived from real-world deployments and community standards.

Following these best practices ensures reliable, secure, and maintainable Helm deployments at scale.

## Key Concepts

- **Chart Standards**: Following Helm community conventions
- **Security Hardening**: Protecting deployments and secrets
- **Performance Optimization**: Efficient chart rendering and deployment
- **Operational Excellence**: Monitoring, upgrading, and troubleshooting
- **GitOps Integration**: Declarative deployment workflows

## Step-by-Step Guide

### Step 1: Chart Development Standards

Follow consistent patterns for chart development:

```yaml
# Chart.yaml - Comprehensive metadata
apiVersion: v2
name: mcp-mesh-agent
description: |
  A Helm chart for deploying MCP Mesh agents.
  This chart supports multiple agent types and configurations.
type: application
version: 1.2.3 # Chart version (SemVer)
appVersion: "1.0.0" # Application version
keywords:
  - mcp-mesh
  - microservices
  - service-mesh
home: https://github.com/mcp-mesh/charts
sources:
  - https://github.com/mcp-mesh/mcp-mesh
maintainers:
  - name: Platform Team
    email: platform@mcp-mesh.io
    url: https://mcp-mesh.io
dependencies:
  - name: common
    version: "1.x.x"
    repository: "https://charts.bitnami.com/bitnami"
annotations:
  # Chart documentation
  "artifacthub.io/readme": |
    https://raw.githubusercontent.com/mcp-mesh/charts/main/charts/mcp-mesh-agent/README.md
  # Security scanning
  "artifacthub.io/containsSecurityUpdates": "false"
  # License
  "artifacthub.io/license": "Apache-2.0"
  # Operator compatibility
  "artifacthub.io/operator": "true"
  # Recommendations
  "artifacthub.io/recommendations": |
    - url: https://charts.mcp-mesh.io/mcp-mesh-registry
```

### Step 2: Values Schema Validation

Implement JSON Schema for values validation:

```json
// values.schema.json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["agent", "image"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "description": "Number of agent replicas"
    },
    "image": {
      "type": "object",
      "required": ["repository", "tag"],
      "properties": {
        "repository": {
          "type": "string",
          "pattern": "^[a-z0-9-_/]+$",
          "description": "Container image repository"
        },
        "tag": {
          "type": "string",
          "pattern": "^[a-zA-Z0-9.-]+$",
          "description": "Container image tag"
        },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"],
          "default": "IfNotPresent"
        }
      }
    },
    "agent": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {
          "type": "string",
          "pattern": "^[a-z0-9-]+$",
          "minLength": 1,
          "maxLength": 63,
          "description": "Agent name (DNS-1123 subdomain)"
        },
        "capabilities": {
          "type": "array",
          "items": {
            "type": "string",
            "pattern": "^[a-z0-9_]+$"
          },
          "minItems": 1,
          "uniqueItems": true
        },
        "resources": {
          "type": "object",
          "properties": {
            "limits": {
              "$ref": "#/definitions/resourceRequirements"
            },
            "requests": {
              "$ref": "#/definitions/resourceRequirements"
            }
          }
        }
      }
    }
  },
  "definitions": {
    "resourceRequirements": {
      "type": "object",
      "properties": {
        "cpu": {
          "type": "string",
          "pattern": "^[0-9]+(\\.[0-9]+)?(m)?$"
        },
        "memory": {
          "type": "string",
          "pattern": "^[0-9]+(\\.[0-9]+)?(Mi|Gi)$"
        }
      }
    }
  }
}
```

### Step 3: Template Best Practices

Write maintainable and efficient templates:

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "mcp-mesh-agent.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "mcp-mesh-agent.labels" . | nindent 4 }}
    {{- with .Values.commonLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  annotations:
    {{- include "mcp-mesh-agent.annotations" . | nindent 4 }}
    {{- with .Values.commonAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  revisionHistoryLimit: {{ .Values.revisionHistoryLimit | default 10 }}
  selector:
    matchLabels:
      {{- include "mcp-mesh-agent.selectorLabels" . | nindent 6 }}
  {{- with .Values.updateStrategy }}
  strategy:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  template:
    metadata:
      annotations:
        # Force pod restart on config change
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      labels:
        {{- include "mcp-mesh-agent.selectorLabels" . | nindent 8 }}
        {{- with .Values.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "mcp-mesh-agent.serviceAccountName" . }}
      automountServiceAccountToken: {{ .Values.serviceAccount.automountToken | default false }}
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      {{- with .Values.priorityClassName }}
      priorityClassName: {{ . }}
      {{- end }}
      {{- with .Values.hostAliases }}
      hostAliases:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- if .Values.initContainers }}
      initContainers:
        {{- include "mcp-mesh-agent.renderTpl" (dict "value" .Values.initContainers "context" $) | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            {{- toYaml .Values.securityContext | nindent 12 }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          {{- with .Values.command }}
          command:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.args }}
          args:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            {{- if .Values.env }}
            {{- include "mcp-mesh-agent.renderTpl" (dict "value" .Values.env "context" $) | nindent 12 }}
            {{- end }}
          {{- if or .Values.envFrom .Values.agent.configMap .Values.agent.secret }}
          envFrom:
            {{- with .Values.envFrom }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            {{- if .Values.agent.configMap }}
            - configMapRef:
                name: {{ include "mcp-mesh-agent.fullname" . }}
            {{- end }}
            {{- if .Values.agent.secret }}
            - secretRef:
                name: {{ include "mcp-mesh-agent.fullname" . }}
            {{- end }}
          {{- end }}
          ports:
            - name: http
              containerPort: {{ .Values.agent.port | default 8080 }}
              protocol: TCP
            {{- if .Values.metrics.enabled }}
            - name: metrics
              containerPort: {{ .Values.metrics.port | default 9090 }}
              protocol: TCP
            {{- end }}
            {{- range .Values.extraPorts }}
            - name: {{ .name }}
              containerPort: {{ .port }}
              protocol: {{ .protocol | default "TCP" }}
            {{- end }}
          {{- with .Values.livenessProbe }}
          livenessProbe:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.readinessProbe }}
          readinessProbe:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.startupProbe }}
          startupProbe:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          {{- with .Values.volumeMounts }}
          volumeMounts:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.lifecycle }}
          lifecycle:
            {{- toYaml . | nindent 12 }}
          {{- end }}
        {{- with .Values.sidecars }}
        {{- include "mcp-mesh-agent.renderTpl" (dict "value" . "context" $) | nindent 8 }}
        {{- end }}
      {{- with .Values.volumes }}
      volumes:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.terminationGracePeriodSeconds }}
      terminationGracePeriodSeconds: {{ . }}
      {{- end }}
      {{- with .Values.dnsPolicy }}
      dnsPolicy: {{ . }}
      {{- end }}
      {{- with .Values.dnsConfig }}
      dnsConfig:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

### Step 4: Security Best Practices

Implement comprehensive security measures:

```yaml
# templates/podsecuritypolicy.yaml
{{- if .Values.podSecurityPolicy.enabled }}
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: {{ include "mcp-mesh-agent.fullname" . }}
  labels:
    {{- include "mcp-mesh-agent.labels" . | nindent 4 }}
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
    - ALL
  volumes:
    - 'configMap'
    - 'emptyDir'
    - 'projected'
    - 'secret'
    - 'downwardAPI'
    - 'persistentVolumeClaim'
  hostNetwork: false
  hostIPC: false
  hostPID: false
  runAsUser:
    rule: 'MustRunAsNonRoot'
  seLinux:
    rule: 'RunAsAny'
  supplementalGroups:
    rule: 'RunAsAny'
  fsGroup:
    rule: 'RunAsAny'
  readOnlyRootFilesystem: true
{{- end }}

---
# templates/networkpolicy.yaml
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "mcp-mesh-agent.fullname" . }}
  labels:
    {{- include "mcp-mesh-agent.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "mcp-mesh-agent.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow traffic from registry
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mcp-mesh-registry
      ports:
        - protocol: TCP
          port: {{ .Values.agent.port | default 8080 }}
    # Allow metrics scraping
    {{- if .Values.metrics.enabled }}
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: {{ .Values.metrics.port | default 9090 }}
    {{- end }}
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
    # Allow registry access
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mcp-mesh-registry
      ports:
        - protocol: TCP
          port: 8080
    # Allow external HTTPS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443
{{- end }}
```

### Step 5: Performance Optimization

Optimize chart rendering and deployment:

```yaml
# templates/_helpers.tpl
{{/*
Efficient helper functions with caching
*/}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
*/}}
{{- define "mcp-mesh-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Render template with caching for performance
*/}}
{{- define "mcp-mesh-agent.renderTpl" -}}
{{- $value := .value -}}
{{- $context := .context -}}
{{- if typeIs "string" $value -}}
{{- tpl $value $context -}}
{{- else -}}
{{- tpl ($value | toYaml) $context -}}
{{- end -}}
{{- end -}}

{{/*
Common labels with minimal computation
*/}}
{{- define "mcp-mesh-agent.labels" -}}
{{- if not .labels_cached }}
{{- $_ := set . "labels_cached" (dict
  "helm.sh/chart" (include "mcp-mesh-agent.chart" .)
  "app.kubernetes.io/name" (include "mcp-mesh-agent.name" .)
  "app.kubernetes.io/instance" .Release.Name
  "app.kubernetes.io/version" (.Chart.AppVersion | default "0.2" | quote)
  "app.kubernetes.io/managed-by" .Release.Service
) }}
{{- end }}
{{- range $key, $value := .labels_cached }}
{{ $key }}: {{ $value }}
{{- end }}
{{- end }}
```

### Step 6: Operational Excellence

Implement comprehensive operational practices:

```yaml
# Chart testing
# templates/tests/test-connection.yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mcp-mesh-agent.fullname" . }}-test-connection"
  labels:
    {{- include "mcp-mesh-agent.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: test-health
      image: curlimages/curl:7.85.0
      command: ['sh', '-c']
      args:
        - |
          echo "Testing agent health endpoint..."
          curl -f http://{{ include "mcp-mesh-agent.fullname" . }}:{{ .Values.agent.port | default 8080 }}/health
          echo "Testing agent readiness..."
          curl -f http://{{ include "mcp-mesh-agent.fullname" . }}:{{ .Values.agent.port | default 8080 }}/ready
          echo "Testing metrics endpoint..."
          {{- if .Values.metrics.enabled }}
          curl -f http://{{ include "mcp-mesh-agent.fullname" . }}:{{ .Values.metrics.port | default 9090 }}/metrics
          {{- end }}
          echo "All tests passed!"
  restartPolicy: Never
```

Create comprehensive documentation:

```markdown
# templates/NOTES.txt

{{- $fullName := include "mcp-mesh-agent.fullname" . -}}
✨ MCP Mesh Agent {{ .Values.agent.name }} has been deployed!

📋 Release Information:
Name: {{ .Release.Name }}
Namespace: {{ .Release.Namespace }}
Version: {{ .Chart.Version }}
Revision: {{ .Release.Revision }}

🚀 Application Details:
Agent Name: {{ .Values.agent.name }}
Replicas: {{ .Values.replicaCount }}
Image: {{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- if .Values.agent.capabilities }}
Capabilities: {{ .Values.agent.capabilities | join ", " }}
{{- end }}

📊 Resources:
CPU Request: {{ .Values.resources.requests.cpu | default "not set" }}
Memory Request: {{ .Values.resources.requests.memory | default "not set" }}
CPU Limit: {{ .Values.resources.limits.cpu | default "not set" }}
Memory Limit: {{ .Values.resources.limits.memory | default "not set" }}

🔍 Service Discovery:
Internal DNS: {{ $fullName }}.{{ .Release.Namespace }}.svc.cluster.local
Service Port: {{ .Values.service.port | default 8080 }}

{{- if .Values.ingress.enabled }}
🌐 External Access:
{{- range $host := .Values.ingress.hosts }}
{{- range .paths }}
URL: http{{ if $.Values.ingress.tls }}s{{ end }}://{{ $host.host }}{{ .path }}
{{- end }}
{{- end }}
{{- else }}
🔒 External Access: Disabled (ingress.enabled=false)
{{- end }}

{{- if .Values.autoscaling.enabled }}
📈 Autoscaling:
Min Replicas: {{ .Values.autoscaling.minReplicas }}
Max Replicas: {{ .Values.autoscaling.maxReplicas }}
Target CPU: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}%
{{- end }}

🏥 Health Checks:
Liveness: curl http://{{ $fullName }}:{{ .Values.agent.port | default 8080 }}/health
Readiness: curl http://{{ $fullName }}:{{ .Values.agent.port | default 8080 }}/ready
{{- if .Values.metrics.enabled }}
Metrics: curl http://{{ $fullName }}:{{ .Values.metrics.port | default 9090 }}/metrics
{{- end }}

📝 Common Operations:

1. Check deployment status:
   kubectl rollout status deployment/{{ $fullName }} -n {{ .Release.Namespace }}

2. View logs:
   kubectl logs -f deployment/{{ $fullName }} -n {{ .Release.Namespace }}

3. Scale deployment:
   kubectl scale deployment/{{ $fullName }} --replicas=5 -n {{ .Release.Namespace }}

4. Port forward for local access:
   kubectl port-forward deployment/{{ $fullName }} 8080:{{ .Values.agent.port | default 8080 }} -n {{ .Release.Namespace }}

5. Run tests:
   helm test {{ .Release.Name }} -n {{ .Release.Namespace }}

{{- if .Values.debug.enabled }}
⚠️ DEBUG MODE IS ENABLED - Not recommended for production!
{{- end }}

For more information, visit: https://docs.mcp-mesh.io
```

### Step 7: GitOps Integration

Integrate with GitOps workflows:

```yaml
# argocd/application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mcp-mesh-platform
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/mcp-mesh/deployments
    targetRevision: HEAD
    path: helm/mcp-mesh-platform
    helm:
      valueFiles:
        - values.yaml
        - values-production.yaml
      parameters:
        - name: image.tag
          value: "1.0.0"
  destination:
    server: https://kubernetes.default.svc
    namespace: mcp-mesh
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  revisionHistoryLimit: 10
```

## Configuration Options

| Practice          | Configuration               | Impact                       |
| ----------------- | --------------------------- | ---------------------------- |
| Schema Validation | `values.schema.json`        | Prevents misconfigurations   |
| Security Policies | `podSecurityPolicy.enabled` | Enforces security standards  |
| Network Policies  | `networkPolicy.enabled`     | Controls traffic flow        |
| Resource Limits   | `resources.limits`          | Prevents resource exhaustion |
| Monitoring        | `metrics.enabled`           | Enables observability        |

## Examples

### Example 1: Production-Ready Chart

```yaml
# values-production.yaml
# Production-ready configuration

# High availability
replicaCount: 5

# Resource management
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"

# Security hardening
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001
  seccompProfile:
    type: RuntimeDefault

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 10001
  capabilities:
    drop:
      - ALL

# Network policies
networkPolicy:
  enabled: true

# Pod disruption budget
podDisruptionBudget:
  enabled: true
  minAvailable: 2

# Monitoring
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s

# Health checks
livenessProbe:
  httpGet:
    path: /health
    port: http
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 5

readinessProbe:
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

# Autoscaling
autoscaling:
  enabled: true
  minReplicas: 5
  maxReplicas: 50
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

### Example 2: Chart Lifecycle Management

```bash
#!/bin/bash
# chart-lifecycle.sh

# Lint chart
echo "Linting chart..."
helm lint ./mcp-mesh-agent

# Package chart
echo "Packaging chart..."
helm package ./mcp-mesh-agent

# Test chart
echo "Testing chart..."
helm install test-release ./mcp-mesh-agent \
  --dry-run --debug \
  --generate-name

# Security scan
echo "Security scanning..."
helm template ./mcp-mesh-agent | \
  kubesec scan -

# Sign chart
echo "Signing chart..."
helm gpg sign ./mcp-mesh-agent-*.tgz

# Push to registry
echo "Pushing to registry..."
helm push mcp-mesh-agent-*.tgz oci://registry.mcp-mesh.io/charts
```

## Best Practices

1. **Use Subcharts**: Create modular, reusable components
2. **Version Everything**: Pin all versions (charts, images, dependencies)
3. **Test Thoroughly**: Unit tests, integration tests, upgrade tests
4. **Document Extensively**: README, NOTES.txt, inline comments
5. **Secure by Default**: Minimal permissions, network policies

## Common Pitfalls

### Pitfall 1: Hardcoded Values

**Problem**: Values hardcoded in templates

**Solution**: Always parameterize:

```yaml
# Bad
image: mcp-mesh/agent:1.0.0

# Good
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
```

### Pitfall 2: Missing Resource Limits

**Problem**: Pods without resource constraints

**Solution**: Always set defaults:

```yaml
# values.yaml
resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi
```

## Testing

### Chart Unit Testing

```yaml
# tests/deployment_test.yaml
suite: test deployment
templates:
  - deployment.yaml
tests:
  - it: should create deployment with correct name
    asserts:
      - isKind:
          of: Deployment
      - equal:
          path: metadata.name
          value: RELEASE-NAME-mcp-mesh-agent

  - it: should have security context
    asserts:
      - isNotNull:
          path: spec.template.spec.securityContext
      - equal:
          path: spec.template.spec.securityContext.runAsNonRoot
          value: true

  - it: should have resource limits
    asserts:
      - isNotNull:
          path: spec.template.spec.containers[0].resources.limits
      - exists:
          path: spec.template.spec.containers[0].resources.limits.memory
```

### Integration Testing

```python
# test_helm_deployment.py
import subprocess
import json
import time
import pytest

def helm_install(release_name, namespace):
    """Install Helm chart"""
    cmd = [
        "helm", "install", release_name, "./mcp-mesh-agent",
        "--namespace", namespace,
        "--create-namespace",
        "--wait",
        "--timeout", "5m"
    ]
    subprocess.run(cmd, check=True)

def test_production_deployment():
    """Test production-ready deployment"""
    namespace = "test-prod"
    release = "test-release"

    try:
        # Install with production values
        helm_install(release, namespace)

        # Verify deployment
        cmd = f"kubectl get deployment -n {namespace} -o json"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        deployments = json.loads(result.stdout)

        assert len(deployments['items']) > 0

        # Check security context
        deployment = deployments['items'][0]
        security_context = deployment['spec']['template']['spec']['securityContext']
        assert security_context['runAsNonRoot'] is True

        # Check resource limits
        containers = deployment['spec']['template']['spec']['containers']
        assert all('resources' in c and 'limits' in c['resources']
                  for c in containers)

    finally:
        # Cleanup
        subprocess.run([
            "helm", "uninstall", release, "-n", namespace
        ])
```

## Monitoring and Debugging

### Monitor Chart Performance

```bash
# Measure template rendering time
time helm template large-release ./mcp-mesh-platform \
  -f values-production.yaml > /dev/null

# Check rendered size
helm template large-release ./mcp-mesh-platform \
  -f values-production.yaml | wc -c

# Profile template execution
helm template large-release ./mcp-mesh-platform \
  --debug 2>&1 | grep -E "took|duration"
```

### Debug Chart Issues

```bash
# Enable debug output
helm install my-release ./mcp-mesh-agent \
  --debug \
  --dry-run

# Check computed values
helm get values my-release --all

# Verify hooks
helm get hooks my-release

# List all resources
helm get manifest my-release | kubectl get -f -
```

## 🔧 Troubleshooting

### Issue 1: Schema Validation Failures

**Symptoms**: `values don't meet the specifications of the schema`

**Cause**: Values don't match schema

**Solution**:

```bash
# Validate values against schema
helm lint ./mcp-mesh-agent --strict

# Test specific values file
helm template ./mcp-mesh-agent \
  -f values-custom.yaml \
  --validate
```

### Issue 2: Template Rendering Slow

**Symptoms**: Long deployment times

**Cause**: Inefficient templates

**Solution**:

```yaml
# Cache computed values
{{- $fullname := include "chart.fullname" . -}}
{{- $labels := include "chart.labels" . -}}

# Reuse throughout template
name: {{ $fullname }}
labels:
  {{- $labels | nindent 4 }}
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **ConfigMap Size**: Limited to 1MB for rendered templates
- **CRD Ordering**: CRDs must be installed before use
- **Hooks Limitations**: Limited hook weights (pre/post)
- **Cross-Namespace**: Helm doesn't manage cross-namespace resources well

## 📝 TODO

- [ ] Add mutation webhook examples
- [ ] Create Helm plugin for MCP Mesh
- [ ] Document OPA policy integration
- [ ] Add cost optimization practices
- [ ] Create security scanning automation

## Summary

You now understand Helm best practices for production:

Key takeaways:

- 🔑 Follow chart development standards
- 🔑 Implement comprehensive security
- 🔑 Optimize performance
- 🔑 Test thoroughly at all levels

## Next Steps

Return to the Helm deployment overview or explore troubleshooting.

Continue to [Troubleshooting Guide](./troubleshooting.md) →

---

💡 **Tip**: Use `helm create` with a custom starter: `helm create mychart --starter mcp-mesh-starter`

📚 **Reference**: [Helm Best Practices Guide](https://helm.sh/docs/chart_best_practices/)

🧪 **Try It**: Create a production-ready chart for your own agent following these practices
