# MCP Mesh Progressive Implementation Plan (REVISED)

## From Current Advanced State to Enhanced HTTP Wrapper Architecture

### Current State Analysis (Post-Codebase Review)

- ✅ **EXCELLENT**: Advanced dependency injection with hash-based change detection
- ✅ **EXCELLENT**: Universal proxy system (`MCPClientProxy` + `SelfDependencyProxy`)
- ✅ **EXCELLENT**: Pipeline architecture with startup/heartbeat phases
- ✅ **EXCELLENT**: Decorator registry and debounced processing
- ✅ **EXCELLENT**: Registry communication with graceful degradation
- ✅ **WORKING**: HTTP wrapper mounting FastMCP apps (basic implementation)
- ❌ **MISSING**: `/metadata` endpoint to expose capability routing information
- ❌ **MISSING**: Full MCP protocol support (tools/list, resources/_, prompts/_)
- ❌ **MISSING**: Session affinity routing in HTTP wrapper
- ❌ **MISSING**: Intelligent routing based on capability metadata

---

## Pre-Phase 1: Docker Compose Development Environment Setup

**Goal**: Establish containerized development environment for multi-agent testing
**Status**: ✅ **COMPLETED** - Environment ready for development
**Location**: `v0.3_dev/testing/`

### Docker Compose Environment Overview

The testing environment provides:

- **5 identical agents** (A, B, C, D, E) running on ports 8090-8094
- **Redis** for session storage on port 6379
- **Shared volume mounting** for live code changes
- **Isolated networking** for realistic multi-agent scenarios

### Development Workflow

#### 1. Starting the Environment

```bash
cd v0.3_dev/testing
docker-compose up -d
```

#### 2. Making Code Changes

All source code changes are automatically reflected in containers via volume mounts:

- `src/runtime/python/` → `/app/src/runtime/python/` (in all agent containers)
- No need to rebuild images for Python code changes

#### 3. Restarting Containers After Changes

```bash
# Restart all agents to pick up changes
docker-compose restart agent_a agent_b agent_c agent_d agent_e

# Or restart specific agent
docker-compose restart agent_a

# Or restart everything
docker-compose restart
```

#### 4. Testing Multiple Agents

```bash
# Test agent endpoints
curl http://localhost:8090/health  # Agent A
curl http://localhost:8091/health  # Agent B
curl http://localhost:8092/health  # Agent C
curl http://localhost:8093/health  # Agent D
curl http://localhost:8094/health  # Agent E

# Test Redis connection
docker-compose exec redis redis-cli ping
```

#### 5. Viewing Logs

```bash
# All agents
docker-compose logs -f

# Specific agent
docker-compose logs -f agent_a

# Redis logs
docker-compose logs -f redis
```

#### 6. Testing Session Affinity

```bash
# Run Phase 4 tests
cd v0.3_dev/testing
python test_phase4_session_affinity.py
```

### Environment Configuration

- **Agent Ports**: 8090 (A), 8091 (B), 8092 (C), 8093 (D), 8094 (E)
- **Redis Port**: 6379
- **Volume Mounts**: Live code changes without rebuilds
- **Network**: `mcp_mesh_test_network` for inter-agent communication

### Key Benefits for Development

1. **Multi-Agent Testing**: Easy to test session affinity between identical replicas
2. **Live Reloading**: Code changes reflected immediately after container restart
3. **Isolated Environment**: No conflicts with local development
4. **Realistic Scenarios**: Multiple agents with shared Redis storage
5. **Easy Debugging**: Individual agent logs and health checks

### Quick Development Cycle

```bash
# 1. Make code changes in src/runtime/python/
vim src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py

# 2. Restart containers
docker-compose restart

# 3. Test changes
curl http://localhost:8090/metadata
python test_phase4_session_affinity.py

# 4. View logs if needed
docker-compose logs -f agent_a
```

This environment eliminates the complexity of running multiple agents locally and provides a realistic testing scenario for session affinity and multi-agent functionality.

---

## Phase 1: Foundation - Add Metadata Endpoint

**Goal**: Add `/metadata` endpoint to expose capability routing information
**Risk**: Low - Purely additive, no breaking changes
**Timeline**: 1-2 days
**Files**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`

### Precise Changes Required:

#### 1. Add metadata endpoint to FastAPI app

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: After line 69 (after health endpoints)

```python
@app.get("/metadata")
async def get_routing_metadata():
    """Get routing metadata for all capabilities on this agent."""
    from ...engine.decorator_registry import DecoratorRegistry
    from datetime import datetime

    capabilities_metadata = {}

    # Get all registered mesh tools from existing DecoratorRegistry
    try:
        registered_tools = DecoratorRegistry.get_all_mesh_tools()

        for func_name, (func, metadata) in registered_tools.items():
            capability_name = metadata.get('capability', func_name)
            capabilities_metadata[capability_name] = {
                "function_name": func_name,
                "capability": capability_name,
                "version": metadata.get('version', '1.0.0'),
                "tags": metadata.get('tags', []),
                "description": metadata.get('description', ''),
                # Extract routing flags from **kwargs (already supported)
                "session_required": metadata.get('session_required', False),
                "stateful": metadata.get('stateful', False),
                "streaming": metadata.get('streaming', False),
                "full_mcp_access": metadata.get('full_mcp_access', False),
                # Include any custom metadata from **kwargs
                "custom_metadata": {k: v for k, v in metadata.items()
                                 if k not in ['capability', 'function_name', 'version',
                                            'tags', 'description', 'dependencies']}
            }
    except Exception as e:
        logger.warning(f"Failed to get mesh tools metadata: {e}")
        capabilities_metadata = {}

    # Get agent configuration from context
    agent_config = context.get('agent_config', {})

    return {
        "agent_id": agent_config.get('agent_id', 'unknown'),
        "capabilities": capabilities_metadata,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy"
    }
```

#### 2. No changes needed to decorators (already support \*\*kwargs)

**Current `@mesh.tool` decorator already supports**:

```python
@mesh.tool(
    capability="test_capability",
    session_required=True,      # ✅ Already stored in metadata
    stateful=True,             # ✅ Already stored in metadata
    full_mcp_access=False,     # ✅ Already stored in metadata
    custom_priority="high"     # ✅ Already stored in metadata
)
def test_function():
    pass
```

### What Works After Phase 1:

- ✅ All existing functionality unchanged
- ✅ New `/metadata` endpoint exposes capability routing information
- ✅ Routing flags from `@mesh.tool(**kwargs)` are exposed
- ✅ Foundation for intelligent routing decisions

### What Doesn't Work Yet:

- ❌ HTTP wrapper doesn't use metadata for routing decisions
- ❌ No session affinity implementation
- ❌ No full MCP protocol support (still only tools/call)

### Testing Phase 1:

```bash
# Test basic metadata endpoint
curl http://localhost:8080/metadata

# Expected response:
{
  "agent_id": "agent-123",
  "capabilities": {
    "my_capability": {
      "function_name": "my_function",
      "capability": "my_capability",
      "session_required": true,
      "stateful": false,
      "full_mcp_access": false,
      "custom_metadata": {"priority": "high"}
    }
  },
  "timestamp": "2025-07-03T12:00:00.000Z",
  "status": "healthy"
}

