# Prometheus Integration

> Collect, store, and query metrics from your MCP Mesh deployment

## Overview

Prometheus is the de facto standard for metrics collection in Kubernetes environments. This guide covers integrating Prometheus with MCP Mesh to collect metrics from the registry, agents, and infrastructure. You'll learn how to configure scraping, create recording rules, optimize storage, and write efficient queries.

Proper Prometheus integration provides the foundation for monitoring, alerting, and performance analysis of your MCP Mesh deployment.

## Key Concepts

- **Metrics Types**: Counter, Gauge, Histogram, Summary
- **Service Discovery**: Kubernetes SD for automatic target discovery
- **Recording Rules**: Pre-computed queries for efficiency
- **Federation**: Scaling Prometheus across clusters
- **Remote Storage**: Long-term retention strategies

## Step-by-Step Guide

### Step 1: Deploy Prometheus Operator

The Prometheus Operator simplifies deployment and management:

```bash
# Install kube-prometheus-stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Create monitoring namespace
kubectl create namespace monitoring

# Install with custom values
cat > prometheus-values.yaml << 'EOF'
prometheus:
  prometheusSpec:
    # Enable ServiceMonitor discovery
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false

    # Retention configuration
    retention: 30d
    retentionSize: 50GB

    # Resource allocation
    resources:
      requests:
        memory: 2Gi
        cpu: 1
      limits:
        memory: 4Gi
        cpu: 2

    # Storage configuration
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: fast-ssd
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

    # Scrape configuration
    scrapeInterval: 30s
    evaluationInterval: 30s

    # Enable features
    enableFeatures:
      - exemplar-storage
      - memory-snapshot-on-shutdown

# Grafana configuration
grafana:
  enabled: true
  adminPassword: "changeme"
  persistence:
    enabled: true
    size: 10Gi

# AlertManager configuration
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname', 'namespace']
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 12h
      receiver: 'default'
    receivers:
    - name: 'default'
      slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK_URL'
        channel: '#alerts'
EOF

# Install Prometheus stack
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values prometheus-values.yaml
```

### Step 2: Configure MCP Mesh Metrics

Implement metrics in MCP Mesh components:

```python
# mcp_mesh/metrics.py
from prometheus_client import Counter, Histogram, Gauge, Info
from prometheus_client import CollectorRegistry, generate_latest
import time
from functools import wraps

# Create registry
REGISTRY = CollectorRegistry()

# Define metrics
agent_info = Info(
    'mcp_mesh_agent',
    'MCP Mesh agent information',
    ['agent_name', 'version', 'capabilities'],
    registry=REGISTRY
)

request_count = Counter(
    'mcp_mesh_requests_total',
    'Total number of requests processed',
    ['agent', 'method', 'status'],
    registry=REGISTRY
)

request_duration = Histogram(
    'mcp_mesh_request_duration_seconds',
    'Request duration in seconds',
    ['agent', 'method'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY
)

active_connections = Gauge(
    'mcp_mesh_connections_active',
    'Number of active connections',
    ['agent', 'type'],
    registry=REGISTRY
)

registry_agents = Gauge(
    'mcp_mesh_registry_agents_total',
    'Total number of registered agents',
    ['status'],
    registry=REGISTRY
)

# Decorator for timing functions
def track_request_duration(agent_name, method):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                request_count.labels(
                    agent=agent_name,
                    method=method,
                    status=status
                ).inc()
                request_duration.labels(
                    agent=agent_name,
                    method=method
                ).observe(duration)
        return wrapper
    return decorator

# Metrics endpoint handler
async def metrics_handler(request):
    """Prometheus metrics endpoint"""
    metrics = generate_latest(REGISTRY)
    return Response(
        body=metrics,
        content_type="text/plain; version=0.0.4; charset=utf-8"
    )

# Usage in agent
class WeatherAgent:
    def __init__(self, name="weather-agent"):
        self.name = name
        # Set agent info
        agent_info.labels(
            agent_name=self.name,
            version="1.0.0",
            capabilities="weather_forecast,weather_current"
        ).set(1)

        # Track connections
        active_connections.labels(
            agent=self.name,
            type="client"
        ).set(0)

    @track_request_duration("weather-agent", "get_forecast")
    async def get_forecast(self, location: str):
        """Get weather forecast with metrics"""
        # Increment active connections
        active_connections.labels(
            agent=self.name,
            type="client"
        ).inc()

        try:
            # Your forecast logic here
            forecast = await self._fetch_forecast(location)
            return forecast
        finally:
            # Decrement active connections
            active_connections.labels(
                agent=self.name,
                type="client"
            ).dec()
```

