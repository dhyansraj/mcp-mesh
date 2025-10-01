# Alerting and SLOs

> Define service level objectives and implement proactive alerting for MCP Mesh

## Overview

Effective alerting and well-defined Service Level Objectives (SLOs) are crucial for maintaining reliable MCP Mesh deployments. This guide covers establishing SLIs (Service Level Indicators), setting appropriate SLOs, implementing multi-tier alerting strategies, and creating runbooks for incident response. You'll learn to balance alerting sensitivity with alert fatigue while ensuring critical issues are never missed.

Proper alerting and SLO management enables proactive incident response, maintains service reliability, and provides clear communication about system performance to stakeholders.

## Key Concepts

- **SLI (Service Level Indicator)**: Metrics that measure service behavior
- **SLO (Service Level Objective)**: Target values for SLIs
- **Error Budget**: Allowable unreliability within SLO
- **Alert Fatigue**: Too many non-actionable alerts
- **Runbooks**: Documented response procedures

## Step-by-Step Guide

### Step 1: Define Service Level Indicators

Identify and implement key SLIs for MCP Mesh:

```yaml
# sli-definitions.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-mesh-slis
  namespace: monitoring
data:
  slis.yaml: |
    # MCP Mesh Service Level Indicators
    slis:
      # Availability SLI
      availability:
        description: "Percentage of successful requests"
        query: |
          (
            sum(rate(mcp_mesh_requests_total{status!="error"}[5m]))
            /
            sum(rate(mcp_mesh_requests_total[5m]))
          ) * 100
        unit: "percent"

      # Latency SLI - P95
      latency_p95:
        description: "95th percentile request latency"
        query: |
          histogram_quantile(0.95,
            sum by (le) (
              rate(mcp_mesh_request_duration_seconds_bucket[5m])
            )
          )
        unit: "seconds"

      # Latency SLI - P99
      latency_p99:
        description: "99th percentile request latency"
        query: |
          histogram_quantile(0.99,
            sum by (le) (
              rate(mcp_mesh_request_duration_seconds_bucket[5m])
            )
          )
        unit: "seconds"

      # Error Rate SLI
      error_rate:
        description: "Percentage of failed requests"
        query: |
          (
            sum(rate(mcp_mesh_requests_total{status="error"}[5m]))
            /
            sum(rate(mcp_mesh_requests_total[5m]))
          ) * 100
        unit: "percent"

      # Throughput SLI
      throughput:
        description: "Requests processed per second"
        query: |
          sum(rate(mcp_mesh_requests_total[5m]))
        unit: "requests/second"

      # Registry Health SLI
      registry_health:
        description: "Registry availability and responsiveness"
        query: |
          min(
            up{job="mcp-mesh-registry"} * 100,
            (
              rate(mcp_mesh_registry_request_duration_seconds_bucket{le="0.5"}[5m])
              /
              rate(mcp_mesh_registry_request_duration_seconds_count[5m])
            ) * 100
          )
        unit: "percent"

      # Agent Registration SLI
      agent_registration_time:
        description: "Time to register new agent"
        query: |
          histogram_quantile(0.95,
            sum by (le) (
              rate(mcp_mesh_registry_registration_duration_seconds_bucket[5m])
            )
          )
        unit: "seconds"
```

### Step 2: Establish Service Level Objectives

Define SLOs based on business requirements:

