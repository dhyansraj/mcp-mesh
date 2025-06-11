# Task 16: MCP FastAPI HTTP Wrapper Integration (Updated Implementation Plan)

## Overview: Distributed MCP Agent Network Architecture

**⚠️ CRITICAL**: This task implements the revolutionary transformation of local MCP functions into distributed, network-accessible HTTP services. This is the foundational technology that enables MCP agents to run in containers/pods and communicate across network boundaries.

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `src/runtime/python/src/mcp_mesh/decorators.py` - Current mesh decorator implementation
- `src/runtime/python/src/mcp_mesh/runtime/processor.py` - Decorator processor with DI
- `src/core/registry/service.go` - Go registry with dependency resolution
- `examples/hello_world.py` - Reference implementation with DI examples

## Current Package Structure

```
mcp-mesh/
├── src/
│   ├── core/                     # Go components
│   │   ├── registry/            # Registry service
│   │   │   ├── server.go       # HTTP endpoints
│   │   │   └── service.go      # Business logic with DI resolution
│   │   └── cli/                # CLI tools
│   └── runtime/
│       └── python/
│           └── src/mcp_mesh/
│               ├── decorators.py           # @mesh_agent decorator
│               └── runtime/
│                   ├── processor.py        # Processes decorators
│                   ├── registry_client.py  # Registry communication
│                   ├── dependency_injector.py  # DI system
│                   └── http_wrapper.py     # TO BE IMPLEMENTED
```

## Registry Endpoints (Current)

```
POST /agents/register_with_metadata  # Agent registration
POST /heartbeat                      # Health monitoring + dependency resolution
GET  /agents                         # Service discovery
GET  /health                         # Registry health
GET  /capabilities                   # Capability discovery
```

## Implementation Requirements

### 16.1: Core HTTP Wrapper Implementation

**Location**: `src/runtime/python/src/mcp_mesh/runtime/http_wrapper.py`

```python
class HttpMcpWrapper:
    """Wraps MCP server with HTTP endpoints for distributed communication."""

    def __init__(self, mcp_server: FastMCP, config: HttpConfig):
        self.mcp_server = mcp_server
        self.app = FastAPI()
        self.host = config.host or "0.0.0.0"
        self.port = config.port or 0  # 0 = auto-assign
        self.actual_port = None
        self.server = None

    async def setup(self):
        """Set up HTTP endpoints and middleware."""
        # 1. Mount MCP endpoints
        mcp_app = create_app(self.mcp_server)  # From mcp.server.fastapi
        self.app.mount("/mcp", mcp_app)

        # 2. Add health endpoints for K8s
        @self.app.get("/health")
        async def health():
            return {"status": "healthy"}

        @self.app.get("/ready")
        async def ready():
            # Check if MCP server is initialized
            return {"ready": self.mcp_server.initialized}

        @self.app.get("/livez")
        async def liveness():
            return {"alive": True}

        # 3. Add mesh-specific endpoints
        @self.app.get("/mesh/info")
        async def mesh_info():
            return {
                "agent_id": self.mcp_server.name,
                "capabilities": self._get_capabilities(),
                "dependencies": self._get_dependencies(),
                "transport": ["stdio", "http"],
                "http_endpoint": f"http://{self._get_host_ip()}:{self.actual_port}"
            }

    async def start(self):
        """Start HTTP server with auto port assignment."""
        # Find available port if not specified
        if self.port == 0:
            self.actual_port = self._find_available_port()
        else:
            self.actual_port = self.port

        # Configure uvicorn
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.actual_port,
            log_level="info"
        )
        self.server = uvicorn.Server(config)

        # Start in background task
        asyncio.create_task(self.server.serve())

        # Register with mesh registry
        await self._register_http_endpoint()
```

### 16.2: Runtime Processor Integration

**Update**: `src/runtime/python/src/mcp_mesh/runtime/processor.py`

