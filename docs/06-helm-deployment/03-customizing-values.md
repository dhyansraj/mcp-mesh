# Customizing Values

> Master Helm values management for flexible MCP Mesh deployments

## Overview

Helm values files are the key to customizing deployments without modifying charts. This guide covers advanced techniques for managing values across environments, organizing complex configurations, using templating within values, and implementing security best practices. You'll learn how to structure values for maintainability and create reusable configuration patterns.

Proper values management is crucial for maintaining consistent deployments across development, staging, and production environments.

## Key Concepts

- **Values Hierarchy**: How Helm merges multiple values files
- **Value Templates**: Using Go templates in values
- **Environment Separation**: Managing environment-specific configs
- **Secrets Management**: Secure handling of sensitive values
- **Values Validation**: Ensuring configuration correctness

## Step-by-Step Guide

### Step 1: Understanding Values Precedence

Helm merges values in a specific order (later overrides earlier):

```bash
# Order of precedence (lowest to highest):
1. Chart's default values.yaml
2. Parent chart's values
3. Values files (-f flag) in order
4. Individual --set flags

# Example showing precedence
helm install my-release ./chart \
  -f values-base.yaml \           # 2nd priority
  -f values-production.yaml \     # 3rd priority
  --set image.tag=v2.0.0         # Highest priority
```

### Step 2: Structure Values for Maintainability

Organize values files hierarchically:

```
values/
├── base/
│   ├── values.yaml          # Base configuration
│   ├── monitoring.yaml      # Monitoring settings
│   └── security.yaml        # Security policies
├── environments/
│   ├── development.yaml     # Dev overrides
│   ├── staging.yaml         # Staging overrides
│   └── production.yaml      # Prod overrides
├── agents/
│   ├── weather.yaml         # Weather agent config
│   ├── analytics.yaml       # Analytics agent config
│   └── notification.yaml    # Notification agent config
└── secrets/
    ├── dev-secrets.yaml     # Dev secrets (encrypted)
    ├── staging-secrets.yaml # Staging secrets
    └── prod-secrets.yaml    # Prod secrets
```

Base values file:

```yaml
# values/base/values.yaml
# Common configuration across all environments

global:
  # Organization-wide settings
  organization: "mcp-mesh-corp"
  domain: "mcp-mesh.io"

  # Common labels
  labels:
    team: "platform"
    project: "mcp-mesh"
    costCenter: "engineering"

  # Default resource constraints
  resources:
    defaults:
      requests:
        memory: "128Mi"
        cpu: "100m"
      limits:
        memory: "512Mi"
        cpu: "500m"

# Registry defaults
registry:
  enabled: true

  image:
    repository: mcp-mesh/registry
    pullPolicy: IfNotPresent

  service:
    type: ClusterIP
    port: 8080

  persistence:
    enabled: true
    storageClass: "" # Use cluster default
    accessMode: ReadWriteOnce

  # Health check defaults
  livenessProbe:
    initialDelaySeconds: 30
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3

  readinessProbe:
    initialDelaySeconds: 5
    periodSeconds: 5
    timeoutSeconds: 3
    failureThreshold: 3

# Agent defaults
agentDefaults:
  image:
    pullPolicy: IfNotPresent

  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0

  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000

  containerSecurityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
```

### Step 3: Environment-Specific Overrides

Create environment-specific values:

```yaml
# values/environments/development.yaml
# Development environment overrides

global:
  environment: development

  # Dev-specific labels
  labels:
    environment: dev
    tier: non-production

# Minimal resources for dev
registry:
  replicaCount: 1

  persistence:
    size: 5Gi

  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "256Mi"
      cpu: "100m"

# Enable debug logging
logging:
  level: debug
  format: text

# Simplified monitoring
monitoring:
  enabled: false

# Agent configurations for dev
agents:
  weather:
    replicaCount: 1
    resources:
      requests:
        memory: "64Mi"
        cpu: "25m"
    env:
      LOG_LEVEL: "debug"
      CACHE_ENABLED: "false"
```

Production values:

```yaml
# values/environments/production.yaml
# Production environment overrides

global:
  environment: production

  labels:
    environment: prod
    tier: production
    compliance: "pci-dss"

# HA configuration
registry:
  replicaCount: 5

  persistence:
    size: 100Gi
    storageClass: "fast-ssd"

  resources:
    requests:
      memory: "2Gi"
      cpu: "1000m"
    limits:
      memory: "4Gi"
      cpu: "2000m"

  # Anti-affinity for distribution
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

  # Production database
  database:
    type: postgresql
    connectionPool:
      min: 10
      max: 50
    ssl:
      enabled: true
      mode: require

# Structured logging for production
logging:
  level: info
  format: json

  # Send to centralized logging
  outputs:
    - type: stdout
    - type: fluentd
      host: fluentd.logging.svc.cluster.local
      port: 24224

# Full monitoring stack
monitoring:
  enabled: true

  prometheus:
    retention: 30d
    storageSize: 200Gi

  grafana:
    persistence:
      enabled: true
      size: 20Gi

  alerts:
    enabled: true
    pagerduty:
      enabled: true
      serviceKey: "${PAGERDUTY_SERVICE_KEY}"

# Production agent settings
agents:
  weather:
    replicaCount: 10

    autoscaling:
      enabled: true
      minReplicas: 10
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

    resources:
      requests:
        memory: "512Mi"
        cpu: "250m"
      limits:
        memory: "1Gi"
        cpu: "500m"

    # Production-grade probes
    livenessProbe:
      httpGet:
        path: /health
        port: http
      initialDelaySeconds: 60
      periodSeconds: 30
      timeoutSeconds: 10
      failureThreshold: 5

    # Circuit breaker configuration
    circuitBreaker:
      enabled: true
      requestVolumeThreshold: 20
      errorThresholdPercentage: 50
      sleepWindow: 30000
```

### Step 4: Advanced Templating in Values

Use Go templates for dynamic values:

```yaml
# values/templates/dynamic-values.yaml
# Dynamic value generation

{% raw %}{{- $environment := .Values.global.environment | default "development" -}}{% endraw %}
{% raw %}{{- $domain := .Values.global.domain | default "local" -}}{% endraw %}

# Generate URLs based on environment
urls:
  registry:
    internal: "http://{% raw %}{{ .Release.Name }}{% endraw %}-registry.{% raw %}{{ .Release.Namespace }}{% endraw %}.svc.cluster.local:8080"
    external: "https://registry.{% raw %}{{ $environment }}{% endraw %}.{% raw %}{{ $domain }}{% endraw %}"

  agents:
    {% raw %}{{- range $name, $agent := .Values.agents }}{% endraw %}
    {% raw %}{{ $name }}{% endraw %}:
      internal: "http://{% raw %}{{ $.Release.Name }}{% endraw %}-{% raw %}{{ $name }}{% endraw %}.{% raw %}{{ $.Release.Namespace }}{% endraw %}.svc.cluster.local:8080"
      external: "https://{% raw %}{{ $name }}{% endraw %}.{% raw %}{{ $environment }}{% endraw %}.{% raw %}{{ $domain }}{% endraw %}"
    {% raw %}{{- end }}{% endraw %}

# Environment-specific features
features:
  debugMode: {% raw %}{{ eq $environment "development" }}{% endraw %}
  tracing: {% raw %}{{ has $environment (list "staging" "production") }}{% endraw %}
  profiling: {% raw %}{{ eq $environment "development" }}{% endraw %}

# Resource multipliers by environment
resourceMultipliers:
  {% raw %}{{- if eq $environment "production" }}{% endraw %}
  cpu: 2.0
  memory: 2.0
  {% raw %}{{- else if eq $environment "staging" }}{% endraw %}
  cpu: 1.5
  memory: 1.5
  {% raw %}{{- else }}{% endraw %}
  cpu: 0.5
  memory: 0.5
  {% raw %}{{- end }}{% endraw %}

# Conditional configurations
{% raw %}{{- if eq $environment "production" }}{% endraw %}
backup:
  enabled: true
  schedule: "0 2 * * *"
  retention: 30
{% raw %}{{- end }}{% endraw %}
```

### Step 5: Secrets Management

Implement secure secrets handling:

```yaml
# values/secrets/production-secrets.yaml (encrypted with SOPS)
# sops --encrypt --age $AGE_PUBLIC_KEY production-secrets.yaml

database:
  password: ENC[AES256_GCM,data:1234567890abcdef,iv:...,tag:...,type:str]

agents:
  weather:
    apiKey: ENC[AES256_GCM,data:weatherapi123,iv:...,tag:...,type:str]

  notification:
    smtp:
      password: ENC[AES256_GCM,data:smtppass456,iv:...,tag:...,type:str]
    twilio:
      authToken: ENC[AES256_GCM,data:twiliotoken789,iv:...,tag:...,type:str]
```

Use with Helm:

```bash
# Decrypt and install
sops -d values/secrets/production-secrets.yaml | \
  helm install my-release ./chart \
    -f values/base/values.yaml \
    -f values/environments/production.yaml \
    -f -
```

## Configuration Options

