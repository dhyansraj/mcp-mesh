# Multi-Environment Deployment

> Manage MCP Mesh deployments across development, staging, and production environments

## Overview

Managing deployments across multiple environments is a critical aspect of production operations. This guide shows how to structure Helm deployments for different environments, manage environment-specific configurations, handle secrets securely, and implement promotion workflows. You'll learn patterns for maintaining consistency while allowing environment-specific customizations.

Proper multi-environment management ensures reliable deployments and reduces configuration drift between environments.

## Key Concepts

- **Environment Separation**: Isolating dev, staging, and production
- **Configuration Inheritance**: Base configs with environment overrides
- **Secret Management**: Environment-specific sensitive data
- **Promotion Workflows**: Moving changes through environments
- **Environment Parity**: Maintaining consistency across environments

## Step-by-Step Guide

### Step 1: Environment Structure

Organize your environments with a clear hierarchy:

```
environments/
├── base/                    # Shared configuration
│   ├── kustomization.yaml
│   └── values.yaml
├── development/
│   ├── kustomization.yaml
│   ├── values.yaml
│   └── secrets.yaml
├── staging/
│   ├── kustomization.yaml
│   ├── values.yaml
│   └── secrets.yaml
└── production/
    ├── kustomization.yaml
    ├── values.yaml
    ├── secrets.yaml
    └── values-dr.yaml      # Disaster recovery

# Helm releases structure
releases/
├── dev/
│   └── mcp-mesh/
├── staging/
│   └── mcp-mesh/
└── prod/
    ├── mcp-mesh/
    └── mcp-mesh-dr/
```

### Step 2: Base Configuration

Create a base configuration that all environments inherit:

```yaml
# environments/base/values.yaml
# Common configuration across all environments

global:
  # Organization settings
  organization: "mcp-mesh-corp"
  project: "mcp-mesh"

  # Common labels
  labels:
    app: "mcp-mesh"
    managedBy: "helm"
    version: "1.0.0"

  # Image configuration
  imageRegistry: "registry.mcp-mesh.io"
  imagePullPolicy: "IfNotPresent"

  # Security defaults
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000

# Registry configuration
registry:
  image:
    repository: mcp-mesh/registry
    tag: "1.0.0"

  service:
    type: ClusterIP
    port: 8080

  # Health checks
  livenessProbe:
    initialDelaySeconds: 30
    periodSeconds: 10

  readinessProbe:
    initialDelaySeconds: 5
    periodSeconds: 5

# Agent defaults
agentDefaults:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0

  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL

# Monitoring defaults
monitoring:
  metrics:
    enabled: true
    port: 9090

  serviceMonitor:
    interval: 30s
    scrapeTimeout: 10s
```

### Step 3: Development Environment

Configure development for rapid iteration:

```yaml
# environments/development/values.yaml
# Development-specific overrides

global:
  environment: development

  # Dev cluster domain
  domain: "dev.mcp-mesh.local"

  # Development tags
  labels:
    environment: "dev"
    tier: "development"

# Single instance for dev
registry:
  replicaCount: 1

  # Use local storage
  persistence:
    enabled: true
    size: 10Gi
    storageClass: "standard"

  # Minimal resources
  resources:
    requests:
      memory: "128Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "500m"

  # SQLite for simplicity
  database:
    type: "sqlite"
    path: "/data/registry.db"

  # Enable debug logging
  logging:
    level: "DEBUG"
    format: "text"

# Development agents
agents:
  weather:
    enabled: true
    replicaCount: 1
    image:
      tag: "0.3" # Use 0.3 in dev
    env:
      LOG_LEVEL: "DEBUG"
      CACHE_ENABLED: "false"
      MOCK_EXTERNAL_APIS: "true"
    resources:
      requests:
        memory: "64Mi"
        cpu: "50m"
      limits:
        memory: "256Mi"
        cpu: "200m"

# Simplified monitoring
monitoring:
  prometheus:
    enabled: false
  grafana:
    enabled: false

# Dev ingress with self-signed cert
ingress:
  enabled: true
  className: "nginx"
  hosts:
    - host: "mcp-mesh.dev.local"
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - "mcp-mesh.dev.local"
      secretName: mcp-mesh-dev-tls

# Development features
features:
  debugMode: true
  mockData: true
  rateLimit: false
  authentication: false
```

