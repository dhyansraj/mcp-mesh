# MCP Mesh Development Guidelines

## 🚨 CRITICAL BEHAVIORAL RULES - READ FIRST

**ANALYSIS-ONLY MODE**: When asked to "analyze", "investigate", "check", or "look at" code - provide analysis ONLY. Do NOT modify files without explicit permission.

**PROTECTED DIRECTORIES**: NEVER modify without explicit permission:

- `/src/core/` - Go core engine (registry, database, orchestration)
- `/src/runtime/` - Python agent runtime and decorators
- `/examples/` - Reference implementations and demos
- `/tools/` - Build scripts and utilities
- `/config/` - Configuration files
- `/docker/` - Container definitions
- `/k8s/` - Kubernetes manifests

**TWO-STEP PROCESS**:

1. Provide analysis/findings first
2. Ask "What specific changes would you like me to implement?"
3. Wait for explicit approval before modifying files

## 🏗️ MCP Mesh Architecture

**Core Innovation**: Pull-based dynamic dependency injection where agents register capabilities and get dependency URLs from registry, then use HTTP proxy wrappers for remote MCP tool calls.

### Key Components:

- **Registry Service** (Go): Central capability discovery and agent coordination
- **Agent Runtime** (Python): Independent MCP-compatible agents with FastMCP/FastAPI servers
- **Python Decorators**: `@mesh.agent` (config) + `@mesh.tool` (functionality)
- **Capability Injection**: Dynamic function parameter monkey-patching based on dependency availability
- **Service Discovery**: Automatic registry wire-up with graceful standalone operation
- **Resilient Connection**: Agents work without registry, auto-connect when available, continue if registry fails

### Architecture Principles:

- **Microservices**: Each agent = independent K8s pod with isolated scaling
- **Dynamic Wiring**: Registry-controlled "who can call whom" decisions
- **MCP Compatible**: Full MCP protocol support with extended capabilities
- **Zero Dependencies**: Agents start minimal, acquire capabilities on-demand
- **Self-Organizing**: Agents make intelligent routing decisions autonomously

## 🛠️ Development Standards

**Core Engine**: Go (`/src/core/`) - Registry, orchestration, database layer
**Agent Runtime**: Python (`/src/runtime/`) - Agent execution and MCP integration
**Build System**: Makefile with targets for build, test, deploy, client generation
**CLI Tools**: `meshctl` for mesh network operations, utilities in `/tools/`
**Examples**: All reference implementations in `/examples/`

**Databases**: SQLite (local/Docker), PostgreSQL (K8s)
**API**: OpenAPI spec available for Go/Python client generation
**Testing**: Go: `make test`, Python: `make test-python`

**Code Style**:

- Database-agnostic queries (SQLite ↔ PostgreSQL)
- Clear error handling with comprehensive logging
- Interface-driven design for testability

## 🔄 Common Workflows

**Build & Test**:

- Go: `make build && make test`
- Python: `make test-python` or `pytest`
- All: `make test-all`

**Development**:

- Local dev: `make dev` (Docker Compose + SQLite)
- Docker examples: `cd examples/docker-examples && docker compose up/down`
- K8s deploy: `make deploy` (PostgreSQL + StatefulSet)
- Client generation: `make generate-clients` (Go + Python from OpenAPI spec)

**CLI Tools**:

- Mesh status: `./bin/meshctl list` (show all agents and dependencies)
- MCP calls: `curl -X POST http://localhost:8081/mcp -H "Content-Type: application/json" -d '{"method": "tools/call", "params": {"name": "function_name", "arguments": {}}}'`
- Build tools: Available in `/tools/` directory
- Examples: Reference all patterns in `/examples/`

## ⚠️ Critical Notes

- All SQL must work with both SQLite AND PostgreSQL
- Registry is the single source of truth for capabilities
- Agent independence is paramount - no tight coupling
- Hot-swappable capabilities are a core feature, not optional
- **Agent Lifecycle**: `@mesh.agent` (config) + `@mesh.tool` (functions) → MeshToolProcessor → FastMCP server → registry /agents/register
- **Environment Override**: `@mesh.agent` parameters can be overridden by env vars (e.g., http_port=9090 → MCP_MESH_HTTP_PORT=8080)
- **Dependency Injection**: Registry returns URLs/function names → HTTP proxy wrappers intercept calls → remote MCP tool calls
- **Resilient**: Agents work standalone, get wired when registry available, continue if registry fails (registry = discovery only, not in data path)
- **Heartbeat**: 30s intervals update dependency cache with new/offline agents (60s timeout → degraded → expired)
- **Health Status**: Only healthy agents returned in dependency resolution
- **Environment Isolation**: Docker Compose and Minikube use separate Docker daemons - no cross-contamination
- **K8s Issue**: MCP Mesh atexit registration fails in K8s ("can't register atexit after shutdown") → unresponsive routes despite "ready" status
- **Environment Difference**: Pure FastMCP works in both Docker Compose and K8s - issue is MCP Mesh's atexit timing/multiple registrations
- **Dev Issue**: Ctrl+C doesn't stop agents cleanly (multiple presses, long waits) - atexit handlers from debugging graceful shutdown problems
- **Container Target**: Containers can force-kill processes even if Python refuses graceful shutdown - atexit may be unnecessary