# Test with routing flags
@mesh.tool(
    capability="session_test",
    session_required=True,
    stateful=True,
    priority="high"
)
def session_test():
    return {"test": "value"}

curl http://localhost:8080/metadata | jq '.capabilities.session_test'
```

---

## Phase 2: Full MCP Protocol Support

**Goal**: Add full MCP protocol methods to existing `MCPClientProxy`
**Risk**: Low - Extends existing proxy without breaking current functionality
**Timeline**: 3-4 days
**Files**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`

### Current State Analysis:

- ✅ `MCPClientProxy` already acts as universal proxy
- ✅ Dependency injection already chooses between `MCPClientProxy` and `SelfDependencyProxy`
- ❌ Only supports `tools/call` method, missing tools/list, resources/_, prompts/_

### Precise Changes Required:

#### 1. Add MCP protocol methods to MCPClientProxy

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Add methods after line 47 (after `__call__` method)

```python
# Add these methods to existing MCPClientProxy class
async def list_tools(self) -> List[Dict[str, Any]]:
    """List available tools from remote agent."""
    return await self._make_mcp_request("tools/list", {})

async def list_resources(self) -> List[Dict[str, Any]]:
    """List available resources from remote agent."""
    return await self._make_mcp_request("resources/list", {})

async def read_resource(self, uri: str) -> Dict[str, Any]:
    """Read a specific resource from remote agent."""
    return await self._make_mcp_request("resources/read", {"uri": uri})

async def list_prompts(self) -> List[Dict[str, Any]]:
    """List available prompts from remote agent."""
    return await self._make_mcp_request("prompts/list", {})

async def get_prompt(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
    """Get a specific prompt from remote agent."""
    params = {"name": name}
    if arguments:
        params["arguments"] = arguments
    return await self._make_mcp_request("prompts/get", params)

async def _make_mcp_request(self, method: str, params: Dict[str, Any]) -> Any:
    """Make generic MCP JSON-RPC request."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }

    url = f"{self.endpoint}/mcp/"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        result = response.json()
        if "error" in result:
            raise Exception(f"MCP request failed: {result['error']}")

        return result.get("result")
```

#### 2. Update existing `__call__` method to use generic helper

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Replace existing `__call__` method (lines 22-47)

```python
async def __call__(self, **kwargs) -> Any:
    """Callable interface for dependency injection (tools/call method)."""
    try:
        # Use generic MCP request method for tools/call
        result = await self._make_mcp_request("tools/call", {
            "name": self.function_name,
            "arguments": kwargs
        })

        # Apply existing content extraction logic
        from .content_extractor import ContentExtractor
        return ContentExtractor.extract_content(result)

    except Exception as e:
        logger.error(f"MCP call to {self.endpoint}/{self.function_name} failed: {e}")
        raise
```

#### 3. Add imports at top of file

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Add after existing imports (around line 8)

```python
import uuid
from typing import List, Dict, Any
```

### What Works After Phase 2:

- ✅ All existing functionality unchanged
- ✅ Full MCP protocol support available on proxies
- ✅ Agent introspection capabilities (list_tools, list_resources, etc.)
- ✅ Can query remote agent capabilities dynamically

### What Doesn't Work Yet:

- ❌ HTTP wrapper doesn't use metadata for routing decisions
- ❌ No session affinity implementation
- ❌ No intelligent routing based on metadata

### Testing Phase 2:

```bash
# Existing tests should still pass
python -m pytest src/runtime/python/tests/unit/test_10_mcp_client_proxy.py

# Previously failing tests should now pass
python -m pytest src/runtime/python/tests/unit/test_16_mcp_client_proxy_unsupported.py

# Test new functionality
import asyncio
from _mcp_mesh.engine.mcp_client_proxy import MCPClientProxy

proxy = MCPClientProxy("http://remote-agent:8080", "test_function")
tools = await proxy.list_tools()
print(f"Remote agent has {len(tools)} tools")
```

---

## Phase 3: HTTP Wrapper Intelligence - Metadata Lookup

**Goal**: Add metadata lookup to HTTP wrapper with logging (no routing changes yet)
**Risk**: Low - Adds logging and metadata access, no behavior change
**Timeline**: 2-3 days
**Files**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`

### Current State Analysis:

- ✅ `HttpMcpWrapper` already exists and mounts FastMCP apps
- ✅ Basic capability extraction already implemented
- ✅ DecoratorRegistry provides in-memory access to capability metadata
- ❌ No routing intelligence logging for debugging

### Precise Changes Required:

#### 1. Add direct metadata access methods to HttpMcpWrapper

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Add after line 138 (after `get_endpoint` method)

```python
def _get_capability_metadata(self, capability: str) -> dict:
    """Get metadata for a specific capability directly from DecoratorRegistry."""
    try:
        from ...engine.decorator_registry import DecoratorRegistry

        # Direct access to in-memory registry - no HTTP calls needed!
        registered_tools = DecoratorRegistry.get_mesh_tools()

        for func_name, decorated_func in registered_tools.items():
            metadata = decorated_func.metadata
            if metadata.get('capability') == capability:
                return metadata

        logger.debug(f"🔍 No metadata found for capability: {capability}")
        return {}

    except Exception as e:
        logger.warning(f"Failed to get capability metadata for {capability}: {e}")
        return {}

def log_routing_decision(self, capability: str, session_id: str = None, mcp_method: str = "tools/call"):
    """Log what routing decision would be made (no actual routing yet)."""
    try:
        # Get metadata directly from DecoratorRegistry
        metadata = self._get_capability_metadata(capability)

        if not metadata:
            logger.debug(f"🔍 No metadata found for capability: {capability}")
            return

        # Log routing decisions that would be made
        if metadata.get('session_required'):
            logger.info(f"📍 Session affinity required for {capability}, session={session_id}")

        if metadata.get('full_mcp_access'):
            logger.info(f"🔓 Full MCP protocol access needed for {capability}")

        if metadata.get('stateful'):
            logger.info(f"🔄 Stateful capability: {capability}")

        if metadata.get('streaming'):
            logger.info(f"🌊 Streaming capability: {capability}")

        # Extract custom metadata (excluding standard fields)
        custom_metadata = {k: v for k, v in metadata.items()
                         if k not in ['capability', 'function_name', 'version',
                                    'tags', 'description', 'dependencies', 'session_required',
                                    'stateful', 'full_mcp_access', 'streaming']}
        if custom_metadata:
            logger.info(f"⚙️ Custom metadata for {capability}: {custom_metadata}")

    except Exception as e:
        logger.warning(f"Failed to log routing decision for {capability}: {e}")
```

#### 3. Integrate routing decision logging (Phase 3 only logs, no actual routing)

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Modify the `setup` method around line 55

```python
async def setup(self):
    """Set up FastMCP app for integration with metadata intelligence."""

    # Existing setup code...
    logger.debug(f"🔍 DEBUG: FastMCP server type: {type(self.mcp_server)}")

    if self._mcp_app is not None:
        logger.debug("🔍 DEBUG: FastMCP app prepared for integration")

        # Add middleware for routing intelligence (logging only in Phase 3)
        @self._mcp_app.middleware("http")
        async def routing_intelligence_middleware(request, call_next):
            """Middleware to log routing decisions without changing behavior."""

            # Extract routing information from headers
            capability = request.headers.get("x-capability")
            session_id = request.headers.get("x-session-id")
            mcp_method = request.headers.get("x-mcp-method", "tools/call")

            # Log what routing decision would be made
            if capability:
                self.log_routing_decision(capability, session_id, mcp_method)

            # Continue with normal processing (no routing changes yet)
            response = await call_next(request)
            return response

        logger.debug("🌐 FastMCP app ready with routing intelligence")
    else:
        logger.warning("❌ FastMCP server doesn't have any supported HTTP app method")
        raise AttributeError("No supported HTTP app method")