```yaml
# slo-definitions.yaml
apiVersion: sloth.slok.dev/v1
kind: PrometheusServiceLevel
metadata:
  name: mcp-mesh-slos
  namespace: monitoring
spec:
  service: "mcp-mesh"
  labels:
    team: "platform"
    tier: "critical"

  # SLO definitions
  slos:
    # 99.9% Availability SLO
    - name: "requests-availability"
      objective: 99.9
      description: "99.9% of requests should be successful"

      sli:
        raw:
          error_ratio_query: |
            sum(rate(mcp_mesh_requests_total{status="error"}[{% raw %}{{.window}}{% endraw %}]))
            /
            sum(rate(mcp_mesh_requests_total[{% raw %}{{.window}}{% endraw %}]))

      alerting:
        name: MCP_Mesh_HighErrorRate
        page_alert:
          labels:
            severity: critical
            team: platform
        ticket_alert:
          labels:
            severity: warning
            team: platform

    # Latency SLO - 95% of requests under 500ms
    - name: "latency-p95"
      objective: 95
      description: "95% of requests should complete within 500ms"

      sli:
        raw:
          error_ratio_query: |
            (
              sum(rate(mcp_mesh_request_duration_seconds_bucket{le="0.5"}[{% raw %}{{.window}}{% endraw %}]))
              /
              sum(rate(mcp_mesh_request_duration_seconds_count[{% raw %}{{.window}}{% endraw %}]))
            )

      alerting:
        name: MCP_Mesh_HighLatency
        page_alert:
          labels:
            severity: critical
        ticket_alert:
          labels:
            severity: warning

    # Registry Availability - 99.95%
    - name: "registry-availability"
      objective: 99.95
      description: "Registry should be available 99.95% of the time"

      sli:
        raw:
          error_ratio_query: |
            1 - avg(up{job="mcp-mesh-registry"})

      alerting:
        name: MCP_Mesh_RegistryDown
        page_alert:
          labels:
            severity: critical
            component: registry

---
# Error Budget Policy
apiVersion: v1
kind: ConfigMap
metadata:
  name: error-budget-policy
  namespace: monitoring
data:
  policy.yaml: |
    error_budget_policies:
      # When error budget is exhausted
      exhausted:
        - freeze_deployments: true
        - require_approval_for_changes: true
        - increase_testing_coverage: true
        - conduct_postmortem: true

      # When error budget is at risk (< 20% remaining)
      at_risk:
        - notify_on_call: true
        - review_recent_changes: true
        - increase_monitoring: true

      # When error budget is healthy (> 80% remaining)
      healthy:
        - allow_experimentation: true
        - deploy_normally: true
        - consider_relaxing_slos: false
```

### Step 3: Implement Multi-Tier Alerting

Create comprehensive alerting rules:

```yaml
# alerting-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: mcp-mesh-alerts
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
spec:
  groups:
    # Critical Alerts - Page immediately
    - name: mcp-mesh.critical
      interval: 30s
      rules:
        - alert: MCP_Mesh_RegistryDown
          expr: |
            up{job="mcp-mesh-registry"} == 0
          for: 2m
          labels:
            severity: critical
            component: registry
            team: platform
          annotations:
            summary: "MCP Mesh Registry is down"
            description: "Registry {% raw %}{{ $labels.instance }}{% endraw %} has been down for more than 2 minutes"
            runbook_url: "https://wiki.mcp-mesh.io/runbooks/registry-down"
            dashboard_url: "https://grafana.mcp-mesh.io/d/registry/overview"

        - alert: MCP_Mesh_HighErrorRate
          expr: |
            (
              sum(rate(mcp_mesh_requests_total{status="error"}[5m]))
              /
              sum(rate(mcp_mesh_requests_total[5m]))
            ) > 0.05
          for: 5m
          labels:
            severity: critical
            team: platform
          annotations:
            summary: "High error rate detected"
            description: "Error rate is {% raw %}{{ $value | humanizePercentage }}{% endraw %} (threshold: 5%)"
            runbook_url: "https://wiki.mcp-mesh.io/runbooks/high-error-rate"

        - alert: MCP_Mesh_SLO_BurnRate_High
          expr: |
            (
              mcp_mesh:slo:error_budget_burn_rate:1h > 14.4
              and
              mcp_mesh:slo:error_budget_burn_rate:5m > 14.4
            )
            or
            (
              mcp_mesh:slo:error_budget_burn_rate:6h > 6
              and
              mcp_mesh:slo:error_budget_burn_rate:30m > 6
            )
          labels:
            severity: critical
            team: platform
          annotations:
            summary: "SLO burn rate is critically high"
            description: "At this rate, the error budget will be exhausted in {% raw %}{{ $value | humanizeDuration }}{% endraw %}"
            runbook_url: "https://wiki.mcp-mesh.io/runbooks/slo-burn-rate"

    # Warning Alerts - Create ticket
    - name: mcp-mesh.warning
      interval: 60s
      rules:
        - alert: MCP_Mesh_HighLatency
          expr: |
            histogram_quantile(0.95,
              sum by (agent, le) (
                rate(mcp_mesh_request_duration_seconds_bucket[5m])
              )
            ) > 0.5
          for: 10m
          labels:
            severity: warning
            team: platform
          annotations:
            summary: "High latency on {% raw %}{{ $labels.agent }}{% endraw %}"
            description: "P95 latency is {% raw %}{{ $value }}{% endraw %}s (threshold: 0.5s)"
            dashboard_url: "https://grafana.mcp-mesh.io/d/agents/{% raw %}{{ $labels.agent }}{% endraw %}"

        - alert: MCP_Mesh_HighMemoryUsage
          expr: |
            (
              container_memory_working_set_bytes{pod=~"mcp-mesh-.*"}
              /
              container_spec_memory_limit_bytes{pod=~"mcp-mesh-.*"}
            ) > 0.8
          for: 15m
          labels:
            severity: warning
            team: platform
          annotations:
            summary: "High memory usage in {% raw %}{{ $labels.pod }}{% endraw %}"
            description: "Memory usage is {% raw %}{{ $value | humanizePercentage }}{% endraw %} of limit"

        - alert: MCP_Mesh_PodRestarts
          expr: |
            increase(kube_pod_container_status_restarts_total{namespace="mcp-mesh"}[1h]) > 5
          labels:
            severity: warning
            team: platform
          annotations:
            summary: "Pod {% raw %}{{ $labels.pod }}{% endraw %} is restarting frequently"
            description: "{% raw %}{{ $value }}{% endraw %} restarts in the last hour"

    # Info Alerts - Dashboard only
    - name: mcp-mesh.info
      interval: 5m
      rules:
        - alert: MCP_Mesh_DeploymentInProgress
          expr: |
            kube_deployment_status_replicas{namespace="mcp-mesh"}
            !=
            kube_deployment_status_replicas_available{namespace="mcp-mesh"}
          labels:
            severity: info
            team: platform
          annotations:
            summary: "Deployment in progress for {% raw %}{{ $labels.deployment }}{% endraw %}"
            description: "{% raw %}{{ $labels.deployment }}{% endraw %} has {% raw %}{{ $value }}{% endraw %} replicas updating"

        - alert: MCP_Mesh_CertificateExpiring
          expr: |
            (cert_manager_certificate_expiration_timestamp_seconds - time()) / 86400 < 30
          labels:
            severity: info
            team: platform
          annotations:
            summary: "Certificate expiring soon"
            description: "Certificate {% raw %}{{ $labels.name }}{% endraw %} expires in {% raw %}{{ $value }}{% endraw %} days"
```

### Step 4: Create Runbooks

Document response procedures for each alert:

````markdown
# runbooks/registry-down.md

# MCP Mesh Registry Down Runbook

## Alert: MCP_Mesh_RegistryDown

### Impact

- New agents cannot register
- Existing agents cannot discover services
- Service mesh functionality degraded

### Verification Steps

1. Check registry pod status:
   ```bash
   kubectl get pods -n mcp-mesh -l app=mcp-mesh-registry
   ```
````

2. Check recent events:

   ```bash
   kubectl get events -n mcp-mesh --sort-by='.lastTimestamp' | grep registry
   ```

3. Check logs:
   ```bash
   kubectl logs -n mcp-mesh -l app=mcp-mesh-registry --tail=100
   ```

### Resolution Steps

