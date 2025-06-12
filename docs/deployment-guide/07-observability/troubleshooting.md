# Observability Troubleshooting

> Comprehensive guide to diagnosing and resolving observability issues in MCP Mesh

## Overview

This troubleshooting guide covers common issues encountered when implementing observability for MCP Mesh. Each issue includes symptoms, root causes, diagnostic steps, and solutions. The guide is organized by observability component to help you quickly find relevant solutions.

## Quick Diagnostics

Run this diagnostic script first:

```bash
#!/bin/bash
# observability-diagnostics.sh

echo "=== MCP Mesh Observability Diagnostics ==="
echo "Date: $(date)"
echo ""

# Check Prometheus
echo "1. Prometheus Status:"
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
kubectl top pods -n monitoring -l app.kubernetes.io/name=prometheus

# Check Grafana
echo -e "\n2. Grafana Status:"
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
curl -s http://localhost:3000/api/health || echo "Grafana not accessible"

# Check Jaeger
echo -e "\n3. Jaeger Status:"
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger
curl -s http://localhost:16686/api/services || echo "Jaeger not accessible"

# Check Elasticsearch
echo -e "\n4. Elasticsearch Status:"
kubectl get pods -n logging -l app.kubernetes.io/name=elasticsearch
curl -s http://localhost:9200/_cluster/health?pretty -u elastic:changeme || echo "Elasticsearch not accessible"

# Check metrics collection
echo -e "\n5. Metrics Collection:"
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length' || echo "0"

# Check for recent errors
echo -e "\n6. Recent Errors:"
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus --tail=20 | grep -i error || echo "No errors"
kubectl logs -n logging -l app.kubernetes.io/name=fluentd --tail=20 | grep -i error || echo "No errors"

# Check resource usage
echo -e "\n7. Resource Usage:"
kubectl top nodes
```

## Common Issues by Component

### 🔍 Prometheus Issues

#### Issue 1: High Memory Usage

**Symptoms:**

- Prometheus pod OOMKilled
- Slow query performance
- Incomplete metrics data

**Diagnosis:**

```bash
# Check memory usage
kubectl top pod -n monitoring -l app.kubernetes.io/name=prometheus

# Check TSDB stats
kubectl exec -n monitoring prometheus-0 -- \
  promtool tsdb analyze /prometheus

# Check cardinality
curl -s http://localhost:9090/api/v1/label/__name__/values | \
  jq -r '.data | length'
```

**Solution:**

```yaml
# Reduce cardinality
# 1. Drop unnecessary metrics
metricRelabelings:
  - sourceLabels: [__name__]
    regex: "go_.*|process_.*"
    action: drop

  # 2. Limit label values
  - sourceLabels: [path]
    regex: "/api/v1/users/[0-9]+"
    targetLabel: path
    replacement: "/api/v1/users/{id}"

# 3. Increase memory limits
resources:
  limits:
    memory: 8Gi
  requests:
    memory: 4Gi

# 4. Reduce retention
prometheusSpec:
  retention: 15d
  retentionSize: 50GB
```

#### Issue 2: Missing Metrics

**Symptoms:**

- No data in Grafana dashboards
- Targets showing as DOWN
- ServiceMonitor not discovered

**Diagnosis:**

```bash
# Check targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .job, health: .health}'

# Check ServiceMonitor discovery
kubectl get servicemonitor -A
kubectl describe prometheus -n monitoring | grep -A10 "Service Monitor Selector"

# Test metric endpoint
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8080
curl http://localhost:8080/metrics
```

**Solution:**

```yaml
# Fix ServiceMonitor labels
kubectl label servicemonitor mcp-mesh-registry -n mcp-mesh \
  release=prometheus

# Fix network policies
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: mcp-mesh
spec:
  podSelector: {}
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8080

# Fix service discovery
# Ensure Prometheus can discover all namespaces
prometheusSpec:
  serviceMonitorNamespaceSelector: {}
  serviceMonitorSelector: {}
```

### 📊 Grafana Issues

#### Issue 3: Dashboard Not Loading

**Symptoms:**

- "No Data" in panels
- Timeout errors
- Template variables not working

**Diagnosis:**

```bash
# Check data source
curl -s -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://localhost:3000/api/datasources

# Test query
curl -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=up{job="mcp-mesh-registry"}'

# Check Grafana logs
kubectl logs -n monitoring deployment/prometheus-grafana | grep -i error
```

**Solution:**

