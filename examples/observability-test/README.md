# Observability Test - Distributed Tracing Hierarchy

This example tests the distributed tracing implementation with a 4-agent setup
that demonstrates both chain and fan-out call patterns.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Call Flow Diagram                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  meshctl call orchestrator/orchestrate_workflow                          │
│  │                                                                       │
│  ├─► CALL A (chain): Full depth trace                                   │
│  │   orchestrator ──► processor ──► analyzer ──► storage                │
│  │                                                                       │
│  └─► CALL B (fan-out): Parallel traces                                  │
│      orchestrator ──┬──► processor (get_status)                         │
│                     └──► storage (get_metrics)                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Agents

| Agent        | Port | Capabilities                       | Role        |
| ------------ | ---- | ---------------------------------- | ----------- |
| orchestrator | 8081 | orchestrate_workflow, simple_chain | Entry point |
| processor    | 8082 | process_data, get_status           | Middle tier |
| analyzer     | 8083 | analyze_data, quick_analyze        | Middle tier |
| storage      | 8084 | store_result, get_metrics          | Leaf node   |

## Quick Start

```bash
# Start all services
cd examples/observability-test
docker compose up --build

# Wait for all agents to register (check registry)
meshctl list

# Trigger the test workflow
meshctl call orchestrator/orchestrate_workflow --workflow_id test123

# View traces in Redis
redis-cli -h localhost XREAD STREAMS mesh:trace 0
```

## Expected Trace Records

When `orchestrate_workflow` is called, the following trace records should be
published to Redis stream `mesh:trace`:

### Correct Hierarchy (Expected)

```
EXT (meshctl external span)
└── S001: orchestrate_workflow (orchestrator)
    │
    │   ═══ CALL A: Chain ═══
    ├── S002: proxy_call_wrapper (orchestrator→processor)
    │   └── S003: process_data (processor)
    │       └── S004: proxy_call_wrapper (processor→analyzer)
    │           └── S005: analyze_data (analyzer)
    │               └── S006: proxy_call_wrapper (analyzer→storage)
    │                   └── S007: store_result (storage)
    │
    │   ═══ CALL B: Fan-out ═══
    ├── S008: proxy_call_wrapper (orchestrator→processor)
    │   └── S009: get_status (processor)
    │
    └── S010: proxy_call_wrapper (orchestrator→storage)
        └── S011: get_metrics (storage)
```

### Expected Redis Records

| #   | function_name        | agent        | span_id | parent_span | Notes                |
| --- | -------------------- | ------------ | ------- | ----------- | -------------------- |
| 1   | orchestrate_workflow | orchestrator | S001    | EXT         | Entry point          |
| 2   | proxy_call_wrapper   | orchestrator | S002    | S001        | Call to processor    |
| 3   | process_data         | processor    | S003    | S002        | Processor tool       |
| 4   | proxy_call_wrapper   | processor    | S004    | S003        | Call to analyzer     |
| 5   | analyze_data         | analyzer     | S005    | S004        | Analyzer tool        |
| 6   | proxy_call_wrapper   | analyzer     | S006    | S005        | Call to storage      |
| 7   | store_result         | storage      | S007    | S006        | Storage tool (leaf)  |
| 8   | proxy_call_wrapper   | orchestrator | S008    | S001        | Fan-out to processor |
| 9   | get_status           | processor    | S009    | S008        | Status check (leaf)  |
| 10  | proxy_call_wrapper   | orchestrator | S010    | S001        | Fan-out to storage   |
| 11  | get_metrics          | storage      | S011    | S010        | Metrics check (leaf) |

### Bug Behavior (Current - Flat Hierarchy)

If the tracing bug exists, all calls will have the external span as parent:

```
EXT (meshctl external span)
├── S001: orchestrate_workflow (orchestrator)  ← Correct
├── S003: process_data (processor)             ← WRONG: parent should be S002
├── S005: analyze_data (analyzer)              ← WRONG: parent should be S004
├── S007: store_result (storage)               ← WRONG: parent should be S006
├── S009: get_status (processor)               ← WRONG: parent should be S008
└── S011: get_metrics (storage)                ← WRONG: parent should be S010
```

## Viewing Traces

### Redis CLI

```bash
# Read all traces
redis-cli XREAD STREAMS mesh:trace 0

# Read with formatting (requires jq)
redis-cli XREAD STREAMS mesh:trace 0 | jq

# Count traces
redis-cli XLEN mesh:trace

# Clear traces for fresh test
redis-cli DEL mesh:trace
```

### Python Script

```python
import redis
import json

r = redis.Redis(host='localhost', port=6379)
traces = r.xread({'mesh:trace': '0'})

for stream, messages in traces:
    print(f"\n{'='*60}")
    for msg_id, data in messages:
        print(f"\nTrace ID: {msg_id}")
        for key, value in data.items():
            key = key.decode() if isinstance(key, bytes) else key
            value = value.decode() if isinstance(value, bytes) else value
            print(f"  {key}: {value}")
```

## Development Testing

The mcp-mesh source code is mounted into the containers, allowing you to:

1. Make changes to `/src/runtime/python/_mcp_mesh/tracing/`
2. Restart only the affected container(s)
3. Re-run the test without rebuilding

```bash
# After making changes to tracing code
docker compose restart orchestrator processor analyzer storage

# Clear previous traces
redis-cli DEL mesh:trace

# Re-run test
meshctl call orchestrator/orchestrate_workflow --workflow_id test456
```

## Troubleshooting

### Agents not registering

```bash
# Check registry health
curl http://localhost:8000/health

# Check agent logs
docker compose logs orchestrator
docker compose logs processor
```

### No traces in Redis

1. Verify `MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true` is set
2. Check Redis connection: `redis-cli ping`
3. Check agent logs for tracing errors

### Dependency resolution failures

```bash
# List all registered services
meshctl list

# Check specific capability
meshctl list --capability process_data
```

## Files

```
observability-test/
├── README.md                 # This file
├── docker-compose.yml        # Service definitions
├── Dockerfile.dev            # Dev image with source mounting
└── agents/
    ├── orchestrator.py       # Entry point agent
    ├── processor.py          # Middle tier agent
    ├── analyzer.py           # Middle tier agent
    └── storage.py            # Leaf node agent
```
