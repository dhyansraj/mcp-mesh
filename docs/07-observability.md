# Observability and Monitoring

> Monitor and trace your MCP Mesh deployment with built-in distributed tracing

## Overview

MCP Mesh includes a built-in distributed tracing system that provides real-time visibility into request flows across your distributed agents. Unlike traditional OpenTelemetry setups, MCP Mesh uses Redis Streams for trace collection and correlation, offering a lightweight, high-performance observability solution.

## What You'll Learn

By the end of this section, you will:

- ✅ Enable distributed tracing in MCP Mesh
- ✅ Monitor trace events in real-time  
- ✅ Query and search completed traces
- ✅ Analyze multi-agent interactions
- ✅ Debug performance bottlenecks
- ✅ Export traces to external systems

## MCP Mesh Distributed Tracing Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Mesh Observability Stack                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                     Visualization Layer                   │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Console   │  │     JSON     │  │   REST API   │   │   │
│  │  │   Export    │  │   Export     │  │  (Queries)   │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      Processing Layer                     │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │    Trace    │  │    Span      │  │    Export    │   │   │
│  │  │ Correlator  │  │  Correlation │  │   Pipeline   │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Collection Layer                       │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Registry  │  │ Redis Streams│  │   Consumer   │   │   │
│  │  │  (Consumer) │  │ (mcp-mesh:   │  │    Group     │   │   │
│  │  │             │  │   traces)    │  │              │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    MCP Mesh Components                    │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Python    │  │      Go      │  │    Redis     │   │   │
│  │  │   Agents    │  │   Registry   │  │   Streams    │   │   │
│  │  │ (Publishers)│  │ (Consumer)   │  │  (Storage)   │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

Enable distributed tracing in your MCP Mesh deployment:

### 1. Enable Tracing in Registry

```bash
# Environment configuration
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
export TRACE_EXPORTER_TYPE=console    # or json, multi
export TRACE_PRETTY_OUTPUT=true
export TRACE_ENABLE_STATS=true

# Start registry with tracing
meshctl start --registry-only
```

### 2. Python Agents Auto-Enable Tracing

Python agents automatically participate in distributed tracing when the registry has it enabled. No additional configuration required!

### 3. Verify Tracing is Working

```bash
# Check tracing status
curl http://localhost:8000/trace/status

# Make a test call to generate traces
curl -X POST http://localhost:9093/mcp/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {"title": "Test Report"}
    }
  }'

# Check completed traces (after ~1 minute)
curl http://localhost:8000/trace/list | jq .
```

## Core Concepts

### 1. Trace Events

MCP Mesh generates three types of trace events:

- **span_start**: When an operation begins
- **span_end**: When an operation completes  
- **error**: When an operation fails

### 2. Trace Correlation

The registry correlates events into complete traces:

- **Same trace_id**: Groups spans into a single trace
- **Same span_id**: Links span_start and span_end events
- **Parent spans**: Creates trace hierarchy

### 3. Data Flow

```
Python Agent → Redis Streams → Registry Consumer → Correlator → Exporter
     ↓              ↓               ↓                ↓            ↓
@mesh.tool()  mcp-mesh:traces  Background     Trace Builder  Console/JSON
```

## Configuration Options

### Registry Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | `false` | Enable/disable tracing |
| `TRACE_EXPORTER_TYPE` | `console` | Export format: console, json, multi |
| `TRACE_PRETTY_OUTPUT` | `true` | Pretty-print console output |
| `TRACE_ENABLE_STATS` | `true` | Collect trace statistics |
| `TRACE_JSON_OUTPUT_DIR` | - | Directory for JSON export |
| `TRACE_BATCH_SIZE` | `100` | Redis consumer batch size |
| `TRACE_TIMEOUT` | `5m` | Trace completion timeout |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |

### Exporter Options

#### Console Exporter
```bash
export TRACE_EXPORTER_TYPE=console
export TRACE_PRETTY_OUTPUT=true
```

Real-time trace output:
```
🔗 TRACE a1b2c3d4 (15ms) - SUCCESS (3 spans across 2 agents)
  📍 Agent: dependent-service
    ✅ tool:generate_report [generate_report] (15ms)
  📍 Agent: fastmcp-service  
    ✅ tool:get_current_time [get_current_time] (2ms)
    ✅ tool:validate_data [validate_data] (8ms)
```

#### JSON Exporter
```bash
export TRACE_EXPORTER_TYPE=json
export TRACE_JSON_OUTPUT_DIR=/var/log/traces
```

#### Multi Exporter
```bash
export TRACE_EXPORTER_TYPE=multi
export TRACE_JSON_OUTPUT_DIR=/var/log/traces
```

## API Reference

### Trace Status
```bash
GET /trace/status
```

Returns tracing configuration and runtime status.

### List Traces
```bash
GET /trace/list?limit=20&offset=0
```

List completed traces with pagination.

### Get Specific Trace
```bash
GET /trace/{trace_id}
```

Retrieve a specific trace by ID.

### Search Traces
```bash
GET /trace/search?agent_name=weather&success=true&start_time=2024-01-01T00:00:00Z
```

Search traces with filtering:

| Parameter | Type | Description |
|-----------|------|-------------|
| `parent_span_id` | string | Filter by parent span |
| `agent_name` | string | Filter by agent name |
| `operation` | string | Filter by operation name |
| `success` | boolean | Filter by success status |
| `start_time` | RFC3339 | Filter by start time |
| `end_time` | RFC3339 | Filter by end time |
| `min_duration_ms` | integer | Minimum duration filter |
| `max_duration_ms` | integer | Maximum duration filter |
| `limit` | integer | Result limit (max 100) |

### Trace Statistics
```bash
GET /trace/stats
```

Returns aggregate trace statistics.

## Trace Analysis Examples

### Example 1: Find Slow Operations

```bash
# Find traces longer than 1 second
curl "http://localhost:8000/trace/search?min_duration_ms=1000" | jq .
```

### Example 2: Debug Failed Operations

```bash
# Find failed traces
curl "http://localhost:8000/trace/search?success=false" | jq .
```

### Example 3: Analyze Agent Performance

```bash
# Get traces for specific agent
curl "http://localhost:8000/trace/search?agent_name=weather-service" | jq .
```

### Example 4: Monitor Recent Activity

```bash
# Get traces from last hour
HOUR_AGO=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
curl "http://localhost:8000/trace/search?start_time=$HOUR_AGO" | jq .
```

## Best Practices

### 1. Monitoring

- Monitor trace export rate and success
- Set up alerts for high error rates
- Watch for trace correlation issues

### 2. Storage Management

- Traces are stored in memory (last 1000)
- Older traces are automatically cleaned up
- Use JSON export for long-term storage

### 3. Performance

- Tracing is designed to be low-overhead
- Async publishing doesn't block operations
- Redis Streams provide high throughput

### 4. Debugging

- Check trace status endpoint for issues
- Monitor Redis stream length
- Verify consumer group processing

## Integration Examples

### External Monitoring Integration

```bash
#!/bin/bash
# Send trace metrics to external monitoring

# Get trace stats
STATS=$(curl -s http://localhost:8000/trace/stats)
TOTAL_TRACES=$(echo $STATS | jq .total_traces)
SUCCESS_RATE=$(echo $STATS | jq '.success_traces / .total_traces * 100')

# Send to monitoring system
curl -X POST http://monitoring.internal/metrics \
  -d "mcp_mesh_traces_total $TOTAL_TRACES"
curl -X POST http://monitoring.internal/metrics \
  -d "mcp_mesh_traces_success_rate $SUCCESS_RATE"
```

### Log Integration

```bash
#!/bin/bash
# Export traces to centralized logging

# Get recent traces and send to logs
curl -s "http://localhost:8000/trace/list?limit=100" | \
  jq -c '.traces[]' | \
  while read trace; do
    echo "$trace" | logger -t mcp-mesh-trace
  done
```

## Troubleshooting

### Issue 1: No Traces Appearing

**Symptoms**: Empty trace list despite agent activity

**Checks**:
```bash
# 1. Verify tracing is enabled
curl http://localhost:8000/trace/status | jq .enabled

# 2. Check Redis stream
redis-cli XLEN mcp-mesh:traces

# 3. Check consumer status
curl http://localhost:8000/trace/status | jq .consumer
```

### Issue 2: Incomplete Traces

**Symptoms**: Traces missing spans or correlation issues

**Checks**:
```bash
# Check for orphaned spans
redis-cli XREVRANGE mcp-mesh:traces + - COUNT 10

# Look for mismatched trace_ids
curl http://localhost:8000/trace/status | jq .correlator
```

### Issue 3: High Memory Usage

**Symptoms**: Registry memory growing

**Checks**:
```bash
# Check active traces count
curl http://localhost:8000/trace/status | jq .correlator.active_traces

# Verify cleanup is working
# Should see periodic cleanup messages in logs
```

## Advanced Configuration

### Custom Exporters

You can implement custom exporters by extending the Go registry:

```go
// Custom exporter implementation
type CustomExporter struct {
    endpoint string
}

func (e *CustomExporter) ExportTrace(trace *CompletedTrace) error {
    // Send trace to custom backend
    return sendToCustomBackend(e.endpoint, trace)
}
```

### Redis Configuration

```bash
# High-performance Redis settings for tracing
redis-cli CONFIG SET stream-node-max-bytes 4096
redis-cli CONFIG SET stream-node-max-entries 100
```

## Performance Characteristics

- **Throughput**: 10,000+ spans/second
- **Latency**: <1ms trace event publishing
- **Memory**: ~1MB per 1000 completed traces
- **Storage**: Configurable retention (default: in-memory)

## Next Steps

The distributed tracing system provides a solid foundation for observability. Consider adding:

1. **External Export**: Send traces to Jaeger/Zipkin
2. **Alerting**: Set up alerts on trace metrics
3. **Dashboards**: Create visualizations for trace data
4. **Custom Metrics**: Extract business metrics from traces

---

💡 **Tip**: Use the search API with time ranges to analyze performance trends over time

📚 **Reference**: [MCP Mesh Tracing API Documentation](./07-observability/03-distributed-tracing.md)

🎯 **Next Step**: Explore the detailed [Distributed Tracing Guide](./07-observability/03-distributed-tracing.md)