#### Step 1: Quick Recovery

```bash
# Try restarting the registry
kubectl rollout restart deployment/mcp-mesh-registry -n mcp-mesh

# Wait for rollout
kubectl rollout status deployment/mcp-mesh-registry -n mcp-mesh
```

#### Step 2: Check Database Connection

```bash
# Test database connectivity
kubectl exec -n mcp-mesh deployment/mcp-mesh-registry -- \
  pg_isready -h $DB_HOST -p $DB_PORT

# Check database status
kubectl get pods -n mcp-mesh -l app=postgresql
```

#### Step 3: Scale Out

```bash
# If single pod issue, scale up
kubectl scale deployment/mcp-mesh-registry -n mcp-mesh --replicas=3
```

#### Step 4: Failover to Backup

```bash
# If primary region down, failover to secondary
kubectl apply -f /emergency/registry-failover.yaml
```

### Post-Incident

1. Create incident report
2. Update monitoring thresholds if needed
3. Review registry HA configuration
4. Schedule postmortem meeting

````

### Step 5: Implement SLO Dashboards

Create comprehensive SLO monitoring dashboards:

```json
{
  "dashboard": {
    "title": "MCP Mesh SLO Overview",
    "uid": "mcp-mesh-slo",
    "panels": [
      {
        "title": "Error Budget Status",
        "type": "stat",
        "gridPos": {"h": 8, "w": 8, "x": 0, "y": 0},
        "targets": [
          {
            "expr": "(1 - ((1 - 0.999) - (1 - avg_over_time(mcp_mesh:slo:availability[30d])))) * 100",
            "legendFormat": "Remaining Budget %"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "red", "value": 0},
                {"color": "yellow", "value": 20},
                {"color": "green", "value": 50}
              ]
            }
          }
        }
      },

      {
        "title": "SLO Compliance - 28 Days",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 8, "x": 8, "y": 0},
        "targets": [
          {
            "expr": "avg_over_time(mcp_mesh:slo:availability[28d]) * 100",
            "legendFormat": "Availability"
          }
        ],
        "options": {
          "showThresholdLabels": true,
          "showThresholdMarkers": true
        },
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "min": 95,
            "max": 100,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "red", "value": 95},
                {"color": "yellow", "value": 99},
                {"color": "green", "value": 99.9}
              ]
            }
          }
        }
      },

      {
        "title": "Burn Rate",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 8, "x": 16, "y": 0},
        "targets": [
          {
            "expr": "mcp_mesh:slo:error_budget_burn_rate:1h",
            "legendFormat": "1h burn rate"
          },
          {
            "expr": "mcp_mesh:slo:error_budget_burn_rate:24h",
            "legendFormat": "24h burn rate"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 10
            },
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": 0},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 10}
              ]
            }
          }
        }
      },

      {
        "title": "SLI Trends",
        "type": "timeseries",
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": 8},
        "targets": [
          {
            "expr": "mcp_mesh:sli:availability",
            "legendFormat": "Availability"
          },
          {
            "expr": "100 - (mcp_mesh:sli:error_rate * 100)",
            "legendFormat": "Success Rate"
          },
          {
            "expr": "(mcp_mesh:sli:latency_p95 < 0.5) * 100",
            "legendFormat": "Latency SLI"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "min": 90,
            "max": 100
          }
        }
      }
    ]
  }
}
````

### Step 6: Implement Alert Routing

Configure intelligent alert routing:

```yaml
# alertmanager-config.yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-mcp-mesh
  namespace: monitoring