```json
// Fix data source configuration
{
  "name": "Prometheus",
  "type": "prometheus",
  "url": "http://prometheus-operated:9090",
  "access": "proxy",
  "jsonData": {
    "timeInterval": "30s",
    "queryTimeout": "60s",
    "httpMethod": "POST"
  }
}

// Fix template variables
{
  "templating": {
    "list": [{
      "name": "namespace",
      "type": "query",
      "datasource": "Prometheus",
      "query": "label_values(up, namespace)",
      "refresh": 2,
      "regex": "mcp-mesh.*",
      "sort": 1
    }]
  }
}
```

#### Issue 4: Slow Dashboard Performance

**Symptoms:**

- Long load times
- Browser hanging
- Query timeouts

**Solution:**

```promql
# Use recording rules instead of complex queries
# Bad - complex query in dashboard
histogram_quantile(0.95,
  sum by (agent, le) (
    rate(mcp_mesh_request_duration_seconds_bucket[$__interval])
  )
)

# Good - pre-computed recording rule
mcp_mesh:request_duration:p95

# Optimize time ranges
# Use $__interval instead of fixed intervals
rate(metric[$__interval])

# Limit query results
topk(10, metric)
```

### 🔎 Distributed Tracing Issues

#### Issue 5: Traces Not Appearing

**Symptoms:**

- No traces in Jaeger UI
- Broken trace continuity
- Missing spans

**Diagnosis:**

```bash
# Check OTEL collector
kubectl logs -n observability deployment/otel-collector | grep -E "receiver|exporter"

# Verify trace export
curl -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans": []}'

# Check Jaeger ingestion
kubectl port-forward -n observability svc/mcp-mesh-jaeger-collector 14268
curl http://localhost:14268/api/sampling?service=test
```

**Solution:**

```python
# Fix trace context propagation
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Set up propagator
set_global_textmap(TraceContextTextMapPropagator())

# Ensure context is propagated in async code
import contextvars
from opentelemetry import trace, context

trace_context = contextvars.ContextVar('trace_context')

async def parent_operation():
    with tracer.start_as_current_span("parent") as span:
        ctx = context.get_current()
        await child_operation(ctx)

async def child_operation(parent_ctx):
    # Restore parent context
    token = context.attach(parent_ctx)
    try:
        with tracer.start_as_current_span("child") as span:
            # Span will be properly linked
            pass
    finally:
        context.detach(token)
```

#### Issue 6: High Trace Volume

**Symptoms:**

- Storage filling up quickly
- Slow Jaeger queries
- Collector dropping traces

**Solution:**

```yaml
# Implement intelligent sampling
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    expected_new_traces_per_sec: 1000
    policies:
      # Always sample errors
      - name: error-sampler
        type: status_code
        status_code:
          status_codes: [ERROR]

      # Sample slow traces
      - name: latency-sampler
        type: latency
        latency:
          threshold_ms: 1000

      # Rate limit per service
      - name: service-rate-limit
        type: rate_limiting
        rate_limiting:
          spans_per_second: 100

      # Probabilistic fallback
      - name: probabilistic-sampler
        type: probabilistic
        probabilistic:
          sampling_percentage: 1
```

### 📝 Centralized Logging Issues

#### Issue 7: Logs Not Indexed

**Symptoms:**

- Logs not appearing in Kibana
- Fluentd errors
- Index pattern missing

**Diagnosis:**

```bash
# Check Fluentd status
kubectl logs -n logging daemonset/fluentd | tail -50

# Check Elasticsearch indices
curl -s http://localhost:9200/_cat/indices?v -u elastic:changeme

# Test log parsing
echo '{"level":"INFO","msg":"test","timestamp":"2024-01-15T10:00:00Z"}' | \
  kubectl exec -n logging fluentd-xxxxx -- \
  fluent-cat test.log
```

**Solution:**

```yaml
# Fix Fluentd parsing
<parse>
  @type multi_format
  # JSON logs
  <pattern>
    format json
    time_key timestamp
    time_format %Y-%m-%dT%H:%M:%S.%NZ
  </pattern>
  # Plain text fallback
  <pattern>
    format none
    message_key log
  </pattern>
</parse>

# Fix index template
PUT _index_template/mcp-mesh-logs
{
  "index_patterns": ["mcp-mesh-logs-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1
    },
    "mappings": {
      "properties": {
        "timestamp": {
          "type": "date"
        },
        "level": {
          "type": "keyword"
        }
      }
    }
  }
}
```

#### Issue 8: Log Storage Full

**Symptoms:**

