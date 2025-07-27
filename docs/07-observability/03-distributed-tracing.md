# Distributed Tracing

> Real-time trace correlation and analysis for MCP Mesh using Redis Streams

## Overview

MCP Mesh implements a high-performance distributed tracing system built on Redis Streams that provides end-to-end visibility into request flows across multiple agents. Unlike traditional OpenTelemetry setups, this system is specifically designed for MCP's JSON-RPC protocol with automatic context propagation and real-time correlation.

## Architecture Components

### 1. Python Agent Tracing (Publishers)

Python agents automatically publish trace events to Redis Streams when decorated with `@mesh.tool()`:

```python
@app.tool()
@mesh.tool(depends_on=["data-processor"])
async def generate_report(title: str) -> str:
    # Automatic trace context creation and propagation
    # publishes span_start -> calls dependency -> publishes span_end
    processor = await mesh.get_agent("data-processor")
    return await processor.process_data({"title": title})
```

**Event Types Published:**
- `span_start`: Operation begins
- `span_end`: Operation completes successfully  
- `error`: Operation fails with error details

### 2. Redis Streams (Transport Layer)

**Stream Name**: `mcp-mesh:traces`
**Consumer Group**: `mcp-mesh-registry-processors`

Events are published asynchronously without blocking agent operations:

```bash
# View recent trace events
redis-cli XREVRANGE mcp-mesh:traces + - COUNT 10

# Monitor stream length
redis-cli XLEN mcp-mesh:traces
```

### 3. Go Registry (Consumer & Correlator)

The registry consumes events and correlates them into complete traces:

- **Consumer**: Reads from Redis Streams with automatic failover
- **Correlator**: Builds complete traces from individual span events
- **Exporters**: Output traces in multiple formats (console, JSON, stats)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | `false` | Enable tracing system |
| `TRACE_EXPORTER_TYPE` | `console` | Export format |
| `TRACE_PRETTY_OUTPUT` | `true` | Pretty console output |
| `TRACE_ENABLE_STATS` | `true` | Collect statistics |
| `TRACE_JSON_OUTPUT_DIR` | `/tmp` | JSON export directory |
| `TRACE_BATCH_SIZE` | `100` | Consumer batch size |
| `TRACE_TIMEOUT` | `5m` | Trace completion timeout |

### Enable Tracing

```bash
# Enable in registry
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
export TRACE_EXPORTER_TYPE=console
export TRACE_PRETTY_OUTPUT=true

meshctl start --registry-only
```

Python agents automatically detect when tracing is enabled and begin publishing events.

## Trace Data Model

### TraceEvent Structure

```json
{
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "span_id": "x1y2z3w4-a5b6-c789-def0-123456789abc", 
  "parent_span": "parent-span-id-if-exists",
  "agent_name": "weather-service",
  "agent_id": "weather-123",
  "ip_address": "192.168.1.100",
  "event_type": "span_start|span_end|error",
  "operation": "tool:get_weather",
  "timestamp": 1640995200.123,
  "duration_ms": 150,
  "success": true,
  "error_message": null,
  "capability": "get_weather",
  "target_agent": "data-processor",
  "runtime": "python-3.11"
}
```

### CompletedTrace Structure

```json
{
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "spans": [
    {
      "span_id": "x1y2z3w4-a5b6-c789-def0-123456789abc",
      "agent_name": "weather-service", 
      "operation": "tool:get_weather",
      "start_time": "2024-01-01T10:00:00Z",
      "end_time": "2024-01-01T10:00:00.150Z",
      "duration_ms": 150,
      "success": true
    }
  ],
  "start_time": "2024-01-01T10:00:00Z",
  "end_time": "2024-01-01T10:00:00.300Z", 
  "duration": "300ms",
  "success": true,
  "span_count": 3,
  "agent_count": 2,
  "agents": ["weather-service", "data-processor"]
}
```

## Trace Correlation Logic

### 1. Event Collection

Events are correlated by `trace_id` and individual spans by `span_id`:

```
span_start[trace_id=ABC, span_id=123] + span_end[trace_id=ABC, span_id=123] = Complete Span
```

### 2. Completion Detection

Traces are considered complete when:
- All spans have both start and end events
- No new events for 5 seconds
- Contains at least one span

### 3. Export Triggers

Traces are exported when:
- **Immediately**: When completion is detected during event processing
- **Cleanup**: Every minute, completed traces are found and exported
- **Expiry**: After 5 minutes of inactivity (incomplete traces)

## Export Formats

### Console Exporter

Real-time trace visualization in terminal:

```bash
export TRACE_EXPORTER_TYPE=console
export TRACE_PRETTY_OUTPUT=true
```