stringData:
  alertmanager.yaml: |
    global:
      resolve_timeout: 5m
      slack_api_url: ${SLACK_API_URL}
      pagerduty_url: https://events.pagerduty.com/v2/enqueue

    # Alert routing tree
    route:
      group_by: ['alertname', 'cluster', 'service']
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 12h
      receiver: 'default'

      routes:
      # Critical alerts - page immediately
      - match:
          severity: critical
        receiver: pagerduty-critical
        group_wait: 0s
        repeat_interval: 1h
        continue: true

      # Critical alerts also go to Slack
      - match:
          severity: critical
        receiver: slack-critical

      # Warning alerts - ticket only
      - match:
          severity: warning
        receiver: slack-warnings
        group_wait: 5m
        group_interval: 5m
        repeat_interval: 4h

      # Info alerts - dashboard only
      - match:
          severity: info
        receiver: slack-info
        group_wait: 30m
        group_interval: 30m
        repeat_interval: 24h

      # Team-specific routing
      - match:
          team: platform
        receiver: platform-team
        routes:
        - match:
            component: registry
          receiver: registry-oncall

    # Inhibition rules
    inhibit_rules:
    - source_match:
        severity: 'critical'
      target_match:
        severity: 'warning'
      equal: ['alertname', 'instance']

    - source_match:
        alertname: 'MCP_Mesh_RegistryDown'
      target_match_re:
        alertname: 'MCP_Mesh_.*'
      equal: ['instance']

    # Receivers
    receivers:
    - name: 'default'
      slack_configs:
      - channel: '#alerts-default'
        title: 'MCP Mesh Alert'
        text: '{% raw %}{{ range .Alerts }}{% endraw %}{% raw %}{{ .Annotations.summary }}{% endraw %}{% raw %}{{ end }}{% endraw %}'

    - name: 'pagerduty-critical'
      pagerduty_configs:
      - service_key: ${PAGERDUTY_SERVICE_KEY}
        description: '{% raw %}{{ .GroupLabels.alertname }}{% endraw %}: {% raw %}{{ .CommonAnnotations.summary }}{% endraw %}'
        details:
          firing: '{% raw %}{{ .Alerts.Firing | len }}{% endraw %}'
          resolved: '{% raw %}{{ .Alerts.Resolved | len }}{% endraw %}'
          labels: '{% raw %}{{ .CommonLabels }}{% endraw %}'
        links:
        - href: '{% raw %}{{ .CommonAnnotations.dashboard_url }}{% endraw %}'
          text: 'Dashboard'
        - href: '{% raw %}{{ .CommonAnnotations.runbook_url }}{% endraw %}'
          text: 'Runbook'

    - name: 'slack-critical'
      slack_configs:
      - channel: '#alerts-critical'
        color: 'danger'
        title: '🚨 CRITICAL: {% raw %}{{ .GroupLabels.alertname }}{% endraw %}'
        text: |
          {% raw %}{{ range .Alerts.Firing }}{% endraw %}
          *Alert:* {% raw %}{{ .Annotations.summary }}{% endraw %}
          *Description:* {% raw %}{{ .Annotations.description }}{% endraw %}
          *Runbook:* <{% raw %}{{ .Annotations.runbook_url }}{% endraw %}|View Runbook>
          *Dashboard:* <{% raw %}{{ .Annotations.dashboard_url }}{% endraw %}|View Dashboard>
          {% raw %}{{ end }}{% endraw %}
        send_resolved: true

    - name: 'slack-warnings'
      slack_configs:
      - channel: '#alerts-warning'
        color: 'warning'
        title: '⚠️ Warning: {% raw %}{{ .GroupLabels.alertname }}{% endraw %}'
        text: '{% raw %}{{ .CommonAnnotations.summary }}{% endraw %}'
        send_resolved: true

    - name: 'platform-team'
      webhook_configs:
      - url: 'http://incident-bot:8080/webhook'
        send_resolved: true
```

## Configuration Options

| Component        | Setting | Description                 |
| ---------------- | ------- | --------------------------- |
| SLO Target       | `99.9%` | Availability objective      |
| Error Budget     | `0.1%`  | Allowable downtime          |
| Burn Rate Alert  | `14.4x` | 1-hour burn rate threshold  |
| Alert Evaluation | `30s`   | How often to evaluate rules |
| Alert Delay      | `5m`    | Wait before firing          |

## Examples

### Example 1: Custom SLO for Business Metrics

```yaml
# business-slo.yaml
apiVersion: sloth.slok.dev/v1
kind: PrometheusServiceLevel
metadata:
  name: business-slos
