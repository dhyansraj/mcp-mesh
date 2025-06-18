# Observability and Monitoring

> Gain deep insights into your MCP Mesh deployment with comprehensive observability

## Overview

Observability is crucial for operating MCP Mesh at scale. This section covers implementing comprehensive monitoring, metrics collection, distributed tracing, centralized logging, and alerting. You'll learn how to gain visibility into agent behavior, track system performance, debug distributed interactions, and maintain service level objectives.

With proper observability, you can proactively identify issues, optimize performance, and ensure reliability of your MCP Mesh deployment.

## What You'll Learn

By the end of this section, you will:

- ✅ Set up Prometheus for metrics collection and storage
- ✅ Create Grafana dashboards for visualization
- ✅ Implement distributed tracing with OpenTelemetry
- ✅ Configure centralized logging with the ELK stack
- ✅ Define SLIs/SLOs and configure alerting rules
- ✅ Debug complex multi-agent interactions

## Why Observability for MCP Mesh?

MCP Mesh's distributed nature makes observability essential:

1. **Distributed Complexity**: Track requests across multiple agents
2. **Performance Optimization**: Identify bottlenecks and optimize
3. **Debugging**: Understand failures in complex interactions
4. **SLA Compliance**: Monitor and maintain service levels
5. **Capacity Planning**: Make data-driven scaling decisions
6. **Security**: Detect anomalous behavior and threats

## MCP Mesh Observability Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Mesh Observability Stack                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     Visualization Layer                   │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Grafana    │  │   Kibana     │  │   Jaeger     │   │   │
│  │  │ (Dashboards) │  │   (Logs)     │  │  (Traces)    │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      Storage Layer                        │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │ Prometheus  │  │ Elasticsearch│  │   Tempo      │   │   │
│  │  │  (Metrics)  │  │   (Logs)     │  │  (Traces)    │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Collection Layer                       │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │ Prometheus  │  │   Fluentd    │  │    OTEL      │   │   │
│  │  │  Exporters  │  │  (Logstash)  │  │  Collector   │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    MCP Mesh Components                    │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Registry  │  │    Agents    │  │   Sidecars   │   │   │
│  │  │  (Metrics)  │  │  (All Data)  │  │ (Collectors) │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Section Contents

1. **[Prometheus Integration](./07-observability/01-prometheus-integration.md)** - Metrics collection and storage
2. **[Grafana Dashboards](./07-observability/02-grafana-dashboards.md)** - Visualization and monitoring
3. **[Distributed Tracing](./07-observability/03-distributed-tracing.md)** - OpenTelemetry and Jaeger
4. **[Centralized Logging](./07-observability/04-centralized-logging.md)** - ELK stack integration
5. **[Alerting and SLOs](./07-observability/05-alerting-slos.md)** - Proactive monitoring

## Quick Start Example

Deploy basic observability stack:

```bash
# Deploy Prometheus and Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts

# Install Prometheus with ServiceMonitor support
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false

# Deploy MCP Mesh with monitoring enabled
helm install mcp-mesh ./mcp-mesh-platform \
  --namespace mcp-mesh \
  --set global.monitoring.enabled=true \
  --set serviceMonitor.enabled=true

# Access Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Default credentials: admin/prom-operator
```

## Key Observability Concepts

### 1. The Three Pillars

**Metrics**: Numerical measurements over time

```yaml
# Example metrics from MCP Mesh
mcp_mesh_agent_requests_total{agent="weather", status="success"} 1234
mcp_mesh_registry_connections_active 42
mcp_mesh_agent_response_time_seconds{quantile="0.99"} 0.123
```

**Logs**: Discrete events with context

```json
{
  "timestamp": "2024-01-15T10:30:45Z",
  "level": "INFO",
  "agent": "weather-service",
  "trace_id": "abc123",
  "message": "Processing weather request",
  "location": "New York",
  "duration_ms": 45
}
```

**Traces**: Request flow across services

```
[Registry] ──> [Weather Agent] ──> [External API]
     │              │                    │
     ├── 5ms        ├── 20ms            └── 100ms
     │              │
     └── Total: 125ms
```

### 2. Observability Levels

- **Infrastructure**: Node metrics, resource usage
- **Platform**: Kubernetes metrics, pod health
- **Application**: MCP Mesh specific metrics
- **Business**: Agent-specific KPIs

### 3. Data Flow

```
Agent → Metrics Exporter → Prometheus → Grafana
      → Structured Logs → Fluentd → Elasticsearch → Kibana
      → Trace Spans → OTEL Collector → Jaeger
```

## Best Practices

- 📊 **Start Simple**: Begin with basic metrics, add complexity gradually
- 🏷️ **Label Consistently**: Use standard labels across all telemetry
- 📈 **Define SLIs Early**: Establish what matters before issues arise
- 🔍 **Correlate Data**: Link metrics, logs, and traces with common IDs
- ⚡ **Optimize Collection**: Balance visibility with performance impact

## Common Challenges

1. **Data Volume**: MCP Mesh can generate significant telemetry data
2. **Cardinality**: Too many label combinations can overwhelm storage
3. **Correlation**: Linking events across distributed agents
4. **Performance**: Observability overhead on agents
5. **Cost**: Storage and processing of observability data

## Ready to Implement Observability?

Start with [Prometheus Integration](./07-observability/01-prometheus-integration.md) →

## 🔧 Troubleshooting

### High Memory Usage in Prometheus

```bash
# Check cardinality
curl -s http://localhost:9090/api/v1/label/__name__/values | jq '. | length'

# Identify high-cardinality metrics
curl -s http://localhost:9090/api/v1/query?query=prometheus_tsdb_symbol_table_size_bytes | jq
```

### Missing Metrics

```bash
# Verify ServiceMonitor is discovered
kubectl get servicemonitor -n mcp-mesh
kubectl describe prometheus -n monitoring

# Check scrape targets
kubectl port-forward -n monitoring prometheus-0 9090
# Visit http://localhost:9090/targets
```

For detailed solutions, see our [Observability Troubleshooting Guide](./07-observability/troubleshooting.md).

## ⚠️ Known Limitations

- **Prometheus Storage**: Single-node storage limits scalability
- **Trace Sampling**: 100% tracing not feasible at scale
- **Log Retention**: Costs increase rapidly with retention period
- **Dashboard Performance**: Complex queries can be slow

## 📝 TODO

- [ ] Add Thanos for long-term metrics storage
- [ ] Document Cortex/Mimir integration
- [ ] Create runbooks for common alerts
- [ ] Add eBPF-based observability
- [ ] Document multi-cluster federation

---

💡 **Tip**: Use exemplars to jump from metrics to traces: Enable with `--enable-feature=exemplar-storage` in Prometheus

📚 **Reference**: [Prometheus Best Practices](https://prometheus.io/docs/practices/)

🎯 **Next Step**: Ready to collect metrics? Start with [Prometheus Integration](./07-observability/01-prometheus-integration.md)