- Elasticsearch disk usage high
- Write failures
- Slow queries

**Solution:**

```bash
# Implement lifecycle policy
PUT _ilm/policy/mcp-mesh-logs-policy
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_age": "1d",
            "max_size": "50GB"
          }
        }
      },
      "warm": {
        "min_age": "2d",
        "actions": {
          "shrink": {
            "number_of_shards": 1
          },
          "forcemerge": {
            "max_num_segments": 1
          }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}

# Force merge old indices
POST /mcp-mesh-logs-2024.01.*/_forcemerge?max_num_segments=1

# Delete old data
DELETE /mcp-mesh-logs-2023.*
```

### 🚨 Alerting Issues

#### Issue 9: Alerts Not Firing

**Symptoms:**

- Known problems but no alerts
- Alerts stuck in pending
- No notifications received

**Diagnosis:**

```bash
# Check alert rules
kubectl exec -n monitoring prometheus-0 -- \
  promtool check rules /etc/prometheus/rules/*.yaml

# Check pending alerts
curl -s http://localhost:9090/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.state=="pending")'

# Check AlertManager
kubectl logs -n monitoring alertmanager-0
curl -s http://localhost:9093/api/v1/alerts
```

**Solution:**

```yaml
# Fix alert expressions
# Ensure data exists
- alert: ServiceDown
  expr: up{job="mcp-mesh-registry"} == 0 or absent(up{job="mcp-mesh-registry"})
  for: 2m

# Fix AlertManager routing
route:
  receiver: 'default'
  group_by: ['alertname', 'cluster']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h

# Test configuration
amtool check-config alertmanager.yaml
amtool config routes test --config.file=alertmanager.yaml
```

#### Issue 10: Alert Storm

**Symptoms:**

- Hundreds of alerts firing
- Notification channels flooded
- Real issues lost in noise

**Solution:**

```yaml
# Implement alert grouping
route:
  group_by: ["alertname", "cluster", "service"]
  group_wait: 30s
  group_interval: 5m

# Add inhibition rules
inhibit_rules:
  - source_match:
      severity: "critical"
      alertname: "ClusterDown"
    target_match_re:
      severity: "warning|info"
    equal: ["cluster"]

  # Implement alert deduplication
  - alert: HighErrorRate
    expr: |
      (
        increase(errors_total[5m]) > 100
        AND
        rate(errors_total[5m]) > 0.05
      )
    # Don't alert on both conditions
```

## Performance Optimization

### Optimize Metric Collection

```yaml
# Reduce scrape frequency for non-critical targets
scrape_configs:
  - job_name: "mcp-mesh-agents"
    scrape_interval: 60s # Instead of default 30s

# Drop unused metrics at collection time
metric_relabel_configs:
  - source_labels: [__name__]
    regex: "go_gc_.*"
    action: drop
```

### Optimize Query Performance

```promql
# Use recording rules for expensive queries
groups:
  - name: expensive_queries
    interval: 30s
    rules:
    - record: instance:cpu_utilization:rate5m
      expr: |
        100 - (avg by (instance) (
          irate(node_cpu_seconds_total{mode="idle"}[5m])
        ) * 100)
```

### Optimize Storage

```bash
# Prometheus storage optimization
# Use compression
--storage.tsdb.retention.size=100GB
--storage.tsdb.wal-compression

# Elasticsearch optimization
PUT /_cluster/settings
{
  "transient": {
    "indices.memory.index_buffer_size": "20%",
    "indices.queries.cache.size": "15%"
  }
}
```

## Emergency Procedures

### Prometheus Recovery

```bash
#!/bin/bash
# prometheus-recovery.sh

# 1. Stop Prometheus
kubectl scale statefulset prometheus-prometheus -n monitoring --replicas=0

# 2. Backup corrupted data
kubectl exec -n monitoring prometheus-0 -- tar czf /tmp/backup.tgz /prometheus
kubectl cp monitoring/prometheus-0:/tmp/backup.tgz ./prometheus-backup.tgz

# 3. Clean WAL
kubectl exec -n monitoring prometheus-0 -- rm -rf /prometheus/wal/*

# 4. Restart
kubectl scale statefulset prometheus-prometheus -n monitoring --replicas=1

# 5. Verify
kubectl logs -n monitoring prometheus-0 -f
```

### Elasticsearch Recovery