spec:
  service: "mcp-mesh-business"
  slos:
    - name: "transaction-success"
      objective: 99.95
      description: "99.95% of payment transactions should succeed"

      sli:
        raw:
          error_ratio_query: |
            sum(rate(mcp_mesh_business_transactions_total{status="failed"}[{% raw %}{{.window}}{% endraw %}]))
            /
            sum(rate(mcp_mesh_business_transactions_total[{% raw %}{{.window}}{% endraw %}]))

      alerting:
        name: BusinessTransactionFailures
        page_alert:
          labels:
            severity: critical
            team: business

    - name: "api-cost-efficiency"
      objective: 95
      description: "95% of API calls should stay under cost threshold"

      sli:
        raw:
          error_ratio_query: |
            (
              sum(rate(mcp_mesh_api_calls_total{cost_exceeded="true"}[{% raw %}{{.window}}{% endraw %}]))
              /
              sum(rate(mcp_mesh_api_calls_total[{% raw %}{{.window}}{% endraw %}]))
            )
```

### Example 2: Adaptive Alerting

```python
# adaptive_alerting.py
from prometheus_api_client import PrometheusConnect
import numpy as np
from datetime import datetime, timedelta

class AdaptiveAlerting:
    """Implement adaptive thresholds based on historical data"""

    def __init__(self, prometheus_url: str):
        self.prom = PrometheusConnect(url=prometheus_url)

    def calculate_dynamic_threshold(self, metric: str,
                                  lookback_days: int = 7,
                                  sensitivity: float = 3.0):
        """Calculate dynamic threshold using statistical methods"""

        # Get historical data
        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)

        # Query data points
        data = self.prom.custom_query_range(
            query=metric,
            start_time=start_time,
            end_time=end_time,
            step='5m'
        )

        if not data:
            return None

        # Extract values
        values = [float(point[1]) for point in data[0]['values']]

        # Calculate statistics
        mean = np.mean(values)
        std = np.std(values)

        # Calculate percentiles
        p50 = np.percentile(values, 50)
        p95 = np.percentile(values, 95)
        p99 = np.percentile(values, 99)

        # Dynamic threshold based on time of day
        hour = datetime.now().hour
        if 9 <= hour <= 17:  # Business hours
            threshold = mean + (sensitivity * std)
        else:  # Off hours
            threshold = mean + ((sensitivity + 1) * std)

        return {
            'threshold': threshold,
            'mean': mean,
            'std': std,
            'p50': p50,
            'p95': p95,
            'p99': p99,
            'current_hour': hour
        }

    def generate_alert_rule(self, metric_name: str,
                          threshold_info: dict):
        """Generate Prometheus alert rule with dynamic threshold"""

        return f"""
        - alert: {metric_name}_DynamicThreshold
          expr: |
            {metric_name} > {threshold_info['threshold']}
          for: 5m
          labels:
            severity: warning
            threshold_type: dynamic
          annotations:
            summary: "{metric_name} exceeds dynamic threshold"
            description: |
              Current value: {% raw %}{{{{ $value }}{% endraw %}}}
              Dynamic threshold: {threshold_info['threshold']:.2f}
              Based on mean: {threshold_info['mean']:.2f} (±{threshold_info['std']:.2f})
              P95: {threshold_info['p95']:.2f}, P99: {threshold_info['p99']:.2f}
        """

# Usage
alerting = AdaptiveAlerting("http://prometheus:9090")

# Calculate dynamic threshold for request rate
threshold = alerting.calculate_dynamic_threshold(
    "rate(mcp_mesh_requests_total[5m])"
)