### Step 4: Staging Environment

Configure staging to mirror production:

```yaml
# environments/staging/values.yaml
# Staging-specific overrides

global:
  environment: staging

  # Staging domain
  domain: "staging.mcp-mesh.io"

  labels:
    environment: "staging"
    tier: "pre-production"

# Multi-replica for testing HA
registry:
  replicaCount: 3

  persistence:
    enabled: true
    size: 50Gi
    storageClass: "fast-ssd"

  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "1Gi"
      cpu: "500m"

  # PostgreSQL for production parity
  database:
    type: "postgresql"
    host: "postgres-staging.mcp-mesh.io"
    port: 5432
    name: "mcp_mesh_staging"
    sslMode: "require"

  # Production-like logging
  logging:
    level: "INFO"
    format: "json"

  # Anti-affinity for distribution
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchExpressions:
                - key: app.kubernetes.io/name
                  operator: In
                  values:
                    - mcp-mesh-registry
            topologyKey: kubernetes.io/hostname

# Staging agents
agents:
  weather:
    enabled: true
    replicaCount: 3
    image:
      tag: "1.0.0-rc.1" # Release candidate
    env:
      LOG_LEVEL: "INFO"
      CACHE_ENABLED: "true"
      CACHE_TTL: "300"
      API_TIMEOUT: "30"
    resources:
      requests:
        memory: "256Mi"
        cpu: "100m"
      limits:
        memory: "512Mi"
        cpu: "250m"

    # Test autoscaling
    autoscaling:
      enabled: true
      minReplicas: 3
      maxReplicas: 10
      targetCPUUtilizationPercentage: 70

  analytics:
    enabled: true
    replicaCount: 2
    persistence:
      enabled: true
      size: 100Gi

# Full monitoring stack
monitoring:
  prometheus:
    enabled: true
    retention: "7d"
    resources:
      requests:
        memory: "512Mi"
        cpu: "250m"

  grafana:
    enabled: true
    adminPassword: "staging-changeme"
    persistence:
      enabled: true
      size: 10Gi

# Staging ingress with real cert
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-staging"
    nginx.ingress.kubernetes.io/rate-limit: "100"
  hosts:
    - host: "api.staging.mcp-mesh.io"
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - "api.staging.mcp-mesh.io"
      secretName: mcp-mesh-staging-tls

# Staging features
features:
  debugMode: false
  mockData: false
  rateLimit: true
  authentication: true
  canary:
    enabled: true
    percentage: 10
```

### Step 5: Production Environment

Configure production for reliability and scale:

```yaml
# environments/production/values.yaml
# Production-specific overrides

global:
  environment: production

  # Production domain
  domain: "mcp-mesh.io"

  labels:
    environment: "production"
    tier: "production"
    compliance: "sox"
    dataClassification: "confidential"

# HA configuration
registry:
  replicaCount: 5

  persistence:
    enabled: true
    size: 200Gi
    storageClass: "ultra-ssd"

  resources:
    requests:
      memory: "2Gi"
      cpu: "1000m"
    limits:
      memory: "4Gi"
      cpu: "2000m"

  # Production PostgreSQL with HA
  database:
    type: "postgresql"
    host: "postgres-primary.mcp-mesh.io"
    port: 5432
    name: "mcp_mesh_production"
    sslMode: "require"
    connectionPool:
      min: 20
      max: 100
      idleTimeout: 300

  # Production logging
  logging:
    level: "INFO"
    format: "json"
    outputs:
      - type: "stdout"
      - type: "syslog"
        host: "syslog.mcp-mesh.io"
        port: 514

  # Strict anti-affinity
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

  # Pod disruption budget
  podDisruptionBudget:
    enabled: true
    minAvailable: 3

# Production agents
agents:
  weather:
    enabled: true
    replicaCount: 10
    image:
      tag: "1.0.0"

    # Production configuration
    env:
      LOG_LEVEL: "INFO"
      CACHE_ENABLED: "true"
      CACHE_TTL: "3600"
      API_TIMEOUT: "10"
      CIRCUIT_BREAKER_ENABLED: "true"
      RATE_LIMIT_PER_MINUTE: "1000"

    # Production resources
    resources:
      requests:
        memory: "1Gi"
        cpu: "500m"
      limits:
        memory: "2Gi"
        cpu: "1000m"

    # Production autoscaling
    autoscaling:
      enabled: true
      minReplicas: 10
      maxReplicas: 100
      targetCPUUtilizationPercentage: 60
      targetMemoryUtilizationPercentage: 70
      behavior:
        scaleUp:
          stabilizationWindowSeconds: 60
          policies:
            - type: Percent
              value: 100
              periodSeconds: 60
            - type: Pods
              value: 5
              periodSeconds: 60
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
            - type: Percent
              value: 10
              periodSeconds: 60

    # Production probes
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

  analytics:
    enabled: true
    replicaCount: 20
    persistence:
      enabled: true
      size: 5Ti
      storageClass: "ultra-ssd"

    # Analytics-specific config
    streaming:
      enabled: true
      kafka:
        brokers:
          - "kafka-1.mcp-mesh.io:9092"
          - "kafka-2.mcp-mesh.io:9092"
          - "kafka-3.mcp-mesh.io:9092"

# Production monitoring
monitoring:
  prometheus:
    enabled: true
    retention: "90d"
    storageSize: 1Ti
    replicas: 3

    # Remote write for long-term storage
    remoteWrite:
      - url: "https://metrics.mcp-mesh.io/api/v1/write"
        writeRelabelConfigs:
          - sourceLabels: [__name__]
            regex: "go_.*"
            action: drop

  grafana:
    enabled: true
    replicas: 3
    persistence:
      enabled: true
      size: 50Gi

    # LDAP authentication
    ldap:
      enabled: true
      host: "ldap.mcp-mesh.io"
      port: 636
      useSSL: true

  alertmanager:
    enabled: true
    replicas: 3

    # Alert routing
    config:
      route:
        receiver: "default"
        routes:
          - receiver: "critical"
            matchers:
              - severity = "critical"
          - receiver: "warning"
            matchers:
              - severity = "warning"

      receivers:
        - name: "default"
          slackConfigs:
            - apiURL: "${SLACK_WEBHOOK_URL}"
              channel: "#alerts"

        - name: "critical"
          pagerdutyConfigs:
            - serviceKey: "${PAGERDUTY_SERVICE_KEY}"
          slackConfigs:
            - apiURL: "${SLACK_WEBHOOK_URL}"
              channel: "#alerts-critical"

# Production ingress with WAF
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/rate-limit: "1000"
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.2 TLSv1.3"
    nginx.ingress.kubernetes.io/ssl-ciphers: "ECDHE+AESGCM:ECDHE+AES256:!aNULL"
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
  hosts:
    - host: "api.mcp-mesh.io"
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - "api.mcp-mesh.io"
      secretName: mcp-mesh-production-tls

# Production features
features:
  debugMode: false
  mockData: false
  rateLimit: true
  authentication: true
  audit:
    enabled: true
    retention: "7y"
  backup:
    enabled: true
    schedule: "0 2 * * *"
    retention: 30
```

### Step 6: Secret Management

Implement secure secret handling per environment:

```bash
# Structure for secrets
secrets/
├── development/
│   ├── database-secret.yaml
│   └── api-keys.yaml
├── staging/
│   ├── database-secret.yaml
│   ├── api-keys.yaml
│   └── certificates.yaml
└── production/
    ├── database-secret.yaml
    ├── api-keys.yaml
    ├── certificates.yaml
    └── backup-credentials.yaml
```

Use Sealed Secrets or SOPS:

```yaml
# secrets/production/database-secret.yaml (encrypted with SOPS)
apiVersion: v1
kind: Secret
metadata:
  name: mcp-mesh-database
  namespace: mcp-mesh
type: Opaque
data:
  username: ENC[AES256_GCM,data:postgres_prod,iv:...,tag:...,type:str]
  password: ENC[AES256_GCM,data:supersecret123,iv:...,tag:...,type:str]
  connection-string: ENC[AES256_GCM,data:postgresql://...,iv:...,tag:...,type:str]
```

### Step 7: Deployment Scripts

Create environment-specific deployment scripts:

```bash
#!/bin/bash
# deploy.sh - Environment deployment script

set -euo pipefail

ENVIRONMENT="${1:-}"
ACTION="${2:-install}"
NAMESPACE="mcp-mesh-${ENVIRONMENT}"

if [[ -z "$ENVIRONMENT" ]]; then
  echo "Usage: $0 <environment> [action]"
  echo "Environments: dev, staging, prod"
  echo "Actions: install, upgrade, diff, rollback"
  exit 1
fi

# Validate environment
if [[ ! -d "environments/${ENVIRONMENT}" ]]; then
  echo "Error: Unknown environment '${ENVIRONMENT}'"
  exit 1
fi

# Set environment-specific values
case "$ENVIRONMENT" in
  dev|development)
    ENVIRONMENT="development"
    VALUES_FILES="-f environments/base/values.yaml -f environments/development/values.yaml"
    HELM_ARGS="--timeout 5m"
    ;;
  staging)
    VALUES_FILES="-f environments/base/values.yaml -f environments/staging/values.yaml"
    HELM_ARGS="--timeout 10m --atomic"
    ;;
  prod|production)
    VALUES_FILES="-f environments/base/values.yaml -f environments/production/values.yaml"
    HELM_ARGS="--timeout 15m --atomic --wait"
    # Require confirmation for production
    read -p "Deploy to PRODUCTION? Type 'yes' to confirm: " confirm
    if [[ "$confirm" != "yes" ]]; then
      echo "Deployment cancelled"
      exit 1
    fi
    ;;
esac

# Decrypt secrets if using SOPS
if command -v sops &> /dev/null; then
  echo "Decrypting secrets for ${ENVIRONMENT}..."
  SECRETS_FILE="/tmp/secrets-${ENVIRONMENT}.yaml"
  sops -d "secrets/${ENVIRONMENT}/secrets.yaml" > "$SECRETS_FILE"
  VALUES_FILES="${VALUES_FILES} -f ${SECRETS_FILE}"
  trap "rm -f ${SECRETS_FILE}" EXIT
fi

# Execute action
case "$ACTION" in
  install)
    echo "Installing MCP Mesh in ${ENVIRONMENT}..."
    helm install mcp-mesh ./mcp-mesh-platform \
      --namespace "$NAMESPACE" \
      --create-namespace \
      $VALUES_FILES \
      $HELM_ARGS
    ;;

  upgrade)
    echo "Upgrading MCP Mesh in ${ENVIRONMENT}..."
    helm upgrade mcp-mesh ./mcp-mesh-platform \
      --namespace "$NAMESPACE" \
      $VALUES_FILES \
      $HELM_ARGS
    ;;

  diff)
    echo "Showing diff for ${ENVIRONMENT}..."
    helm diff upgrade mcp-mesh ./mcp-mesh-platform \
      --namespace "$NAMESPACE" \
      $VALUES_FILES
    ;;

  rollback)
    echo "Rolling back MCP Mesh in ${ENVIRONMENT}..."
    REVISION="${3:-}"
    if [[ -z "$REVISION" ]]; then
      echo "Error: Revision number required for rollback"
      echo "Usage: $0 $ENVIRONMENT rollback <revision>"
      helm history mcp-mesh -n "$NAMESPACE"
      exit 1
    fi
    helm rollback mcp-mesh "$REVISION" \
      --namespace "$NAMESPACE" \
      --wait
    ;;

  *)
    echo "Error: Unknown action '$ACTION'"
    exit 1
    ;;
esac

echo "Deployment complete!"
```

## Configuration Options

