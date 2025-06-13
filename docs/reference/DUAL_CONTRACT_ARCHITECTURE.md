# Dual-Contract Architecture for MCP Mesh

## Overview

MCP Mesh now implements a **dual-contract architecture** that separates concerns between registry and agent services with dedicated OpenAPI specifications for each.

## 🔄 Architecture

### Before: Single Contract Confusion

```
❌ Single OpenAPI spec for everything
❌ Agent endpoints incorrectly validated against registry contract
❌ Scope confusion between services
```

### After: Dual-Contract Clarity

```
✅ Registry API Contract: agent-registry communication
✅ Agent API Contract: agent HTTP wrapper endpoints
✅ Clear service boundaries and validation
```

## 📋 Two OpenAPI Specifications

### 1. Registry API (`api/mcp-mesh-registry.openapi.yaml`)

**Purpose**: Defines the contract for agent-registry communication

**Scope**:

- Agent registration: `POST /agents/register`
- Heartbeat management: `POST /heartbeat`
- Agent discovery: `GET /agents`
- Registry health: `GET /health`

**Implementations**:

- **Go server**: Generated handlers in `src/core/registry/generated/`
- **Python client**: Generated client in `src/runtime/python/src/mcp_mesh/registry_client_generated/`

### 2. Agent API (`api/mcp-mesh-agent.openapi.yaml`)

**Purpose**: Defines the contract for agent HTTP wrapper endpoints

**Scope**:

- Agent health checks: `GET /health`, `GET /ready`, `GET /livez`
- Mesh integration: `GET /mesh/info`, `GET /mesh/tools`
- MCP protocol: `POST /mcp`
- Monitoring: `GET /metrics`

**Implementations**:

- **Python server**: Generated handlers in `src/runtime/python/src/mcp_mesh/agent_server_generated/`

## 🔧 Code Generation

### Updated Generation Script

```bash
# Generate all contracts
./tools/codegen/generate.sh all

# Generate specific contracts
./tools/codegen/generate.sh registry     # Go server + Python client
./tools/codegen/generate.sh agent       # Python server
./tools/codegen/generate.sh registry-go # Only Go server
./tools/codegen/generate.sh agent-python # Only Python server
```

### Generated Code Structure

```
api/
├── mcp-mesh-registry.openapi.yaml      # 📋 Registry contract
└── mcp-mesh-agent.openapi.yaml         # 📋 Agent contract

src/core/registry/generated/             # 🤖 Go registry server
├── server.go                            # Generated from registry contract

src/runtime/python/src/mcp_mesh/
├── registry_client_generated/           # 🤖 Python registry client
│   └── mcp_mesh_registry_client/        # Generated from registry contract
└── agent_server_generated/              # 🤖 Python agent server
    └── mcp_mesh_agent_server/           # Generated from agent contract
```

## ✅ Dual-Contract Validation

### Updated Endpoint Detection

```bash
# Validates against BOTH contracts
make detect-endpoints

# Manual validation
python3 tools/detection/detect_endpoints.py \
  api/mcp-mesh-registry.openapi.yaml \
  api/mcp-mesh-agent.openapi.yaml \
  src
```

**Smart Contract Matching**:

- Registry paths (`src/core/registry/`) → validated against registry contract
- Agent paths (`src/runtime/`, `src/mcp_mesh/runtime/`) → validated against agent contract

### Schema Validation

```bash
# Validates BOTH specifications
make validate-schema
```

## 🎯 Resolved Issues

### ✅ **Endpoint Detection False Positives**

**Before**:

```
❌ Found endpoints not in OpenAPI specification:
  GET /ready
  GET /mesh/info
  GET /metrics
  POST /mcp
```

**After**:

```
✅ All endpoints are defined in appropriate OpenAPI specifications
  Registry endpoints: 5 found, all valid
  Agent endpoints: 6 found, all valid
```

### ✅ **Clear Service Boundaries**

- **Registry Service**: Handles agent registration, discovery, heartbeats
- **Agent Service**: Provides health checks, mesh info, MCP transport

### ✅ **Proper Contract Enforcement**

- Registry code must implement registry contract
- Agent code must implement agent contract
- No more scope confusion

## 🚀 Usage Examples

### Registry Contract Usage (Go + Python)

```go
// Go registry server (generated)
func (h *BusinessLogicHandlers) RegisterAgent(c *gin.Context) {
    // Implement agent registration logic
}
```

```python
# Python registry client (generated)
from mcp_mesh.registry_client_generated.mcp_mesh_registry_client import AgentsApi

client = AgentsApi(api_client)
response = client.register_agent(agent_registration)
```

### Agent Contract Usage (Python)

```python
# Python agent server (generated)
from mcp_mesh.agent_server_generated import AgentHealthResponse

@app.get("/health")
async def get_agent_health() -> AgentHealthResponse:
    return AgentHealthResponse(
        status="healthy",
        agent_id="hello-world",
        timestamp=datetime.now()
    )
```

## 🔄 Migration Impact

### What Changed

1. **Added agent OpenAPI specification**
2. **Updated code generation for dual contracts**
3. **Enhanced endpoint detection with contract matching**
4. **Updated Makefile targets for dual validation**

### What Stayed The Same

1. **Registry service implementation** (still uses generated Go handlers)
2. **Registry client integration** (Python agents still communicate with registry)
3. **Core workflow** (still contract-first development)

## 🎖️ Benefits

### For Developers

1. **Clear Boundaries**: Know which contract applies to which code
2. **Proper Validation**: Endpoints validated against correct specification
3. **Service Isolation**: Registry and agent concerns are separated
4. **Type Safety**: Both services get proper generated types

### For AI Development

1. **Context Clarity**: AI knows which contract to modify
2. **Scope Guidance**: Clear instructions for endpoint placement
3. **Validation Accuracy**: No more false positive endpoint violations
4. **Contract Evolution**: Both contracts can evolve independently

## 🔧 Next Steps

1. **Generate agent server code**: `make generate`
2. **Integrate with HTTP wrapper**: Update Python runtime to use generated agent handlers
3. **Update tests**: Validate against both contracts
4. **Documentation**: Update API docs for both contracts

---

**🤖 AI GUIDANCE**: This dual-contract architecture resolves the endpoint detection issues by providing clear service boundaries. Always identify whether you're working on registry (agent-registry communication) or agent (HTTP wrapper) functionality, then use the appropriate contract.