```bash
# Fix unassigned shards
POST /_cluster/reroute
{
  "commands": [{
    "allocate_empty_primary": {
      "index": "mcp-mesh-logs-2024.01.15",
      "shard": 0,
      "node": "node-1",
      "accept_data_loss": true
    }
  }]
}

# Reset index
POST /mcp-mesh-logs-2024.01.15/_close
PUT /mcp-mesh-logs-2024.01.15/_settings
{
  "index.blocks.read_only_allow_delete": null
}
POST /mcp-mesh-logs-2024.01.15/_open
```

## Monitoring the Monitors

### Health Check Dashboard

```json
{
  "dashboard": {
    "title": "Observability Health",
    "panels": [
      {
        "title": "Component Status",
        "targets": [
          { "expr": "up{job=~'prometheus|grafana|jaeger-.*|elasticsearch'}" }
        ]
      },
      {
        "title": "Data Ingestion Rates",
        "targets": [
          { "expr": "rate(prometheus_tsdb_samples_appended_total[5m])" },
          { "expr": "rate(jaeger_collector_spans_received_total[5m])" },
          { "expr": "rate(elasticsearch_indices_indexing_index_total[5m])" }
        ]
      },
      {
        "title": "Error Rates",
        "targets": [
          { "expr": "rate(prometheus_rule_evaluation_failures_total[5m])" },
          { "expr": "rate(grafana_api_response_status_total{code!~'2..'}[5m])" }
        ]
      }
    ]
  }
}
```

### Synthetic Monitoring

```python
# synthetic_monitor.py
import requests
import time
from prometheus_client import Counter, Histogram, push_to_gateway

# Metrics
check_duration = Histogram('observability_check_duration_seconds',
                         'Duration of observability checks',
                         ['component'])
check_failures = Counter('observability_check_failures_total',
                        'Total observability check failures',
                        ['component'])

def check_prometheus():
    start = time.time()
    try:
        r = requests.get('http://prometheus:9090/api/v1/query',
                        params={'query': 'up'})
        r.raise_for_status()
        assert len(r.json()['data']['result']) > 0
    except Exception as e:
        check_failures.labels(component='prometheus').inc()
        raise
    finally:
        check_duration.labels(component='prometheus').observe(time.time() - start)

def check_grafana():
    start = time.time()
    try:
        r = requests.get('http://grafana:3000/api/health')
        r.raise_for_status()
        assert r.json()['database'] == 'ok'
    except Exception as e:
        check_failures.labels(component='grafana').inc()
        raise
    finally:
        check_duration.labels(component='grafana').observe(time.time() - start)

# Run checks
if __name__ == '__main__':
    while True:
        check_prometheus()
        check_grafana()

        # Push metrics
        push_to_gateway('pushgateway:9091', job='synthetic_monitor')

        time.sleep(60)
```

## Prevention Best Practices

1. **Capacity Planning**

   ```bash
   # Monitor growth rate
   prometheus_tsdb_symbol_table_size_bytes /
   prometheus_tsdb_storage_blocks_bytes
   ```

2. **Regular Maintenance**

   ```bash
   # Weekly: Check cardinality
   # Monthly: Review retention policies
   # Quarterly: Capacity review
   ```

3. **Testing Changes**

   ```bash
   # Test recording rules
   promtool test rules tests.yml

   # Test alerts
   promtool check rules alerts.yml
   ```

4. **Documentation**
   - Keep runbooks updated
   - Document custom metrics
   - Maintain architecture diagrams

## Getting Help

If you're still experiencing issues:

1. **Check Logs**

   ```bash
   # Collect all observability logs
   for component in prometheus grafana jaeger elasticsearch fluentd; do
     echo "=== $component logs ==="
     kubectl logs -n monitoring -l app.kubernetes.io/name=$component --tail=100
   done > observability-logs.txt
   ```

2. **Community Resources**

   - Prometheus: https://prometheus.io/community/
   - Grafana: https://community.grafana.com/
   - Jaeger: https://www.jaegertracing.io/get-in-touch/
   - Elastic: https://discuss.elastic.co/

3. **File an Issue**
   - Include diagnostic output
   - Provide configuration files
   - Describe expected vs actual behavior

## Summary

This guide covered troubleshooting for all observability components:

Key takeaways:

- 🔍 Systematic diagnosis approach
- 🔧 Component-specific solutions
- 📊 Performance optimization techniques
- 🚨 Emergency recovery procedures

---

💡 **Remember**: Good observability includes monitoring the monitoring stack itself

📚 **Reference**: Component-specific troubleshooting guides in official documentation

🆘 **Emergency**: If all monitoring is down, check node resources and kubelet logs first