```python
class MeshAgentProcessor:
    async def process_single_agent(self, func_name: str, decorated_func: DecoratedFunction) -> bool:
        # ... existing registration code ...

        # NEW: Check if HTTP is enabled
        if self._should_enable_http(metadata):
            await self._setup_http_wrapper(func_name, decorated_func)

    def _should_enable_http(self, metadata: dict) -> bool:
        """Determine if HTTP wrapper should be enabled."""
        # Explicit enable
        if metadata.get("enable_http"):
            return True

        # Auto-detect container environment
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            return True

        if os.environ.get("MCP_MESH_HTTP_ENABLED", "").lower() == "true":
            return True

        return False

    async def _setup_http_wrapper(self, func_name: str, decorated_func: DecoratedFunction):
        """Set up HTTP wrapper for the function."""
        # Get or create MCP server
        mcp_server = self._get_mcp_server_for_function(decorated_func)

        # Create HTTP wrapper
        config = HttpConfig(
            host=metadata.get("http_host", "0.0.0.0"),
            port=metadata.get("http_port", 0)
        )
        wrapper = HttpMcpWrapper(mcp_server, config)

        # Start HTTP server
        await wrapper.setup()
        await wrapper.start()

        # Store wrapper for lifecycle management
        self._http_wrappers[func_name] = wrapper

        # Update registration with HTTP endpoint
        self._update_registration_with_http(func_name, wrapper.get_endpoint())
```

### 16.3: Dependency Injection with HTTP Clients

**Update**: `src/runtime/python/src/mcp_mesh/runtime/processor.py`

```python
async def _setup_dependency_injection(self, decorated_func: DecoratedFunction, registry_response: dict):
    """Enhanced DI with HTTP client support."""
    # ... existing code ...

    for dep_name in dependencies:
        dep_info = dependencies_resolved.get(dep_name)

        if dep_info and dep_info.get("endpoint", "").startswith("http"):
            # Create HTTP-based MCP client proxy
            proxy = await self._create_http_proxy(dep_name, dep_info)
        else:
            # Create local proxy (existing code)
            proxy = self._create_local_proxy(dep_name, dep_info)

async def _create_http_proxy(self, dep_name: str, dep_info: dict):
    """Create proxy that calls remote HTTP endpoint."""
    from mcp.client.session import ClientSession
    from mcp.client.http import http_client

    class HttpProxy:
        def __init__(self, endpoint: str, agent_id: str):
            self.endpoint = endpoint
            self.agent_id = agent_id
            self._client = None

        async def _ensure_client(self):
            if not self._client:
                # Create HTTP client to remote MCP server
                self._client = await http_client(
                    url=f"{self.endpoint}/mcp",
                    headers={"X-Agent-Id": self.agent_id}
                )

        async def __getattr__(self, name: str):
            """Proxy method calls to remote server."""
            await self._ensure_client()

            async def method_proxy(**kwargs):
                # Call remote tool via MCP protocol
                result = await self._client.call_tool(name, kwargs)
                return result.content[0].text

            return method_proxy

    return HttpProxy(dep_info["endpoint"], dep_info["agent_id"])
```

### 16.4: Registry Updates for HTTP Endpoints

**Update**: `src/core/registry/service.go`

```go
// Enhanced registration to store HTTP endpoints
func (s *Service) handleRegisterWithMetadata(c *gin.Context) {
    // ... existing validation ...

    // Extract HTTP endpoint if provided
    httpEndpoint := ""
    if endpoint, ok := metadata["endpoint"].(string); ok {
        if strings.HasPrefix(endpoint, "http://") || strings.HasPrefix(endpoint, "https://") {
            httpEndpoint = endpoint
        }
    }

    // Store both stdio and HTTP endpoints
    agent.Endpoints = map[string]string{
        "stdio": agent.Endpoint,  // Original stdio endpoint
        "http":  httpEndpoint,    // HTTP endpoint if available
    }

    // ... rest of registration ...
}

// Enhanced dependency resolution to prefer HTTP endpoints
func (s *Service) resolveDependencies(agentID string, dependencies []string) (map[string]*DependencyResolution, error) {
    // ... existing query ...

    // Prefer HTTP endpoint for cross-container communication
    endpoint := depAgent.Endpoints["http"]
    if endpoint == "" {
        endpoint = depAgent.Endpoints["stdio"]
    }

    resolved[dep] = &DependencyResolution{
        AgentID:  depAgent.ID,
        Endpoint: endpoint,
        Status:   depAgent.Status,
        Transport: detectTransport(endpoint),  // "http" or "stdio"
    }
}
```