**Output Example:**
```
🔗 TRACE a1b2c3d4 (285ms) - SUCCESS (3 spans across 2 agents)
  📍 Agent: weather-service
    ✅ tool:get_weather [get_weather] (150ms)
  📍 Agent: data-processor  
    ✅ tool:process_data [process_data] (100ms)
    ✅ tool:validate_result [validate_result] (35ms)
```

### JSON Exporter

Structured export for external systems:

```bash
export TRACE_EXPORTER_TYPE=json
export TRACE_JSON_OUTPUT_DIR=/var/log/traces
```

**Output Files:**
- `/var/log/traces/trace-{trace_id}.json`
- One file per completed trace

### Statistics Exporter

Aggregate metrics collection:

```bash
export TRACE_EXPORTER_TYPE=multi  # Enables all exporters
export TRACE_ENABLE_STATS=true
```

## Query API

### Trace Status

```bash
GET /trace/status
```

Returns tracing configuration and runtime statistics:

```json
{
  "enabled": true,
  "consumer": {
    "stream_name": "mcp-mesh:traces",
    "consumer_group": "mcp-mesh-registry-processors",
    "status": "running"
  },
  "correlator": {
    "active_traces": 5,
    "total_spans": 12,
    "oldest_trace_age": "45s"
  },
  "exporter": {
    "type": "console",
    "exported_traces": 147
  }
}
```

### List Recent Traces

```bash
GET /trace/list?limit=20&offset=0
```

Returns paginated list of completed traces, newest first.

### Get Specific Trace

```bash
GET /trace/{trace_id}
```

Retrieve complete trace details by ID.

### Search Traces

```bash
GET /trace/search?agent_name=weather&success=true&min_duration_ms=100
```

**Search Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `parent_span_id` | string | Filter by parent span |
| `agent_name` | string | Filter by agent name |
| `operation` | string | Filter by operation (partial match) |
| `success` | boolean | Filter by success status |
| `start_time` | RFC3339 | Filter by start time (after) |
| `end_time` | RFC3339 | Filter by end time (before) |
| `min_duration_ms` | integer | Minimum duration filter |
| `max_duration_ms` | integer | Maximum duration filter |
| `limit` | integer | Result limit (max 100) |

### Trace Statistics

```bash
GET /trace/stats
```

Returns aggregate statistics:

```json
{
  "total_traces": 1250,
  "success_traces": 1189,
  "failed_traces": 61,
  "success_rate": 95.12,
  "avg_duration_ms": 234.5,
  "avg_spans_per_trace": 2.8,
  "agents_involved": ["weather", "data-processor", "report-gen"],
  "top_operations": [
    {"operation": "tool:get_weather", "count": 456},
    {"operation": "tool:process_data", "count": 389}
  ]
}
```

## Performance Analysis Examples

### Find Slow Operations

```bash
# Operations taking longer than 1 second
curl "http://localhost:8000/trace/search?min_duration_ms=1000&limit=10" | jq '.traces[] | {trace_id, duration, agents}'
```

### Debug Failed Operations

```bash
# Get recent failures with details
curl "http://localhost:8000/trace/search?success=false&limit=5" | jq '.traces[] | {trace_id, agents, spans: [.spans[] | select(.success == false)]}'
```

### Agent Performance Analysis

```bash
# Analyze specific agent performance
curl "http://localhost:8000/trace/search?agent_name=weather-service&limit=50" | jq '[.traces[].duration] | add / length'
```

### Time-based Analysis

```bash
# Get traces from last hour
HOUR_AGO=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
curl "http://localhost:8000/trace/search?start_time=$HOUR_AGO&limit=100" | jq '.traces | length'
```

## Advanced Features

### Context Propagation

Trace context automatically flows between agents:

```python
# Parent agent
@mesh.tool(depends_on=["child-agent"])  
async def parent_operation():
    # trace_id and span_id automatically propagated
    child = await mesh.get_agent("child-agent")
    return await child.child_operation()

# Child agent  
@mesh.tool()
async def child_operation():
    # Inherits trace context from parent
    # New span created with parent span ID
    pass
```

### Error Correlation

Failed operations are automatically correlated:

```python
@mesh.tool()
async def failing_operation():
    try:
        # operation logic
        pass
    except Exception as e:
        # Error event automatically published with trace context
        raise  # Re-raise to maintain error handling
```

### Multi-Agent Traces

Complex workflows spanning multiple agents are automatically traced:

```
User Request → Agent A → Agent B → Agent C
      ↓            ↓         ↓         ↓
   trace_id    same_id   same_id   same_id
   span_1      span_2    span_3    span_4
              parent=1  parent=2  parent=3
```

## Storage and Retention