print(f"Dynamic threshold: {threshold['threshold']:.2f} req/s")
print(f"Based on historical mean: {threshold['mean']:.2f} (±{threshold['std']:.2f})")
```

## Best Practices

1. **Start with Loose SLOs**: Tighten gradually based on data
2. **Multi-Window Alerts**: Use multiple burn rate windows
3. **Actionable Alerts**: Every alert should have clear actions
4. **Regular Review**: Review SLOs and alerts monthly
5. **Blameless Culture**: Focus on improvement, not blame

## Common Pitfalls

### Pitfall 1: Too Many Alerts

**Problem**: Alert fatigue from non-actionable alerts

**Solution**: Implement alert quality metrics:

```yaml
# Track alert quality
- record: alerts:quality:actionable_ratio
  expr: |
    sum(rate(alertmanager_alerts_resolved{resolved_by="human"}[7d]))
    /
    sum(rate(alertmanager_alerts_resolved[7d]))

# Remove alerts with low actionable ratio
- alert: AlertQualityLow
  expr: alerts:quality:actionable_ratio < 0.5
  annotations:
    summary: "Alert {% raw %}{{ $labels.alertname }}{% endraw %} has low actionable ratio"
    description: "Only {% raw %}{{ $value | humanizePercentage }}{% endraw %} of alerts were actionable"
```

### Pitfall 2: Unrealistic SLOs

**Problem**: SLOs set too high, constantly violated

**Solution**: Base SLOs on historical performance:

```promql
# Calculate realistic SLO based on past performance
# Use P90 of historical availability as starting point
quantile_over_time(0.9,
  avg_over_time(
    up{job="mcp-mesh"}[1d]
  )[30d:1d]
) * 100
```

## Testing

### Test Alert Rules

```python
# test_alerts.py
import pytest
from prometheus_api_client import PrometheusConnect

def test_alert_rules():
    """Test that alert rules are valid and fire correctly"""
    prom = PrometheusConnect(url="http://localhost:9090")

    # Get all configured alerts
    alerts = prom.custom_query("ALERTS")

    # Test specific alert conditions
    test_cases = [
        {
            "alert": "MCP_Mesh_HighErrorRate",
            "condition": "rate(mcp_mesh_requests_total{status='error'}[5m]) > 0.05",
            "should_fire": True
        },
        {
            "alert": "MCP_Mesh_RegistryDown",
            "condition": "up{job='mcp-mesh-registry'} == 0",
            "should_fire": False  # Should not fire in healthy system
        }
    ]

    for test in test_cases:
        result = prom.custom_query(test["condition"])
        if test["should_fire"]:
            assert len(result) > 0, f"{test['alert']} should fire"
        else:
            assert len(result) == 0, f"{test['alert']} should not fire"

def test_slo_calculations():
    """Test SLO calculation accuracy"""
    prom = PrometheusConnect(url="http://localhost:9090")

    # Test availability SLO
    availability = prom.custom_query(
        "avg_over_time(mcp_mesh:slo:availability[1h])"
    )
    assert 0 <= float(availability[0]['value'][1]) <= 1

    # Test error budget
    error_budget = prom.custom_query(
        "mcp_mesh:slo:error_budget_remaining"
    )
    assert 0 <= float(error_budget[0]['value'][1]) <= 1
```

### Chaos Testing for Alerts

```bash
#!/bin/bash
# chaos-test-alerts.sh

echo "Testing alert firing conditions..."

# Test 1: High error rate
echo "Injecting errors..."
for i in {1..100}; do
  curl -X POST http://localhost:8080/error-injection \
    -d '{"error_rate": 0.1, "duration": "60s"}'
done

# Wait for alert
sleep 120
kubectl logs -n monitoring alertmanager-0 | grep "MCP_Mesh_HighErrorRate"

# Test 2: Registry failure
echo "Stopping registry..."
kubectl scale deployment mcp-mesh-registry -n mcp-mesh --replicas=0

# Check if alert fires within 5 minutes
sleep 300
kubectl logs -n monitoring alertmanager-0 | grep "MCP_Mesh_RegistryDown"