### Step 3: Create ServiceMonitors

Define ServiceMonitors for Prometheus to discover MCP Mesh services:

```yaml
# servicemonitor-registry.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mcp-mesh-registry
  namespace: mcp-mesh
  labels:
    app: mcp-mesh
    component: registry
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: mcp-mesh-registry
  endpoints:
    - port: http
      interval: 30s
      path: /metrics
      # Add trace_id to metrics for correlation
      metricRelabelings:
        - sourceLabels: [__name__]
          targetLabel: __tmp_prometheus_job_name
        - sourceLabels: [trace_id]
          targetLabel: trace_id
          regex: "(.*)"
          replacement: "${1}"
        # Drop high-cardinality metrics
        - sourceLabels: [__name__]
          regex: "go_memstats_.*"
          action: drop

---
# servicemonitor-agents.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mcp-mesh-agents
  namespace: mcp-mesh
  labels:
    app: mcp-mesh
    component: agent
spec:
  selector:
    matchLabels:
      app.kubernetes.io/part-of: mcp-mesh
      app.kubernetes.io/component: agent
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
      # Honor agent-provided timestamps
      honorTimestamps: true
      # Add agent name from pod label
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_label_agent_name]
          targetLabel: agent
        - sourceLabels: [__meta_kubernetes_pod_namespace]
          targetLabel: namespace
        - sourceLabels: [__meta_kubernetes_pod_name]
          targetLabel: pod
```

### Step 4: Configure Recording Rules

Create recording rules for common queries:

```yaml
# recording-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: mcp-mesh-recording-rules
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
spec:
  groups:
    - name: mcp_mesh.rules
      interval: 30s
      rules:
        # Request rate by agent
        - record: mcp_mesh:request_rate
          expr: |
            sum by (agent, namespace) (
              rate(mcp_mesh_requests_total[5m])
            )

        # Error rate by agent
        - record: mcp_mesh:error_rate
          expr: |
            sum by (agent, namespace) (
              rate(mcp_mesh_requests_total{status="error"}[5m])
            ) / ignoring(status) group_left
            sum by (agent, namespace) (
              rate(mcp_mesh_requests_total[5m])
            )

        # P95 latency by agent
        - record: mcp_mesh:request_duration:p95
          expr: |
            histogram_quantile(0.95,
              sum by (agent, namespace, le) (
                rate(mcp_mesh_request_duration_seconds_bucket[5m])
              )
            )

        # Active connections per agent
        - record: mcp_mesh:connections:sum
          expr: |
            sum by (agent, namespace) (
              mcp_mesh_connections_active
            )

        # Registry health score
        - record: mcp_mesh:registry:health_score
          expr: |
            (
              up{job="mcp-mesh-registry"} * 100
              + (1 - mcp_mesh:error_rate{agent="registry"}) * 50
              + (mcp_mesh:request_duration:p95{agent="registry"} < 0.5) * 50
            ) / 2

    - name: mcp_mesh.slo
      interval: 30s
      rules:
        # Availability SLO
        - record: mcp_mesh:slo:availability
          expr: |
            1 - (
              sum by (agent) (
                rate(mcp_mesh_requests_total{status="error"}[5m])
              ) / ignoring(status) group_left
              sum by (agent) (
                rate(mcp_mesh_requests_total[5m])
              )
            )

        # Latency SLO
        - record: mcp_mesh:slo:latency
          expr: |
            histogram_quantile(0.95,
              sum by (agent, le) (
                rate(mcp_mesh_request_duration_seconds_bucket[5m])
              )
            ) < bool 1.0
```