| Environment | Replicas | Resources | Storage | Features          |
| ----------- | -------- | --------- | ------- | ----------------- |
| Development | 1        | Minimal   | 10Gi    | Debug, Mock       |
| Staging     | 3        | Medium    | 50Gi    | Full monitoring   |
| Production  | 5+       | High      | 200Gi+  | HA, Backup, Audit |

## Examples

### Example 1: Progressive Deployment

Deploy changes through environments:

```bash
# 1. Deploy to development
./deploy.sh dev upgrade

# 2. Run tests
kubectl run test-pod --rm -it --image=curlimages/curl -- \
  curl http://mcp-mesh-registry.mcp-mesh-dev:8080/health

# 3. Deploy to staging
./deploy.sh staging upgrade

# 4. Run smoke tests
./scripts/smoke-tests.sh staging

# 5. Deploy to production (canary)
helm upgrade mcp-mesh ./mcp-mesh-platform \
  --namespace mcp-mesh-prod \
  -f environments/base/values.yaml \
  -f environments/production/values.yaml \
  --set agents.weather.canary.enabled=true \
  --set agents.weather.canary.percentage=10

# 6. Monitor canary
./scripts/monitor-canary.sh

# 7. Full production deployment
./deploy.sh prod upgrade
```

### Example 2: Environment-Specific Features

Enable features per environment:

```yaml
# Feature flags template
{% raw %}{{- define "features" -}}{% endraw %}
{% raw %}{{- $env := .Values.global.environment | default "development" -}}{% endraw %}
features:
  # Development features
  {% raw %}{{- if eq $env "development" }}{% endraw %}
  debugEndpoints: true
  mockExternalServices: true
  unlimitedRateLimit: true
  {% raw %}{{- end }}{% endraw %}

  # Staging features
  {% raw %}{{- if eq $env "staging" }}{% endraw %}
  canaryDeployment: true
  abTesting: true
  syntheticMonitoring: true
  {% raw %}{{- end }}{% endraw %}

  # Production features
  {% raw %}{{- if eq $env "production" }}{% endraw %}
  auditLogging: true
  complianceMode: true
  disasterRecovery: true
  {% raw %}{{- end }}{% endraw %}
{% raw %}{{- end }}{% endraw %}
```

## Best Practices

1. **Environment Parity**: Keep environments as similar as possible
2. **Progressive Rollout**: Always deploy dev → staging → production
3. **Secret Rotation**: Regularly rotate secrets per environment
4. **Resource Sizing**: Right-size resources per environment load
5. **Monitoring Coverage**: Full monitoring even in non-production

## Common Pitfalls

### Pitfall 1: Configuration Drift

**Problem**: Environments diverge over time

**Solution**: Use GitOps and automation:

```yaml
# .github/workflows/sync-environments.yml
name: Sync Environments
on:
  push:
    paths:
      - "environments/**"
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Dev
        run: ./deploy.sh dev upgrade
      - name: Deploy to Staging
        run: ./deploy.sh staging upgrade
```

### Pitfall 2: Secret Leakage

**Problem**: Secrets exposed in values files

**Solution**: Always encrypt secrets:

```bash
# Never commit plain secrets
echo "secrets*.yaml" >> .gitignore

# Use SOPS to encrypt
sops -e secrets/production/api-keys.yaml > secrets/production/api-keys.enc.yaml
```

## Testing

### Environment Validation

```bash
#!/bin/bash
# validate-environment.sh

ENVIRONMENT=$1

echo "Validating ${ENVIRONMENT} environment..."

# Check all pods are running
kubectl get pods -n "mcp-mesh-${ENVIRONMENT}" -o json | \
  jq -r '.items[] | select(.status.phase != "Running") | .metadata.name' | \
  grep -q . && echo "ERROR: Some pods not running" && exit 1

# Check endpoints
ENDPOINTS=(
  "mcp-mesh-registry:8080/health"
  "weather-agent:8080/health"
  "analytics-agent:8080/health"
)

for endpoint in "${ENDPOINTS[@]}"; do
  kubectl run curl-test --rm -it --image=curlimages/curl -- \
    curl -f "http://${endpoint}" || exit 1
done

echo "Environment validation passed!"
```

### Promotion Testing