# Restore
kubectl scale deployment mcp-mesh-registry -n mcp-mesh --replicas=3
```

## Monitoring and Debugging

### Monitor Alert Health

```yaml
# alert-health-dashboard.json
{
  "dashboard":
    {
      "title": "Alert Health",
      "panels":
        [
          {
            "title": "Alert Firing Rate",
            "targets":
              [
                {
                  "expr": "sum by (alertname) (rate(alertmanager_notifications_total[5m]))",
                },
              ],
          },
          {
            "title": "Alert Resolution Time",
            "targets":
              [
                {
                  "expr": "histogram_quantile(0.95, alertmanager_alert_resolution_duration_seconds_bucket)",
                },
              ],
          },
          {
            "title": "Failed Notifications",
            "targets":
              [
                {
                  "expr": "sum by (integration) (rate(alertmanager_notifications_failed_total[5m]))",
                },
              ],
          },
        ],
    },
}
```

### Debug SLO Violations

```bash
# Check SLO status
curl -s http://prometheus:9090/api/v1/query \
  -d 'query=mcp_mesh:slo:error_budget_remaining' | jq

# Get burn rate history
curl -s http://prometheus:9090/api/v1/query_range \
  -d 'query=mcp_mesh:slo:error_budget_burn_rate:1h' \
  -d 'start=now-24h' \
  -d 'end=now' \
  -d 'step=5m' | jq

# Find when budget was exhausted
curl -s http://prometheus:9090/api/v1/query \
  -d 'query=mcp_mesh:slo:error_budget_remaining == 0' | jq
```

## 🔧 Troubleshooting

### Issue 1: Alerts Not Firing

**Symptoms**: Known issues but no alerts received

**Cause**: Misconfigured rules or routing

**Solution**:

```bash
# Check if alerts are pending
kubectl exec -n monitoring prometheus-0 -- \
  promtool query instant http://localhost:9090 'ALERTS{alertstate="pending"}'

# Verify AlertManager configuration
kubectl logs -n monitoring alertmanager-0 | grep error

# Test alert routing
amtool config routes test \
  --config.file=/etc/alertmanager/alertmanager.yaml \
  --tree \
  --verify.receivers=slack-critical \
  severity=critical alertname=TestAlert
```

### Issue 2: SLO Always Violated

**Symptoms**: SLO compliance always below target

**Cause**: Unrealistic objectives or calculation errors

**Solution**:

```promql
# Debug SLO calculation
# Check raw error ratio
sum(rate(mcp_mesh_requests_total{status="error"}[5m]))
/
sum(rate(mcp_mesh_requests_total[5m]))

# Check if data exists
sum(rate(mcp_mesh_requests_total[5m])) > 0

# Verify time windows
increase(mcp_mesh_requests_total[30d])
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **SLO Window**: Minimum practical window is 28 days
- **Alert Delay**: Minimum 30s evaluation interval
- **Burn Rate**: Requires sufficient traffic for accuracy
- **Multi-Region**: SLOs are per-region, not global

## 📝 TODO

- [ ] Add ML-based anomaly detection
- [ ] Implement alert correlation
- [ ] Create mobile app integration
- [ ] Add voice call escalation
- [ ] Document multi-region SLOs

## Summary

You now have comprehensive alerting and SLOs:

Key takeaways:

- 🔑 Well-defined SLIs and SLOs
- 🔑 Multi-tier alerting strategy
- 🔑 Error budget tracking
- 🔑 Runbooks for every alert

## Next Steps

Complete the observability section with troubleshooting guide.

Continue to [Observability Troubleshooting](./troubleshooting.md) →

---

💡 **Tip**: Use error budget policies to automatically restrict deployments when budget is low

📚 **Reference**: [Google SRE Book - Alerting](https://sre.google/sre-book/monitoring-distributed-systems/)

🧪 **Try It**: Implement a game day to test your alerting and response procedures