### In-Memory Storage

- **Active Traces**: Stored until completion or 5-minute timeout
- **Completed Traces**: Last 1000 traces kept for querying
- **Automatic Cleanup**: Oldest 20% removed when limit exceeded

### Redis Stream Retention

```bash
# Configure Redis stream retention
redis-cli CONFIG SET stream-node-max-bytes 4096
redis-cli CONFIG SET stream-node-max-entries 100

# Manual stream cleanup (if needed)
redis-cli XTRIM mcp-mesh:traces MAXLEN ~ 10000
```

## Troubleshooting

### No Traces Appearing

**Check tracing status:**
```bash
curl http://localhost:8000/trace/status | jq .enabled
```

**Verify Redis stream:**
```bash
redis-cli XLEN mcp-mesh:traces
redis-cli XINFO GROUPS mcp-mesh:traces
```

**Check agent connectivity:**
```bash
# Python agents should log tracing status on startup
# Look for: "Tracing enabled, publishing to redis://..."
```

### Incomplete Traces

**Check for orphaned events:**
```bash
redis-cli XREVRANGE mcp-mesh:traces + - COUNT 20
```

**Monitor correlator status:**
```bash
curl http://localhost:8000/trace/status | jq .correlator
```

### Performance Issues

**Monitor consumer lag:**
```bash
redis-cli XINFO GROUPS mcp-mesh:traces
# Look for "lag" field in consumer info
```

**Check memory usage:**
```bash
curl http://localhost:8000/trace/stats | jq .
# Monitor active_traces count
```

## Integration Examples

### Prometheus Metrics

```bash
#!/bin/bash
# Export trace metrics to Prometheus

STATS=$(curl -s http://localhost:8000/trace/stats)
SUCCESS_RATE=$(echo $STATS | jq .success_rate)
AVG_DURATION=$(echo $STATS | jq .avg_duration_ms)

echo "mcp_mesh_trace_success_rate $SUCCESS_RATE" | curl -X POST --data-binary @- http://pushgateway:9091/metrics/job/mcp-mesh
echo "mcp_mesh_trace_avg_duration_ms $AVG_DURATION" | curl -X POST --data-binary @- http://pushgateway:9091/metrics/job/mcp-mesh
```

### External APM Integration

```bash
#!/bin/bash
# Send traces to external APM (e.g., Datadog, New Relic)

curl -s "http://localhost:8000/trace/list?limit=100" | \
  jq -c '.traces[]' | \
  while read trace; do
    curl -X POST "https://api.datadoghq.com/api/v1/traces" \
      -H "DD-API-KEY: $DD_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$trace"
  done
```

### Log Correlation

```bash
#!/bin/bash
# Correlate traces with application logs

# Extract trace IDs and search logs
curl -s "http://localhost:8000/trace/search?success=false&limit=10" | \
  jq -r '.traces[].trace_id' | \
  while read trace_id; do
    echo "=== Logs for trace $trace_id ==="
    grep "$trace_id" /var/log/mcp-mesh/*.log
  done
```

## Best Practices

### 1. Monitoring

- Set up alerts on trace export failures
- Monitor trace completion rates  
- Track trace duration trends
- Alert on error rate spikes

### 2. Performance

- Use `multi` exporter for comprehensive observability
- Configure appropriate Redis retention policies
- Monitor correlator memory usage
- Tune batch sizes for high throughput

### 3. Debugging

- Use search API for targeted investigation
- Correlate traces with application logs
- Monitor Redis stream health
- Check agent trace context propagation

### 4. Production Deployment

- Configure JSON export for trace persistence
- Set up external metrics collection  
- Implement trace sampling for high-volume systems
- Monitor registry resource usage

## Performance Characteristics

- **Throughput**: 10,000+ spans/second sustained
- **Latency**: <1ms trace event publishing (async)
- **Memory**: ~1MB per 1000 completed traces  
- **Storage**: Configurable retention in Redis and memory
- **Correlation**: Real-time span correlation and export
- **Availability**: Registry failure doesn't impact agents

## Next Steps

The distributed tracing system provides comprehensive observability out of the box. Consider extending with:

1. **Custom Exporters**: Implement organization-specific backends
2. **Trace Sampling**: Add intelligent sampling for high-volume scenarios  
3. **SLA Monitoring**: Extract SLA metrics from trace data
4. **Automated Alerting**: Set up proactive monitoring based on trace patterns

---

💡 **Tip**: Use the trace search API with time windows to identify performance trends and system bottlenecks

📊 **Performance**: Monitor trace statistics regularly to ensure optimal system performance

🔗 **Integration**: Export traces to your existing observability stack using JSON exporter or custom exporters