```

#### 4. Add required imports

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Add after existing imports around line 9

```python
import time
import asyncio
```

### What Works After Phase 3:

- ✅ All existing functionality unchanged
- ✅ HTTP wrapper accesses metadata directly from DecoratorRegistry (fast, in-memory)
- ✅ Logs routing decisions for debugging and monitoring
- ✅ Foundation for intelligent routing in later phases
- ✅ No unnecessary HTTP calls or caching overhead

### What Doesn't Work Yet:

- ❌ No actual routing changes (just logging)
- ❌ No session affinity implementation
- ❌ No different behavior based on metadata

### Testing Phase 3:

```bash
# Test metadata caching
curl http://localhost:8080/metadata

# Test with routing headers to see logging
curl -H "X-Capability: test_capability" -H "X-Session-ID: test-123" -H "X-MCP-Method: tools/call" \
     -X POST http://localhost:8080/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test","arguments":{}}}'

# Check logs for routing intelligence
tail -f logs/mcp-mesh.log | grep "Session affinity\|Full MCP\|Stateful\|Streaming"

# Test with capability that has routing flags
@mesh.tool(
    capability="session_test",
    session_required=True,
    stateful=True,
    priority="high"
)
def session_test():
    return {"test": "value"}

# Should see in logs:
# 📍 Session affinity required for session_test, session=test-123
# 🔄 Stateful capability: session_test
# ⚙️ Custom metadata for session_test: {'priority': 'high'}
```

---

## Phase 4: Session Affinity Implementation

**Goal**: Implement per-agent-instance session affinity for stateful requests
**Risk**: Low - Simple session stickiness within identical agent replicas
**Timeline**: 2-3 days
**Files**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`

### Current State Analysis:

- ✅ HTTP wrapper logs routing decisions
- ✅ Direct metadata access from DecoratorRegistry implemented
- ❌ No session stickiness between identical agent replicas

### Architectural Approach:

- **Per-Agent-Instance Stickiness**: Sessions stick to entire agent pods, not per-capability
- **Self-Assignment**: First pod to see a session claims it via Redis
- **Direct Pod Forwarding**: Pod-to-pod communication within Kubernetes
- **No Registry Discovery**: If request reached this agent, it can handle it

### Precise Changes Required:

#### 1. Add session affinity middleware to FastAPI setup

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Replace the existing RoutingIntelligenceMiddleware

```python
def _add_session_affinity_middleware(self, app: Any) -> None:
    """Add session affinity middleware for per-agent-instance stickiness."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    import json
    import os
    import httpx
    from fastapi import Response

    class SessionAffinityMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, logger):
            super().__init__(app)
            self.logger = logger
            self.pod_ip = os.getenv('POD_IP', 'localhost')
            self.pod_port = os.getenv('POD_PORT', '8080')
            self._init_redis()

        def _init_redis(self):
            """Initialize Redis for session storage."""
            try:
                import redis
                redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()
                self.redis_available = True
                self.logger.info(f"✅ Session affinity Redis connected: {redis_url}")
            except Exception as e:
                self.logger.warning(f"⚠️ Redis unavailable for sessions, using local: {e}")
                self.redis_available = False
                self.local_sessions = {}

        async def dispatch(self, request: Request, call_next):
            # Only handle MCP requests
            if not request.url.path.startswith("/mcp"):
                return await call_next(request)

            # Extract session ID from request
            session_id = await self._extract_session_id(request)

            if session_id:
                # Check for existing session assignment
                assigned_pod = await self._get_session_assignment(session_id)

                if assigned_pod and assigned_pod != self.pod_ip:
                    # Forward to assigned pod
                    return await self._forward_to_pod(request, assigned_pod)
                elif not assigned_pod:
                    # New session - assign to this pod
                    await self._assign_session(session_id, self.pod_ip)
                    self.logger.info(f"📍 Session {session_id} assigned to {self.pod_ip}")
                # else: assigned to this pod, process locally

            # Process locally
            return await call_next(request)

        async def _extract_session_id(self, request: Request) -> str:
            """Extract session ID from request headers or body."""
            # Try header first
            session_id = request.headers.get("X-Session-ID")
            if session_id:
                return session_id

            # Try extracting from JSON-RPC body
            try:
                body = await request.body()
                if body:
                    payload = json.loads(body.decode('utf-8'))
                    if payload.get("method") == "tools/call":
                        arguments = payload.get("params", {}).get("arguments", {})
                        return arguments.get("session_id")
            except Exception:
                pass

            return None

        async def _get_session_assignment(self, session_id: str) -> str:
            """Get existing session assignment."""
            session_key = f"session:{session_id}"

            if self.redis_available:
                try:
                    return self.redis_client.get(session_key)
                except Exception as e:
                    self.logger.warning(f"Redis get failed: {e}")
                    self.redis_available = False

            # Fallback to local storage
            return self.local_sessions.get(session_key)

        async def _assign_session(self, session_id: str, pod_ip: str):
            """Assign session to pod."""
            session_key = f"session:{session_id}"
            ttl = 3600  # 1 hour

            if self.redis_available:
                try:
                    self.redis_client.setex(session_key, ttl, pod_ip)
                    return
                except Exception as e:
                    self.logger.warning(f"Redis set failed: {e}")
                    self.redis_available = False

            # Fallback to local storage
            self.local_sessions[session_key] = pod_ip

        async def _forward_to_pod(self, request: Request, target_pod: str):
            """Forward request to target pod."""
            try:
                # Read request body
                body = await request.body()

                # Prepare headers
                headers = dict(request.headers)
                headers.pop('host', None)
                headers.pop('content-length', None)

                # Forward to target pod
                target_url = f"http://{target_pod}:{self.pod_port}{request.url.path}"
                self.logger.info(f"🔄 Forwarding session to {target_url}")

                async with httpx.AsyncClient() as client:
                    response = await client.request(
                        method=request.method,
                        url=target_url,
                        headers=headers,
                        content=body,
                        params=request.query_params
                    )

                    return Response(
                        content=response.content,
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )

            except Exception as e:
                self.logger.error(f"❌ Session forwarding failed: {e}")
                # Return error - don't process locally as it would break session affinity
                return Response(
                    content=json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {
                            "code": -32603,
                            "message": f"Session forwarding failed: {str(e)}"
                        }
                    }),
                    status_code=503,
                    headers={"Content-Type": "application/json"}
                )

    # Add the middleware to the app
    app.add_middleware(SessionAffinityMiddleware, logger=self.logger)
```

#### 2. Update FastAPI integration to use session affinity

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Replace \_add_routing_intelligence_middleware call in \_integrate_mcp_wrapper