```python
# test_promotion.py
import subprocess
import json
import time

def get_deployment_version(namespace, deployment):
    """Get current deployment version"""
    cmd = f"kubectl get deployment {deployment} -n {namespace} -o json"
    result = subprocess.run(cmd.split(), capture_output=True, text=True)
    data = json.loads(result.stdout)
    return data['spec']['template']['spec']['containers'][0]['image'].split(':')[-1]

def test_promotion_flow():
    """Test version promotion through environments"""
    environments = ['dev', 'staging', 'prod']
    deployment = 'mcp-mesh-registry'

    versions = {}
    for env in environments:
        namespace = f"mcp-mesh-{env}"
        versions[env] = get_deployment_version(namespace, deployment)
        print(f"{env}: {versions[env]}")

    # Verify progressive promotion
    assert versions['prod'] <= versions['staging'] <= versions['dev']
    print("Promotion flow validated!")

if __name__ == "__main__":
    test_promotion_flow()
```

## Monitoring and Debugging

### Monitor Deployments Across Environments

```bash
# Get deployment status across all environments
for env in dev staging prod; do
  echo "=== $env ==="
  helm status mcp-mesh -n "mcp-mesh-$env" --show-desc
done

# Compare configurations
helm get values mcp-mesh -n mcp-mesh-dev > /tmp/dev.yaml
helm get values mcp-mesh -n mcp-mesh-staging > /tmp/staging.yaml
diff /tmp/dev.yaml /tmp/staging.yaml
```

### Environment Health Dashboard

```yaml
# Grafana dashboard for multi-environment
{
  "dashboard":
    {
      "title": "MCP Mesh Multi-Environment",
      "panels":
        [
          {
            "title": "Deployments by Environment",
            "targets":
              [{ "expr": 'count by (environment) (up{job="mcp-mesh"})' }],
          },
          {
            "title": "Error Rates by Environment",
            "targets":
              [
                {
                  "expr": 'rate(http_requests_total{status=~"5.."}[5m]) by (environment)',
                },
              ],
          },
        ],
    },
}
```

## 🔧 Troubleshooting

### Issue 1: Environment Mismatch

**Symptoms**: Wrong configuration in environment

**Cause**: Values file precedence issue

**Solution**:

```bash
# Debug values precedence
helm template mcp-mesh ./mcp-mesh-platform \
  -f environments/base/values.yaml \
  -f environments/production/values.yaml \
  --debug 2>&1 | grep -A10 "computed values"

# Verify final values
helm get values mcp-mesh -n mcp-mesh-prod --all
```

### Issue 2: Secret Not Found

**Symptoms**: `Error: secret "api-keys" not found`

**Cause**: Secrets not deployed or wrong namespace

**Solution**:

```bash
# Check if secrets exist
kubectl get secrets -n mcp-mesh-prod

# Apply secrets manually if needed
sops -d secrets/production/api-keys.yaml | kubectl apply -n mcp-mesh-prod -f -
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Namespace Isolation**: Cross-namespace resources need special handling
- **Secret Size**: Kubernetes secrets limited to 1MB
- **ConfigMap Updates**: May require pod restarts
- **Multi-Region**: Requires additional tooling for global deployments

## 📝 TODO

- [ ] Add GitOps workflow examples
- [ ] Create environment promotion automation
- [ ] Document blue-green deployment patterns
- [ ] Add multi-region deployment guide
- [ ] Create cost optimization per environment

## Summary

You now understand multi-environment deployment patterns:

Key takeaways:

- 🔑 Structure environments with inheritance
- 🔑 Maintain environment parity
- 🔑 Secure secrets per environment
- 🔑 Automate promotion workflows

## Next Steps

Let's explore Helm best practices for production.

Continue to [Helm Best Practices](./05-best-practices.md) →

---

💡 **Tip**: Use `helmfile` for managing multiple environment deployments: `helmfile -e production sync`

📚 **Reference**: [Helm Environment Management](https://helm.sh/docs/intro/using_helm/#customizing-the-chart-before-installing)

🧪 **Try It**: Create a fourth environment for QA testing with its own configuration profile