### Step 5: Optimize Prometheus Performance

Configure Prometheus for optimal performance:

```yaml
# prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config-custom
  namespace: monitoring
data:
  prometheus.yaml: |
    global:
      scrape_interval: 30s
      scrape_timeout: 10s
      evaluation_interval: 30s

      # External labels for federation
      external_labels:
        cluster: 'production'
        region: 'us-east-1'

    # Remote write for long-term storage
    remote_write:
    - url: https://prometheus-storage.example.com/api/v1/write
      remote_timeout: 30s
      queue_config:
        capacity: 10000
        max_shards: 30
        min_shards: 1
        max_samples_per_send: 5000
        batch_send_deadline: 5s
        min_backoff: 30ms
        max_backoff: 100ms

      # Only send aggregated metrics
      write_relabel_configs:
      - source_labels: [__name__]
        regex: 'mcp_mesh:.*'
        action: keep

    # Alerting configuration
    alerting:
      alertmanagers:
      - static_configs:
        - targets:
          - alertmanager:9093

    # Scrape configs
    scrape_configs:
    # MCP Mesh registry with higher frequency
    - job_name: 'mcp-mesh-registry'
      scrape_interval: 15s
      kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names:
          - mcp-mesh
      relabel_configs:
      - source_labels: [__meta_kubernetes_service_name]
        regex: '.*registry.*'
        action: keep
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_service_name]
        target_label: service

    # MCP Mesh agents
    - job_name: 'mcp-mesh-agents'
      kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
          - mcp-mesh
      relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
        target_label: __address__
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
        target_label: agent_name
      - source_labels: [__meta_kubernetes_pod_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
```

### Step 6: Set Up Federation

Configure Prometheus federation for multi-cluster setups:

```yaml
# federation-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-federation
  namespace: monitoring
data:
  federation.yaml: |
    # Global Prometheus configuration
    scrape_configs:
    - job_name: 'federate'
      scrape_interval: 15s
      honor_labels: true
      metrics_path: '/federate'
      params:
        'match[]':
        # Only federate aggregated metrics
        - 'mcp_mesh:.*'
        - 'up{job=~"mcp-mesh.*"}'
        - 'prometheus_build_info'
      static_configs:
      - targets:
        - 'prometheus-us-east-1:9090'
        - 'prometheus-us-west-2:9090'
        - 'prometheus-eu-west-1:9090'
      relabel_configs:
      - source_labels: [__address__]
        regex: 'prometheus-(.*):9090'
        target_label: source_cluster
        replacement: '$1'
```

## Configuration Options

| Component       | Configuration | Description                  |
| --------------- | ------------- | ---------------------------- |
| Scrape Interval | `30s`         | How often to collect metrics |
| Retention       | `30d`         | How long to keep metrics     |
| Storage         | `100Gi`       | Prometheus data storage      |
| Memory          | `4Gi`         | Prometheus memory limit      |
| Remote Write    | Enabled       | Long-term storage            |

## Examples

### Example 1: Custom Business Metrics

```python
# business_metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Business KPIs
revenue_counter = Counter(
    'mcp_mesh_business_revenue_total',
    'Total revenue processed',
    ['agent', 'currency', 'product'],
    registry=REGISTRY
)

api_calls_counter = Counter(
    'mcp_mesh_business_api_calls_total',
    'Total external API calls',
    ['agent', 'api_provider', 'endpoint'],
    registry=REGISTRY
)

cache_hit_rate = Gauge(
    'mcp_mesh_cache_hit_rate',
    'Cache hit rate percentage',
    ['agent', 'cache_type'],
    registry=REGISTRY
)

class AnalyticsAgent:
    @track_request_duration("analytics", "process_transaction")
    async def process_transaction(self, transaction):
        """Process transaction with business metrics"""
        # Track revenue
        revenue_counter.labels(
            agent="analytics",
            currency=transaction.currency,
            product=transaction.product
        ).inc(transaction.amount)

        # Track API usage
        if transaction.requires_external_validation:
            api_calls_counter.labels(
                agent="analytics",
                api_provider="payment-gateway",
                endpoint="validate"
            ).inc()

        # Update cache metrics
        hit_rate = await self.cache.get_hit_rate()
        cache_hit_rate.labels(
            agent="analytics",
            cache_type="redis"
        ).set(hit_rate * 100)
```