| Technique      | Use Case                 | Example                        |
| -------------- | ------------------------ | ------------------------------ |
| Multiple `-f`  | Layer configurations     | `-f base.yaml -f prod.yaml`    |
| `--set`        | Override specific values | `--set image.tag=v2.0.0`       |
| `--set-string` | Force string type        | `--set-string port="8080"`     |
| `--set-file`   | Load file content        | `--set-file tls.cert=cert.pem` |
| `--values`     | Same as `-f`             | `--values custom.yaml`         |

## Examples

### Example 1: Multi-Region Deployment

```yaml
# values/regions/us-east.yaml
global:
  region: us-east-1
  availabilityZones:
    - us-east-1a
    - us-east-1b
    - us-east-1c

ingress:
  enabled: true
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123456789:certificate/abc
  hosts:
    - host: api.us-east.mcp-mesh.io
      paths:
        - path: /*
          pathType: Prefix

nodeSelector:
  topology.kubernetes.io/region: us-east-1

---
# values/regions/eu-west.yaml
global:
  region: eu-west-1
  availabilityZones:
    - eu-west-1a
    - eu-west-1b
    - eu-west-1c

ingress:
  enabled: true
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:eu-west-1:123456789:certificate/def
  hosts:
    - host: api.eu-west.mcp-mesh.io
      paths:
        - path: /*
          pathType: Prefix

nodeSelector:
  topology.kubernetes.io/region: eu-west-1
```

Deploy to multiple regions:

```bash
# US East deployment
helm install mcp-mesh-us-east ./chart \
  -f values/base/values.yaml \
  -f values/environments/production.yaml \
  -f values/regions/us-east.yaml \
  --namespace mcp-mesh-us-east

# EU West deployment
helm install mcp-mesh-eu-west ./chart \
  -f values/base/values.yaml \
  -f values/environments/production.yaml \
  -f values/regions/eu-west.yaml \
  --namespace mcp-mesh-eu-west
```

### Example 2: Feature Flags Configuration

```yaml
# values/features/feature-flags.yaml
featureFlags:
  # Core features
  core:
    newAuthSystem:
      enabled: {% raw %}{{ eq .Values.global.environment "development" }}{% endraw %}
      rolloutPercentage: 10

    improvedCaching:
      enabled: true
      rolloutPercentage: {% raw %}{{ .Values.global.featureRollout.improvedCaching | default 50 }}{% endraw %}

  # Agent-specific features
  agents:
    weather:
      mlPredictions:
        enabled: {% raw %}{{ has .Values.global.environment (list "staging" "production") }}{% endraw %}
        modelVersion: "2.1.0"

      premiumApi:
        enabled: {% raw %}{{ .Values.global.environment | eq "production" }}{% endraw %}
        rateLimit: 1000

    analytics:
      realtimeProcessing:
        enabled: false
        betaUsers:
          - "customer-123"
          - "customer-456"

# Apply feature flags to agents
{% raw %}{{- range $agent, $features := .Values.featureFlags.agents }}{% endraw %}
agents:
  {% raw %}{{ $agent }}{% endraw %}:
    env:
      {% raw %}{{- range $feature, $config := $features }}{% endraw %}
      FEATURE_{% raw %}{{ $feature | upper }}{% endraw %}_ENABLED: {% raw %}{{ $config.enabled | quote }}{% endraw %}
      {% raw %}{{- if $config.rolloutPercentage }}{% endraw %}
      FEATURE_{% raw %}{{ $feature | upper }}{% endraw %}_ROLLOUT: {% raw %}{{ $config.rolloutPercentage | quote }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
      {% raw %}{{- end }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
```

## Best Practices

1. **Layer Values Files**: Base → Environment → Region → Secrets
2. **Use Anchors**: YAML anchors for repeated configurations
3. **Validate Values**: JSON Schema validation before deployment
4. **Version Control**: Track all values files in Git
5. **Document Options**: Comment complex value structures

## Common Pitfalls

### Pitfall 1: Value Type Confusion

**Problem**: Helm interprets numbers/booleans incorrectly

**Solution**: Use explicit typing:

```bash
# Force string
--set-string version="1.10"

# In values file
port: "8080"  # Quoted to ensure string
enabled: true # Explicit boolean
count: 3      # Explicit number
```

### Pitfall 2: Deep Nesting Issues

**Problem**: Deeply nested values are hard to override

**Solution**: Flatten where possible:

```yaml
# Hard to override
database:
  connection:
    pool:
      min: 10
      max: 50

# Better
databasePoolMin: 10
databasePoolMax: 50

# Or use --set with dots
--set database.connection.pool.min=20
```

## Testing

### Validate Values Rendering