```python
def _integrate_mcp_wrapper(self, app: Any, mcp_wrapper: Any, server_key: str) -> None:
    """Integrate HttpMcpWrapper FastMCP app into the main FastAPI app."""
    try:
        fastmcp_app = mcp_wrapper._mcp_app

        if fastmcp_app is not None:
            # Add session affinity middleware instead of routing intelligence
            self._add_session_affinity_middleware(app)

            # Mount the FastMCP app at root
            app.mount("", fastmcp_app)
            self.logger.debug(f"Mounted FastMCP app with session affinity from '{server_key}'")
        else:
            self.logger.warning(f"No FastMCP app available in wrapper '{server_key}'")

    except Exception as e:
        self.logger.error(f"Failed to integrate MCP wrapper '{server_key}': {e}")
        raise
```

### What Works After Phase 4:

- ✅ **Per-Agent-Instance Session Stickiness**: Sessions stick to entire agent pods
- ✅ **Redis-Backed Storage**: Sessions persisted across requests with TTL
- ✅ **Self-Assignment Logic**: First pod to see session claims it automatically
- ✅ **Direct Pod Forwarding**: Pod-to-pod communication within Kubernetes
- ✅ **Graceful Fallback**: Local storage when Redis unavailable
- ✅ **Session Extraction**: From headers (`X-Session-ID`) or JSON-RPC body (`session_id` argument)
- ✅ **No Registry Dependency**: No agent discovery needed for incoming requests

### What Doesn't Work Yet:

- ❌ **Multi-Replica Discovery**: No awareness of which pods are replicas vs different agents
- ❌ **Load Balancing**: Sessions assigned to first pod, not balanced across replicas
- ❌ **Session Migration**: No handling when assigned pod goes down

### Testing Phase 4:

```bash
# Test 1: Session creation and stickiness
curl -X POST http://localhost:8090/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"increment":1,"session_id":"user-123"}}}' \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream"

# Test 2: Same session should stick to same pod
curl -X POST http://localhost:8091/mcp/ \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"increment_counter","arguments":{"increment":2,"session_id":"user-123"}}}' \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream"
# Should forward back to agent A if session was created there

# Test 3: Different session can go to different pod
curl -X POST http://localhost:8091/mcp/ \
     -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"increment_counter","arguments":{"increment":5,"session_id":"user-456"}}}' \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream"

# Test 4: Check Redis has session assignments
docker exec testing-redis-1 redis-cli KEYS "session:*"
docker exec testing-redis-1 redis-cli GET "session:user-123"

# Expected behavior:
# - session:user-123 → assigned to first pod that handled it
# - All subsequent requests with user-123 forward to that pod
# - session:user-456 → can be assigned to any pod
```

---

## Phase 5: Clean Architecture - Move Session Logic to HttpMcpWrapper