### Example 2: Advanced Queries

```promql
# Top 5 agents by request rate
topk(5,
  sum by (agent) (
    rate(mcp_mesh_requests_total[5m])
  )
)

# Agents with error rate > 1%
sum by (agent) (
  rate(mcp_mesh_requests_total{status="error"}[5m])
) / ignoring(status) group_left
sum by (agent) (
  rate(mcp_mesh_requests_total[5m])
) > 0.01

# Request duration heatmap
sum by (le) (
  rate(mcp_mesh_request_duration_seconds_bucket[5m])
)

# Week-over-week comparison
(
  sum by (agent) (
    rate(mcp_mesh_requests_total[5m])
  ) -
  sum by (agent) (
    rate(mcp_mesh_requests_total[5m] offset 1w)
  )
) / sum by (agent) (
  rate(mcp_mesh_requests_total[5m] offset 1w)
) * 100

# Predict resource usage
predict_linear(
  mcp_mesh_connections_active[1h],
  3600 * 4  # 4 hours
)
```

## Best Practices

1. **Label Cardinality**: Keep label values bounded
2. **Metric Naming**: Follow Prometheus conventions
3. **Recording Rules**: Pre-compute expensive queries
4. **Retention Policy**: Balance cost vs history
5. **Federation**: Only federate aggregated metrics

## Common Pitfalls

### Pitfall 1: High Cardinality

**Problem**: Too many unique label combinations

**Solution**: Limit label values:

```python
# Bad - unbounded cardinality
request_count.labels(
    user_id=user.id,  # Millions of values!
    endpoint=endpoint
).inc()

# Good - bounded cardinality
request_count.labels(
    user_type=user.type,  # Limited values
    endpoint=endpoint
).inc()
```

### Pitfall 2: Missing Metrics

**Problem**: Metrics not appearing in Prometheus

**Solution**: Check discovery and networking:

```bash
# Verify endpoints
kubectl get endpoints -n mcp-mesh

# Check ServiceMonitor
kubectl describe servicemonitor mcp-mesh-registry -n mcp-mesh

# Test metrics endpoint
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8080
curl http://localhost:8080/metrics

# Check Prometheus targets
kubectl port-forward -n monitoring svc/prometheus-operated 9090
# Visit http://localhost:9090/targets
```

## Testing

### Validate Metrics

```python
# test_metrics.py
import pytest
from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families

def test_metrics_registration():
    """Test that all metrics are properly registered"""
    # Get all metrics
    metrics = list(REGISTRY.collect())

    # Verify expected metrics exist
    metric_names = [m.name for m in metrics]
    assert 'mcp_mesh_requests_total' in metric_names
    assert 'mcp_mesh_request_duration_seconds' in metric_names

def test_metrics_format():
    """Test metrics are in correct format"""
    from mcp_mesh.metrics import generate_latest

    output = generate_latest(REGISTRY).decode('utf-8')

    # Parse metrics
    families = list(text_string_to_metric_families(output))

    # Verify format
    for family in families:
        assert family.name.startswith('mcp_mesh_')
        assert family.documentation
        assert family.type in ['counter', 'gauge', 'histogram', 'summary']
```

### Load Testing