```bash
#!/bin/bash
# validate-values.sh

echo "Validating values files..."

# Check YAML syntax
for file in values/**/*.yaml; do
  echo "Checking $file"
  yq eval '.' "$file" > /dev/null || exit 1
done

# Test value merging
helm template test-release ./chart \
  -f values/base/values.yaml \
  -f values/environments/production.yaml \
  --debug > /tmp/rendered.yaml

# Validate rendered manifests
kubectl apply --dry-run=client -f /tmp/rendered.yaml

echo "Values validation complete!"
```

### Unit Test Values

```python
# test_values.py
import yaml
import pytest

def load_values(*files):
    """Load and merge multiple values files"""
    result = {}
    for file in files:
        with open(file) as f:
            data = yaml.safe_load(f)
            # Simple merge (use deepmerge for production)
            result.update(data)
    return result

def test_production_values():
    """Test production values configuration"""
    values = load_values(
        'values/base/values.yaml',
        'values/environments/production.yaml'
    )

    # Check critical settings
    assert values['registry']['replicaCount'] >= 3
    assert values['registry']['persistence']['enabled'] is True
    assert values['logging']['level'] == 'info'
    assert values['monitoring']['enabled'] is True

def test_resource_limits():
    """Ensure resource limits are set"""
    values = load_values(
        'values/base/values.yaml',
        'values/environments/production.yaml'
    )

    # Check registry resources
    registry_resources = values['registry']['resources']
    assert 'limits' in registry_resources
    assert 'requests' in registry_resources
    assert registry_resources['limits']['memory']
    assert registry_resources['limits']['cpu']
```

## Monitoring and Debugging

### Debug Values Merging

```bash
# Show final values after merging
helm get values my-release -n mcp-mesh

# Show computed values (with templates evaluated)
helm get values my-release -n mcp-mesh --all

# Debug specific value path
helm template my-release ./chart \
  -f values1.yaml -f values2.yaml \
  --show-only templates/deployment.yaml | grep -A5 "resources:"
```

### Monitor Configuration Drift

```bash
# Compare deployed values with files
diff <(helm get values my-release -n mcp-mesh) values/production-deployed.yaml

# Track values changes
helm get values my-release --revision 1 > rev1-values.yaml
helm get values my-release --revision 2 > rev2-values.yaml
diff rev1-values.yaml rev2-values.yaml
```

## 🔧 Troubleshooting

### Issue 1: Values Not Applying

**Symptoms**: Changes in values file don't affect deployment

**Cause**: Cache or incorrect file path

**Solution**:

```bash
# Clear any cache
rm -rf charts/ Chart.lock

# Verify file path
ls -la values/production.yaml

# Test with explicit path
helm upgrade my-release ./chart \
  -f $(pwd)/values/production.yaml \
  --debug --dry-run
```

### Issue 2: Template Errors in Values

**Symptoms**: `error converting YAML to JSON`

**Cause**: Go template syntax in values file

**Solution**:

```yaml
# Values files don't support templating by default
# Move templates to tpl files:

# templates/values-helper.tpl
{% raw %}{{- define "dynamic.values" -}}{% endraw %}
environment: {% raw %}{{ .Values.global.environment }}{% endraw %}
url: https://{% raw %}{{ .Values.global.environment }}{% endraw %}.example.com
{% raw %}{{- end }}{% endraw %}

# Use in templates
{% raw %}{{- $dynamicValues := include "dynamic.values" . | fromYaml }}{% endraw %}
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Size Limits**: ConfigMaps limited to 1MB
- **No Templating**: Values files don't support Go templates directly
- **Type Coercion**: YAML type inference can be problematic
- **Deep Merging**: Helm doesn't deep merge arrays

## 📝 TODO

- [ ] Add values schema validation
- [ ] Create values generator tool
- [ ] Document GitOps values patterns
- [ ] Add encryption key management guide
- [ ] Create values migration scripts

## Summary

You now understand advanced Helm values management:

Key takeaways:

- 🔑 Layer values files for maintainability
- 🔑 Use environment-specific overrides
- 🔑 Implement secure secrets management
- 🔑 Test and validate values configurations

## Next Steps

Let's explore deploying to multiple environments.

Continue to [Multi-Environment Deployment](./04-multi-environment.md) →

---

💡 **Tip**: Use `yq` tool to manipulate YAML values files programmatically: `yq eval '.registry.replicaCount = 5' -i values.yaml`

📚 **Reference**: [Helm Values Files Documentation](https://helm.sh/docs/chart_template_guide/values_files/)

🧪 **Try It**: Create a values inheritance hierarchy for dev→staging→production with proper overrides