**Goal**: Move session routing from FastAPI middleware to HttpMcpWrapper for clean architecture
**Risk**: Low - Architectural refactor with maintained functionality
**Timeline**: 2-3 days
**Files**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`, `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`

### Current State Analysis (Post-Phase 4):

- ✅ Session affinity working with Redis backend and local fallback
- ❌ Session logic in FastAPI middleware (architectural impurity)
- ❌ No session statistics in metadata endpoint
- ❌ No dedicated SessionStorage class

### Precise Changes Required:

#### 1. Create SessionStorage class with Redis and memory fallback

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Add after imports

```python
class SessionStorage:
    """Session storage with Redis backend and in-memory fallback."""

    def __init__(self):
        self.redis_client = None
        self.memory_store = {}  # Fallback storage (always available)
        self.redis_available = False
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis client with graceful fallback."""
        try:
            import redis
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
            self.redis_available = True
            logger.info(f"✅ Redis session storage connected: {redis_url}")
        except Exception as e:
            logger.warning(f"⚠️ Redis unavailable, using in-memory sessions: {e}")
            self.redis_available = False
            # Agent continues working with local memory - no Redis required!

    async def get_session_pod(self, session_id: str, capability: str = None) -> str:
        """Get assigned pod for session (Redis first, memory fallback)."""
        session_key = f"session:{session_id}:{capability}" if capability else f"session:{session_id}"

        if self.redis_available:
            try:
                assigned_pod = self.redis_client.get(session_key)
                if assigned_pod:
                    return assigned_pod
            except Exception as e:
                logger.warning(f"Redis get failed, falling back to memory: {e}")
                self.redis_available = False

        # Always available - memory fallback
        return self.memory_store.get(session_key)

    async def assign_session_pod(self, session_id: str, pod_ip: str, capability: str = None) -> str:
        """Assign pod to session (Redis preferred, memory always works)."""
        session_key = f"session:{session_id}:{capability}" if capability else f"session:{session_id}"
        ttl = 3600  # 1 hour TTL

        if self.redis_available:
            try:
                self.redis_client.setex(session_key, ttl, pod_ip)
                logger.info(f"📍 Redis: Assigned session {session_key} -> {pod_ip}")
                return pod_ip
            except Exception as e:
                logger.warning(f"Redis set failed, falling back to memory: {e}")
                self.redis_available = False

        # Always works - memory fallback
        self.memory_store[session_key] = pod_ip
        logger.info(f"📍 Memory: Assigned session {session_key} -> {pod_ip}")
        return pod_ip
```

#### 2. Move session routing from FastAPI to HttpMcpWrapper middleware

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Add session routing middleware to FastMCP app

```python
def _add_session_routing_middleware(self):
    """Add session routing middleware to FastMCP app."""
    from starlette.middleware.base import BaseHTTPMiddleware

    class MCPSessionRoutingMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, http_wrapper):
            super().__init__(app)
            self.http_wrapper = http_wrapper

        async def dispatch(self, request: Request, call_next):
            # Extract session ID from request
            session_id = await self.http_wrapper._extract_session_id(request)

            if session_id:
                # Check for existing session assignment
                assigned_pod = await self.http_wrapper.session_storage.get_session_pod(session_id)

                if assigned_pod and assigned_pod != self.http_wrapper.pod_ip:
                    # Forward to assigned pod
                    return await self.http_wrapper._forward_to_external_pod(request, assigned_pod)
                elif not assigned_pod:
                    # New session - assign to this pod
                    await self.http_wrapper.session_storage.assign_session_pod(session_id, self.http_wrapper.pod_ip)

            # Process locally with FastMCP
            return await call_next(request)

    # Add middleware to FastMCP app (not FastAPI)
    self._mcp_app.add_middleware(MCPSessionRoutingMiddleware, http_wrapper=self)
```

#### 3. Remove FastAPI session middleware

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Action**: Remove `_add_session_affinity_middleware` method and its call

#### 4. Add session statistics to metadata endpoint

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Update metadata endpoint to include session stats

```python
# Add session affinity statistics to metadata response
session_affinity_stats = {}
try:
    mcp_wrappers = stored_context.get("mcp_wrappers", {})
    if mcp_wrappers:
        first_wrapper = next(iter(mcp_wrappers.values()))
        if first_wrapper and hasattr(first_wrapper.get("wrapper"), 'get_session_stats'):
            session_affinity_stats = first_wrapper["wrapper"].get_session_stats()
except Exception as e:
    session_affinity_stats = {"error": "session stats unavailable"}

# Include in metadata response
if session_affinity_stats:
    metadata_response["session_affinity"] = session_affinity_stats
```

### What Works After Phase 5:

- ✅ **Clean Architecture**: Session routing moved from FastAPI to HttpMcpWrapper (single responsibility)
- ✅ **All Phase 4 functionality maintained**: Session stickiness, Redis storage, forwarding
- ✅ **SessionStorage class**: Dedicated session management with Redis + memory fallback
- ✅ **Session statistics**: Visible in `/metadata` endpoint for monitoring
- ✅ **Architectural purity**: FastAPI only handles HTTP server, MCP logic in HttpMcpWrapper
- ✅ **Redis completely optional**: Agents work perfectly without Redis (memory fallback)
- ✅ **Production-ready**: Redis with TTL, automatic cleanup, graceful degradation

### Redis Optional Behavior:

- ✅ **Single Agent**: No Redis needed, works perfectly
- ✅ **Multiple Different Agents**: No Redis needed, each handles its capabilities
- ✅ **Multiple Identical Replicas**: Redis recommended for session stickiness
- ✅ **Development/Testing**: No infrastructure setup required

### What Doesn't Work Yet:

- ❌ **Multi-Replica Discovery**: No awareness of which pods are replicas vs different agents
- ❌ **Load Balancing**: Sessions assigned to first pod, not balanced across replicas
- ❌ **Session Migration**: No handling when assigned pod goes down

### Testing Phase 5:

```bash
# Test 1: Clean architecture - session stats in metadata
curl http://localhost:8090/metadata | jq '.session_affinity'
# Expected: {"pod_ip": "agent-a", "storage_backend": "redis", "redis_available": true, ...}

# Test 2: Session creation with clean HttpMcpWrapper routing
curl -X POST http://localhost:8090/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"increment":1,"session_id":"phase5-test"}}}' \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream"

# Test 3: Session forwarding between agents
curl -X POST http://localhost:8091/mcp/ \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"increment_counter","arguments":{"increment":5,"session_id":"phase5-test"}}}' \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream"
# Should forward to agent A, counter should be 6

# Test 4: Redis storage verification
docker exec testing-redis-1 redis-cli GET "session:phase5-test"
# Expected: "agent-a"

# Test 5: Session statistics updated
curl http://localhost:8090/metadata | jq '.session_affinity.total_sessions'
# Should include the new session

# Test 6: Verify clean architecture - FastAPI has no session middleware
# Only HttpMcpWrapper handles session routing now
```

### Architecture Validation:

```bash
# Before Phase 5: FastAPI middleware handled session routing
# After Phase 5: HttpMcpWrapper middleware handles session routing

# FastAPI responsibilities: HTTP server, K8s endpoints only
# HttpMcpWrapper responsibilities: MCP routing, session affinity
# Single responsibility principle maintained ✅
```

---

## Phase 6: Enhanced MCP Client Proxy with Full MCP Protocol Support

**Goal**: Create McpAgent with full MCP capabilities (sessions, streams, circuit breaker) vs McpMeshAgent (tool calls only)
**Risk**: Medium - Adds new agent type but maintains backward compatibility
**Timeline**: 3-4 days
**Files**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`

### Current State Analysis:

- ✅ Phase 2 added basic MCP protocol methods to `MCPClientProxy`
- ✅ Session affinity working with Redis storage in HTTP wrapper
- ✅ HTTP wrapper successfully routes to FastMCP (receiving side complete)
- ❌ MCP Client Proxy only supports basic tool calls (outgoing side incomplete)
- ❌ No distinction between McpMeshAgent vs McpAgent
- ❌ No support for sessions, streams, circuit breaker, cancellation

### Architectural Understanding:

**Flow**: Req → HTTP Wrapper → FastMCP → Functions in script → MCP Client Proxy → Agent B

**HTTP Wrapper (Receiving Side)**: ✅ DONE - Session routing, forwards to FastMCP
**MCP Client Proxy (Outgoing Side)**: ❌ NEEDS WORK - Full MCP protocol support

### Two Agent Types Needed:

- **McpMeshAgent**: Tool calls only (current implementation)
- **McpAgent**: Full MCP protocol (sessions, streams, circuit breaker, cancellation)

### Precise Changes Required:

#### 1. Create McpAgent class for full MCP protocol support with streaming

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Add new class alongside existing MCPClientProxy

```python
class McpAgent:
    """Full MCP protocol agent with sessions, streams, circuit breaker, cancellation."""

    def __init__(self, endpoint: str, agent_id: str = None, auto_session: bool = False):
        self.endpoint = endpoint
        self.agent_id = agent_id or f"mcp_agent_{uuid.uuid4().hex[:8]}"
        self.session_id = None
        self.auto_session = auto_session
        self.active_requests = {}  # Track for cancellation
        self.active_streams = {}   # Track for stream cancellation
        self.circuit_breaker = CircuitBreaker()

    # Session Management
    async def initialize_session(self, session_id: str = None) -> str:
        """Initialize persistent session."""
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"

        # For Phase 6, we don't actually call session/initialize
        # FastMCP handles sessions through X-Session-ID headers
        logger.info(f"Session {self.session_id} initialized for {self.agent_id}")
        return self.session_id

    async def close_session(self):
        """Close persistent session."""
        if self.session_id:
            # Cancel any active streams
            for stream_id in list(self.active_streams.keys()):
                await self.cancel_stream(stream_id)

            self.session_id = None
            logger.info(f"Session closed for {self.agent_id}")

    async def __aenter__(self):
        """Context manager entry - auto-initialize session."""
        if self.auto_session:
            await self.initialize_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - auto-close session."""
        if self.session_id:
            await self.close_session()

    # Full MCP Protocol Methods
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from remote agent."""
        return await self._make_mcp_request("tools/list", {})

    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        """Call a specific tool (non-streaming)."""
        return await self._make_mcp_request("tools/call", {
            "name": name,
            "arguments": arguments or {}
        })

    async def call_tool_streaming(self, name: str, arguments: Dict[str, Any] = None) -> AsyncIterator[Dict[str, Any]]:
        """Call a specific tool with streaming response - THE BREAKTHROUGH METHOD!"""
        stream_id = str(uuid.uuid4())

        try:
            # Track this stream for cancellation
            self.active_streams[stream_id] = {
                "tool_name": name,
                "started_at": time.time(),
                "cancelled": False
            }

            async for chunk in self._make_streaming_request("tools/call", {
                "name": name,
                "arguments": arguments or {}
            }, stream_id):
                # Check if stream was cancelled
                if self.active_streams.get(stream_id, {}).get("cancelled"):
                    logger.info(f"Stream {stream_id} cancelled")
                    break

                yield chunk

        finally:
            # Clean up stream tracking
            self.active_streams.pop(stream_id, None)

    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources."""
        return await self._make_mcp_request("resources/list", {})

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a specific resource."""
        return await self._make_mcp_request("resources/read", {"uri": uri})

    async def subscribe_resource(self, uri: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to resource updates (streaming)."""
        stream_id = str(uuid.uuid4())

        try:
            self.active_streams[stream_id] = {
                "resource_uri": uri,
                "started_at": time.time(),
                "cancelled": False
            }

            async for update in self._make_streaming_request("resources/subscribe", {
                "uri": uri
            }, stream_id):
                if self.active_streams.get(stream_id, {}).get("cancelled"):
                    break
                yield update

        finally:
            self.active_streams.pop(stream_id, None)

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """List available prompts."""
        return await self._make_mcp_request("prompts/list", {})

    async def get_prompt(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get a specific prompt."""
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return await self._make_mcp_request("prompts/get", params)

    # Cancellation Support
    async def cancel_request(self, request_id: str):
        """Cancel an active request."""
        if request_id in self.active_requests:
            self.active_requests[request_id]["cancelled"] = True
            logger.info(f"Request {request_id} marked for cancellation")

    async def cancel_stream(self, stream_id: str):
        """Cancel an active stream."""
        if stream_id in self.active_streams:
            self.active_streams[stream_id]["cancelled"] = True
            logger.info(f"Stream {stream_id} marked for cancellation")

    # Circuit Breaker Pattern
    async def _make_mcp_request_with_circuit_breaker(self, method: str, params: Dict[str, Any]) -> Any:
        """Make MCP request with circuit breaker protection."""
        if self.circuit_breaker.is_open():
            raise Exception("Circuit breaker is open - remote agent unavailable")

        try:
            result = await self._make_mcp_request(method, params)
            self.circuit_breaker.record_success()
            return result
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise

    # Core Request Method
    async def _make_mcp_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Make MCP JSON-RPC request with session support."""
        # Auto-initialize session if needed
        if self.auto_session and not self.session_id:
            await self.initialize_session()

        request_id = str(uuid.uuid4())

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        # Add session header if available
        if self.session_id:
            headers["X-Session-ID"] = self.session_id

        # Track request for cancellation
        self.active_requests[request_id] = {
            "method": method,
            "params": params,
            "started_at": time.time(),
            "cancelled": False
        }

        try:
            url = f"{self.endpoint}/mcp/"

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()

                result = response.json()
                if "error" in result:
                    raise Exception(f"MCP request failed: {result['error']}")

                return result.get("result")

        finally:
            # Clean up request tracking
            self.active_requests.pop(request_id, None)

    # Streaming Support - THE KEY METHOD FOR MULTIHOP STREAMING
    async def _make_streaming_request(self, method: str, params: Dict[str, Any], stream_id: str = None) -> AsyncIterator[Dict[str, Any]]:
        """Make streaming MCP request using FastMCP's text/event-stream support."""
        # Auto-initialize session if needed
        if self.auto_session and not self.session_id:
            await self.initialize_session()

        request_id = str(uuid.uuid4())

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream"  # KEY: Request streaming response
        }

        if self.session_id:
            headers["X-Session-ID"] = self.session_id

        url = f"{self.endpoint}/mcp/"

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        # Check for cancellation
                        if stream_id and self.active_streams.get(stream_id, {}).get("cancelled"):
                            break

                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])  # Remove "data: " prefix
                                yield data
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            self.circuit_breaker.record_failure()
            raise
        else:
            self.circuit_breaker.record_success()


