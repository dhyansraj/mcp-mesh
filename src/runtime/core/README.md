# MCP Mesh Core

Rust core runtime for MCP Mesh agents. This library handles:

- Agent startup and registration
- Heartbeat loop (fast HEAD + conditional POST)
- Topology management and change detection
- Event streaming to language SDKs

## Building

```bash
# Install maturin
pip install maturin

# Build and install in development mode
maturin develop

# Build release wheel
maturin build --release
```

## Usage from Python

```python
from mcp_mesh_core import AgentSpec, start_agent

# Create agent specification
spec = AgentSpec(
    name="my-agent",
    version="1.0.0",
    registry_url="http://localhost:8100",
    http_port=9000,
    capabilities=[...],
    dependencies=[...],
)

# Start agent (returns handle)
handle = start_agent(spec)

# Listen for topology events
async def event_loop():
    while True:
        event = await handle.next_event()
        print(f"Event: {event.event_type}")
```

## Architecture

```
Python SDK                     Rust Core
───────────────────────────────────────────
Decorators          →
Metadata collection →          AgentSpec
                               ↓
                              start_agent()
                               ↓
                              AgentRuntime
                               ├─ HeartbeatLoop
                               ├─ RegistryClient
                               └─ TopologyManager
                               ↓
Event listener      ←         EventStream
DI updates          ←         MeshEvent
```