### 16.5: Container and Kubernetes Support

**New file**: `examples/Dockerfile.mcp-agent`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy agent code
COPY . .

# Environment variables for HTTP mode
ENV MCP_MESH_HTTP_ENABLED=true
ENV MCP_MESH_REGISTRY_URL=http://mcp-mesh-registry:8000

# Run with mcp-mesh-dev (which handles HTTP setup)
CMD ["python", "-m", "mcp_mesh_dev", "start", "my_agent.py"]
```

**New file**: `examples/k8s/hello-world-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello-world-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: hello-world
  template:
    metadata:
      labels:
        app: hello-world
        mesh-agent: "true"
    spec:
      containers:
        - name: agent
          image: mcp-mesh/hello-world:latest
          env:
            - name: MCP_MESH_HTTP_ENABLED
              value: "true"
            - name: MCP_MESH_REGISTRY_URL
              value: "http://mcp-mesh-registry:8000"
          ports:
            - containerPort: 8080
              name: http
          livenessProbe:
            httpGet:
              path: /livez
              port: http
          readinessProbe:
            httpGet:
              path: /ready
              port: http
---
apiVersion: v1
kind: Service
metadata:
  name: hello-world-service
spec:
  selector:
    app: hello-world
  ports:
    - port: 80
      targetPort: http
  type: LoadBalancer
```

### 16.6: Testing and Validation

**New test**: `tests/integration/test_http_wrapper_e2e.py`

```python
async def test_http_wrapper_cross_container():
    """Test cross-container communication via HTTP."""
    # Start system agent with HTTP
    system_agent = await start_agent_with_http("examples/system_agent.py", port=8081)

    # Start hello world with dependency on system agent
    hello_world = await start_agent_with_http("examples/hello_world.py", port=8082)

    # Wait for registration and DI setup
    await asyncio.sleep(2)

    # Call hello world function via HTTP
    async with aiohttp.ClientSession() as session:
        # Call the MCP endpoint
        result = await session.post(
            "http://localhost:8082/mcp",
            json={
                "method": "tools/call",
                "params": {
                    "name": "greet_from_mcp_mesh",
                    "arguments": {}
                }
            }
        )

        response = await result.json()
        # Should include date from SystemAgent via HTTP proxy
        assert "current date" in response["content"]
```

## Success Criteria

### Phase 1: Local HTTP Mode

- [ ] HTTP wrapper starts when `enable_http=True`
- [ ] Functions accessible at `http://localhost:port/mcp`
- [ ] Health endpoints work (`/health`, `/ready`, `/livez`)
- [ ] Registry shows correct HTTP endpoints

### Phase 2: Cross-Process Communication

- [ ] HTTP proxy created for dependencies with HTTP endpoints
- [ ] Successful calls between processes via HTTP
- [ ] Error handling for network failures
- [ ] Proper connection pooling

### Phase 3: Container/K8s Deployment

- [ ] Auto-detect container environment
- [ ] Agents work in Docker containers
- [ ] K8s deployments with service discovery
- [ ] Load balancing across replicas
- [ ] Graceful shutdown on SIGTERM

## Implementation Order

1. **Core HTTP Wrapper** (Phase 1)

   - Basic HttpMcpWrapper class
   - Integration with processor
   - Local testing

2. **HTTP Client Proxies** (Phase 2)

   - HTTP-based proxy implementation
   - Update dependency injection
   - Cross-process testing

3. **Container Support** (Phase 3)
   - Environment detection
   - Docker examples
   - K8s manifests
   - Production testing

This implementation will finally enable true distributed MCP agents, solving the fundamental limitation of stdio-only communication!