```bash
#!/bin/bash
# load-test-metrics.sh

echo "Testing Prometheus under load..."

# Generate load
for i in {1..1000}; do
  curl -s http://mcp-mesh-registry:8080/api/agents &
done
wait

# Check Prometheus performance
curl -s http://prometheus:9090/api/v1/query \
  -d 'query=rate(prometheus_engine_query_duration_seconds_sum[5m])' | \
  jq '.data.result[0].value[1]'

# Check memory usage
curl -s http://prometheus:9090/api/v1/query \
  -d 'query=prometheus_tsdb_symbol_table_size_bytes' | \
  jq '.data.result[0].value[1]' | \
  awk '{print $1/1024/1024 " MB"}'
```

## Monitoring and Debugging

### Monitor Prometheus Health

```yaml
# prometheus-monitoring.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: prometheus-health
  namespace: monitoring
spec:
  groups:
    - name: prometheus.rules
      rules:
        - alert: PrometheusHighMemoryUsage
          expr: |
            (
              prometheus_tsdb_symbol_table_size_bytes /
              prometheus_tsdb_storage_blocks_bytes
            ) > 0.5
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Prometheus high memory usage"
            description: "Prometheus {%raw%}{{ $labels.instance }}{%endraw%} memory usage is high"

        - alert: PrometheusTargetDown
          expr: up{job=~"mcp-mesh.*"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "MCP Mesh target down"
            description: "Target {%raw%}{{ $labels.instance }}{%endraw%} is down"
```

### Debug Metrics Issues

```bash
# Check Prometheus configuration
kubectl exec -n monitoring prometheus-0 -- \
  promtool check config /etc/prometheus/config_out/prometheus.env.yaml

# View Prometheus logs
kubectl logs -n monitoring prometheus-0 -c prometheus

# Check TSDB status
kubectl exec -n monitoring prometheus-0 -- \
  promtool tsdb analyze /prometheus

# Cardinality analysis
kubectl port-forward -n monitoring svc/prometheus-operated 9090
curl -s http://localhost:9090/api/v1/label/__name__/values | \
  jq -r '.data[]' | wc -l
```

## 🔧 Troubleshooting

### Issue 1: Metrics Not Collected

**Symptoms**: No data in Prometheus for MCP Mesh

**Cause**: ServiceMonitor not matched or network issues

**Solution**:

```bash
# Check ServiceMonitor labels match Prometheus
kubectl get prometheus -n monitoring -o yaml | grep -A5 serviceMonitorSelector

# Ensure labels match
kubectl label servicemonitor mcp-mesh-registry -n mcp-mesh \
  prometheus=kube-prometheus

# Restart Prometheus
kubectl rollout restart statefulset prometheus-prometheus -n monitoring
```

### Issue 2: High Memory Usage

**Symptoms**: Prometheus OOMKilled

**Cause**: Too many metrics or high cardinality

**Solution**:

```yaml
# Add metric relabeling to drop unnecessary metrics
metricRelabelings:
  - sourceLabels: [__name__]
    regex: "go_.*|process_.*"
    action: drop

# Reduce retention
prometheusSpec:
  retention: 7d
  retentionSize: 20GB
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Storage**: Local storage not suitable for HA
- **Cardinality**: Limited by available memory
- **Query Performance**: Complex queries can be slow
- **Data Loss**: Possible during restarts without persistent storage

## 📝 TODO

- [ ] Add Thanos sidecar configuration
- [ ] Document multi-tenancy setup
- [ ] Create example Jsonnet dashboards
- [ ] Add PromQL query library
- [ ] Document sharding strategies

## Summary

You now have Prometheus integrated with MCP Mesh:

Key takeaways:

- 🔑 Metrics collection from all components
- 🔑 Efficient storage and querying
- 🔑 Recording rules for performance
- 🔑 Federation for multi-cluster

## Next Steps

Let's visualize these metrics with Grafana dashboards.

Continue to [Grafana Dashboards](./02-grafana-dashboards.md) →

---

💡 **Tip**: Use Prometheus query inspector to understand query performance: `EXPLAIN <query>`

📚 **Reference**: [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)

🧪 **Try It**: Write a recording rule for your most common query to improve dashboard performance