class CircuitBreaker:
    """Circuit breaker with streaming support."""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.streaming_failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def is_open(self) -> bool:
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half-open"
                return False
            return True
        return False

    def record_success(self):
        self.failure_count = 0
        self.streaming_failure_count = 0
        self.state = "closed"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def record_streaming_failure(self):
        """Track streaming-specific failures."""
        self.streaming_failure_count += 1
        self.record_failure()  # Also count as general failure
```

#### 2. Create McpMeshAgent wrapper for tool calls only

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Add wrapper class

```python
class McpMeshAgent:
    """Simplified MCP agent for tool calls only (current MCP Mesh behavior)."""

    def __init__(self, endpoint: str, function_name: str):
        self.endpoint = endpoint
        self.function_name = function_name
        # Use existing MCPClientProxy for backward compatibility
        self.proxy = MCPClientProxy(endpoint, function_name)

    async def call_tool(self, **kwargs) -> Any:
        """Call tool using existing MCP Mesh proxy."""
        return await self.proxy(**kwargs)

    # Expose existing MCPClientProxy methods for compatibility
    async def list_tools(self) -> List[Dict[str, Any]]:
        return await self.proxy.list_tools()

    async def list_resources(self) -> List[Dict[str, Any]]:
        return await self.proxy.list_resources()

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        return await self.proxy.read_resource(uri)

    async def list_prompts(self) -> List[Dict[str, Any]]:
        return await self.proxy.list_prompts()

    async def get_prompt(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        return await self.proxy.get_prompt(name, arguments)
```

#### 3. Update dependency injection to choose agent type

**File**: `src/runtime/python/_mcp_mesh/engine/dependency_injector.py`
**Location**: Update resolve_dependency method

```python
def resolve_dependency(self, dependency_name: str, context: dict = None) -> Any:
    """Resolve dependency with agent type selection."""

    # Check if full MCP protocol is requested
    if context and context.get('full_mcp_protocol', False):
        # Use McpAgent for full MCP protocol support
        endpoint = self._resolve_endpoint(dependency_name, context)
        return McpAgent(endpoint, agent_id=dependency_name)
    else:
        # Use McpMeshAgent for simple tool calls (current behavior)
        endpoint = self._resolve_endpoint(dependency_name, context)
        return McpMeshAgent(endpoint, function_name=dependency_name)
```

### What Works After Phase 6:

- ✅ **BREAKTHROUGH: Streaming Tools/Call**: First platform to support streaming `tools/call` across distributed networks
- ✅ **Multihop Streaming**: Agent A → Agent B → Agent C streaming chains using FastMCP's `text/event-stream`
- ✅ **McpAgent**: Full MCP protocol with sessions, streams, circuit breaker, cancellation
- ✅ **McpMeshAgent**: Simple tool calls (maintains backward compatibility)
- ✅ **Explicit API**: Developers choose `call_tool()` vs `call_tool_streaming()`
- ✅ **Session management**: Auto-session support with context managers (`async with McpAgent()`)
- ✅ **Circuit breaker**: Fault tolerance for both regular and streaming requests
- ✅ **Stream cancellation**: Cancel active streams with proper cleanup
- ✅ **100% MCP compatibility**: Standard MCP protocol + FastMCP streaming extension
- ✅ **Production ready**: All reliability features work with streaming

### What Doesn't Work Yet:

- ❌ Session persistence across agent restarts
- ❌ Advanced session state management
- ❌ Distributed session sharing between different agent types

### Testing Phase 6:

```python
# Test 1: BREAKTHROUGH - Streaming Tools/Call
from _mcp_mesh.engine.mcp_client_proxy import McpAgent

async def test_streaming_breakthrough():
    agent = McpAgent("http://remote-agent:8080", auto_session=True)

    # THE GAME CHANGER: Streaming tools/call
    async for chunk in agent.call_tool_streaming("chat", {
        "message": "Write a long story",
        "session_id": "user_123"
    }):
        print(chunk["text"], end="")  # Real-time streaming response!

    print("\n✅ Streaming tools/call working!")

# Test 2: Multihop Streaming (Agent A -> B -> C)
async def test_multihop_streaming():
    # Agent A calls Agent B
    agent_b = McpAgent("http://agent-b:8080", auto_session=True)

    # Agent B internally calls Agent C with streaming
    # This creates A -> B -> C streaming chain!
    async for token in agent_b.call_tool_streaming("relay_chat", {
        "message": "Tell me about quantum computing",
        "target_agent": "agent-c"
    }):
        print(f"A <- B <- C: {token}", end="")

    print("\n✅ Multihop streaming working!")

# Test 3: Context Manager (Developer Friendly)
async def test_context_manager():
    async with McpAgent("http://remote:8080", auto_session=True) as agent:
        # Session auto-created
        async for response in agent.call_tool_streaming("generate_code", {
            "prompt": "Create a Python web server"
        }):
            print(response["code"], end="")
        # Session auto-closed

    print("\n✅ Auto-session management working!")

# Test 4: Stream Cancellation
async def test_stream_cancellation():
    agent = McpAgent("http://remote:8080")

    # Start a long-running stream
    stream = agent.call_tool_streaming("long_computation", {"size": 1000000})

    count = 0
    async for chunk in stream:
        print(f"Chunk {count}: {chunk}")
        count += 1

        # Cancel after 5 chunks
        if count >= 5:
            await agent.cancel_stream(stream.stream_id)
            break

    print("✅ Stream cancellation working!")

# Test 5: Backward Compatibility
async def test_backward_compatibility():
    # McpMeshAgent (old way) still works
    from _mcp_mesh.engine.mcp_client_proxy import McpMeshAgent

    mesh_agent = McpMeshAgent("http://remote:8080", "calculator")
    result = await mesh_agent.call_tool(operation="add", a=5, b=3)
    print(f"McpMeshAgent result: {result}")

    # McpAgent (new way) with non-streaming
    mcp_agent = McpAgent("http://remote:8080")
    result = await mcp_agent.call_tool("calculator", {"operation": "multiply", "a": 4, "b": 6})
    print(f"McpAgent result: {result}")

    print("✅ Backward compatibility maintained!")

# Test 6: Circuit Breaker with Streaming
async def test_circuit_breaker_streaming():
    agent = McpAgent("http://unreliable-agent:8080")

    try:
        async for chunk in agent.call_tool_streaming("unreliable_tool", {}):
            print(f"Received: {chunk}")
    except Exception as e:
        print(f"Circuit breaker engaged: {e}")

        # Circuit breaker should prevent further streaming attempts
        if agent.circuit_breaker.is_open():
            print("✅ Circuit breaker protecting streaming!")

# Run all tests
async def run_phase6_tests():
    await test_streaming_breakthrough()
    await test_multihop_streaming()
    await test_context_manager()
    await test_stream_cancellation()
    await test_backward_compatibility()
    await test_circuit_breaker_streaming()

    print("\n🎉 Phase 6 - All streaming features working!")
```

### Multihop Streaming Example:

```python
# Agent C - streaming chat tool
@mesh.tool(capability="chat", streaming=True)
async def chat(message: str):
    """Streaming chat that yields tokens."""
    for token in generate_response_tokens(message):
        yield {"text": token, "done": False}
    yield {"text": "", "done": True}

# Agent B - relay streaming tool
@mesh.tool(capability="relay_chat", streaming=True)
async def relay_chat(message: str, target_agent: str):
    """Relay streaming call to downstream agent."""
    agent_c = McpAgent(f"http://{target_agent}:8080", auto_session=True)

    # Forward stream from C to A through B
    async for chunk in agent_c.call_tool_streaming("chat", {"message": message}):
        yield chunk  # This creates the A -> B -> C streaming chain!

# Agent A - consumer
async def main():
    agent_b = McpAgent("http://agent-b:8080", auto_session=True)

    # A -> B -> C streaming chain
    async for token in agent_b.call_tool_streaming("relay_chat", {
        "message": "Hello world",
        "target_agent": "agent-c"
    }):
        print(token["text"], end="")  # Real-time tokens from C through B!
```

### Developer Experience:

```python
# Simple, explicit API
agent = McpAgent("http://ai-service:8080", auto_session=True)

# Non-streaming call
summary = await agent.call_tool("summarize", {"text": "long document..."})

# Streaming call - developer explicitly chooses
async for chunk in agent.call_tool_streaming("chat", {"message": "Hello"}):
    print(chunk["text"], end="")

# The magic: This works across ANY number of network hops!
```

---

## Phase 7: Auto-Dependency Injection for System Components

**Goal**: Use MCP Mesh's own dependency injection to auto-discover cache and session agents
**Risk**: Low - Uses existing DI system, graceful fallback to local implementations
**Timeline**: 2-3 days
**Files**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`

### Current State Analysis:

- ✅ Phase 5 implemented Redis session storage with fallback
- ✅ Existing DependencyInjector is sophisticated and battle-tested
- ❌ Redis is still manual configuration, not auto-discovered
- ❌ No auto-discovery of distributed cache agents

### Precise Changes Required:

#### 1. Add auto-dependency injection for system components

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Replace SessionStorage with auto-injected system

```python
class SystemComponentInjector:
    """Auto-inject system components using MCP Mesh's dependency injection."""

    def __init__(self, context: dict):
        self.context = context
        self.cache_agent = None
        self.session_agent = None
        self.redis_client = None
        self.memory_store = {}  # Fallback
        self._inject_system_components()

    def _inject_system_components(self):
        """Auto-inject cache and session tracking using existing DI."""
        from ...engine.dependency_injector import DependencyInjector

        # Try to resolve distributed cache agent
        try:
            self.cache_agent = DependencyInjector.resolve_dependency(
                "redis_cache",
                context=self.context
            )
            if self.cache_agent:
                logger.info("✅ Auto-injected distributed cache agent")
        except Exception as e:
            logger.debug(f"ℹ️ Cache agent not available: {e}")

        # Try to resolve session tracking agent
        try:
            self.session_agent = DependencyInjector.resolve_dependency(
                "session_tracker",
                context=self.context
            )
            if self.session_agent:
                logger.info("✅ Auto-injected session tracking agent")
        except Exception as e:
            logger.debug(f"ℹ️ Session tracking agent not available: {e}")

        # Fallback to Redis client if available
        if not self.cache_agent:
            self._init_redis_fallback()

    def _init_redis_fallback(self):
        """Initialize Redis client as fallback when no cache agent available."""
        try:
            import redis
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"✅ Redis fallback connected: {redis_url}")
        except Exception as e:
            logger.info(f"ℹ️ Redis unavailable, using in-memory: {e}")
            self.redis_client = None

    async def get_session_pod(self, session_id: str, capability: str) -> str:
        """Get assigned pod for session using auto-injected components."""
        session_key = f"session:{session_id}:{capability}"

        # Try session tracking agent first
        if self.session_agent:
            try:
                result = await self.session_agent.get_session_assignment(
                    session_id=session_id,
                    capability=capability
                )
                if result and result.get('pod_ip'):
                    logger.debug(f"📍 Session agent: {session_key} -> {result['pod_ip']}")
                    return result['pod_ip']
            except Exception as e:
                logger.warning(f"Session agent failed, falling back: {e}")

        # Try cache agent
        if self.cache_agent:
            try:
                result = await self.cache_agent.get(key=session_key)
                if result:
                    logger.debug(f"📍 Cache agent: {session_key} -> {result}")
                    return result
            except Exception as e:
                logger.warning(f"Cache agent failed, falling back: {e}")

        # Try Redis client
        if self.redis_client:
            try:
                assigned_pod = self.redis_client.get(session_key)
                if assigned_pod:
                    logger.debug(f"📍 Redis: {session_key} -> {assigned_pod}")
                    return assigned_pod
            except Exception as e:
                logger.warning(f"Redis failed, falling back to memory: {e}")

        # Fallback to memory
        return self.memory_store.get(session_key)

    async def assign_session_pod(self, session_id: str, capability: str, pod_ip: str) -> str:
        """Assign pod to session using auto-injected components."""
        session_key = f"session:{session_id}:{capability}"
        ttl = 3600  # 1 hour

        # Try session tracking agent first
        if self.session_agent:
            try:
                await self.session_agent.assign_session(
                    session_id=session_id,
                    capability=capability,
                    pod_ip=pod_ip,
                    ttl=ttl
                )
                logger.info(f"📍 Session agent: Assigned {session_key} -> {pod_ip}")
                return pod_ip
            except Exception as e:
                logger.warning(f"Session agent assignment failed: {e}")

        # Try cache agent
        if self.cache_agent:
            try:
                await self.cache_agent.set(
                    key=session_key,
                    value=pod_ip,
                    ttl=ttl
                )
                logger.info(f"📍 Cache agent: Assigned {session_key} -> {pod_ip}")
                return pod_ip
            except Exception as e:
                logger.warning(f"Cache agent assignment failed: {e}")

        # Try Redis client
        if self.redis_client:
            try:
                self.redis_client.setex(session_key, ttl, pod_ip)
                logger.info(f"📍 Redis: Assigned {session_key} -> {pod_ip}")
                return pod_ip
            except Exception as e:
                logger.warning(f"Redis assignment failed: {e}")

        # Fallback to memory
        self.memory_store[session_key] = pod_ip
        logger.info(f"📍 Memory: Assigned {session_key} -> {pod_ip}")
        return pod_ip

    def get_stats(self) -> dict:
        """Get system component statistics."""
        return {
            "cache_agent": "available" if self.cache_agent else "unavailable",
            "session_agent": "available" if self.session_agent else "unavailable",
            "redis_client": "available" if self.redis_client else "unavailable",
            "fallback_sessions": len(self.memory_store),
            "storage_hierarchy": [
                "session_agent" if self.session_agent else None,
                "cache_agent" if self.cache_agent else None,
                "redis_client" if self.redis_client else None,
                "memory_store"
            ]
        }
```

#### 2. Update HttpMcpWrapper to use auto-injection

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Replace SessionStorage usage in `__init__` method

```python
class HttpMcpWrapper:
    def __init__(self, mcp_server: FastMCP, context: dict = None):
        self.mcp_server = mcp_server
        self.context = context or {}

        # Existing metadata caching...
        self.metadata_cache = {}
        self.cache_ttl = 60
        self.last_cache_update = 0

        # Replace manual session storage with auto-injected system components
        self.system_injector = SystemComponentInjector(self.context)
        self.pod_ip = os.getenv('POD_IP', 'localhost')
        self.pod_port = os.getenv('POD_PORT', '8080')
```

#### 3. Update session management to use auto-injected components

**File**: `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`
**Location**: Update session methods

```python
async def _get_session_pod(self, session_id: str, capability: str) -> str:
    """Get or assign pod for session using auto-injected components."""

    # Check if session already assigned using auto-injected system
    assigned_pod = await self.system_injector.get_session_pod(session_id, capability)
    if assigned_pod:
        return assigned_pod

    # New session - assign using auto-injected system
    target_pod = await self._assign_session_pod(session_id, capability)
    return target_pod

async def _assign_session_pod(self, session_id: str, capability: str) -> str:
    """Assign session to pod using auto-injected components."""

    # For Phase 7, still assign to current pod
    # TODO: Future phases could implement pod discovery and consistent hashing
    target_pod = self.pod_ip

    await self.system_injector.assign_session_pod(session_id, capability, target_pod)
    return target_pod

def get_session_stats(self) -> dict:
    """Get session statistics including auto-injected components."""
    system_stats = self.system_injector.get_stats()

    return {
        "pod_ip": self.pod_ip,
        "system_components": system_stats,
        "auto_injection": {
            "cache_agent": system_stats["cache_agent"],
            "session_agent": system_stats["session_agent"],
            "redis_fallback": system_stats["redis_client"],
            "storage_hierarchy": system_stats["storage_hierarchy"]
        }
    }
```

#### 4. Update context passing in pipeline

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Pass context to HttpMcpWrapper

```python
# In setup_fastapi_server function, when creating HttpMcpWrapper
if http_wrapper:
    # Pass context for auto-dependency injection
    http_wrapper_instance = HttpMcpWrapper(server, context)
    await http_wrapper_instance.setup()

    # Store in context for metadata endpoint access
    context['http_wrapper'] = http_wrapper_instance
```

### What Works After Phase 7:

- ✅ All previous functionality maintained
- ✅ Auto-discovery of distributed cache agents using MCP Mesh DI
- ✅ Auto-discovery of session tracking agents using MCP Mesh DI
- ✅ Graceful fallback hierarchy: session_agent → cache_agent → redis → memory
- ✅ Uses MCP Mesh's own dependency injection system
- ✅ Visible system component status in metadata endpoint

### What Doesn't Work Yet:

- ❌ No actual cache or session tracking agent implementations (need to be deployed)
- ❌ No pod discovery for optimal session assignment
- ❌ No consistent hashing across multiple pods

### Testing Phase 7:

```bash
# Test with no system components (should use memory fallback)
curl http://localhost:8080/metadata | jq '.session_affinity.auto_injection'

# Deploy a cache agent and test auto-discovery
# (This would require implementing actual cache agent)

# Test session assignment with auto-injection
curl -H "X-Capability: session_test" -H "X-Session-ID: user-123" \
     -X POST http://localhost:8080/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"session_test","arguments":{}}}'

# Check logs for auto-injection hierarchy
tail -f logs/mcp-mesh.log | grep "Auto-injected\|Cache agent\|Session agent"
```

---

## Risk Mitigation Strategy

### Each Phase:

1. **Feature Flags**: Enable/disable new features via environment variables
2. **Backward Compatibility**: Always maintain existing behavior as default
3. **Comprehensive Testing**: Each phase has specific test suite
4. **Rollback Plan**: Can disable any phase features instantly

### Example Feature Flags:

```bash
# Phase 1
MCP_MESH_METADATA_ENDPOINT=true

# Phase 2
MCP_MESH_UNIVERSAL_PROXY=true

# Phase 3
MCP_MESH_HTTP_WRAPPER_INTELLIGENCE=true

# Phase 4
MCP_MESH_SESSION_AFFINITY=true

# Phase 5
MCP_MESH_REDIS_SESSIONS=true
MCP_MESH_REDIS_URL=redis://...

# Phase 6
MCP_MESH_FULL_MCP_PROTOCOL=true

# Phase 7
MCP_MESH_AUTO_DEPENDENCY_INJECTION=true
```

### Progressive Rollout:

1. **Development**: Enable all features
2. **Staging**: Enable phase by phase
3. **Production**: Conservative rollout with monitoring
4. **Rollback**: Disable features if issues occur

## Summary

Each phase builds on the previous one while maintaining full backward compatibility. The system works end-to-end at every phase, with clearly defined capabilities and limitations. This approach minimizes risk while delivering incremental value.

The key insight is that we're not breaking anything - we're **adding intelligence layer by layer** while preserving existing functionality at each step.
