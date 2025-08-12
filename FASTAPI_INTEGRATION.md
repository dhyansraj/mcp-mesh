# FastAPI Integration for MCP Mesh

## Overview

This document outlines the implementation plan for extending MCP Mesh's dependency injection system to FastAPI route handlers. The goal is to provide the same elegant dependency injection experience for backend services that agents currently enjoy, eliminating boilerplate MCP client code.

## Registry Changes Required

### Service Type Classification

The registry must support two distinct service types:

- **"agent"** (default): Full MCP agents that provide capabilities - existing behavior
- **"api"**: FastAPI services that consume capabilities but don't register as agents

### Critical Topology Management

**API Services Must NOT Trigger Topology Changes:**

- APIs registering/unregistering do **not** cause topology change notifications to agents
- APIs going healthy/unhealthy do **not** cause topology change notifications to agents
- Registry continues tracking API health using same logic as agents (for dependency resolution)
- Only agent registration/unregistration/health changes trigger topology notifications

**Implementation Details:**

```json
// Heartbeat payload
{
  "service_type": "api", // Optional field, defaults to "agent"
  "agent_id": "api-service-xyz",
  "dependencies": ["pdf-extractor", "user-service"]
  // ... other fields
}
```

**Why This Matters:**

- Agents rely on topology change events to refresh their dependency connections
- API services coming/going shouldn't disrupt agent-to-agent connectivity
- APIs are "consumers" of capabilities, not "providers" in the mesh topology
- Maintains stability of the agent mesh while allowing API services to discover dependencies

## Current State vs Vision

### Current Backend Pattern (Boilerplate Heavy)

```python
# Current: Manual MCP client management
@router.post("/user/upload-resume")
async def upload_user_resume(request: Request, file: UploadFile = File(...)):
    user_data = request.state.user

    # Manual service instantiation and URL management
    file_service = FileService()
    mcp_client = MCPClient()

    # Manual MCP JSON-RPC calls with error handling
    result = await mcp_client.call_pdf_extractor(file_path, file_content)

    # Manual user data updates
    AuthService.update_user_data(user_email, result["resume_data"])
    return {"success": True}
```

### Vision: Clean Dependency Injection

```python
# Vision: Clean dependency injection like agents
@router.post("/user/upload-resume")
@mesh.route(dependencies=["pdf-extractor", "user-service"])
async def upload_user_resume(
    request: Request,
    file: UploadFile = File(...),        # FastAPI resolves
    pdf_agent: McpAgent = None,          # MCP Mesh injects
    user_service: McpAgent = None        # MCP Mesh injects
):
    user_data = request.state.user

    # Direct agent calls with automatic service discovery
    result = await pdf_agent.extract_text_from_pdf(
        file_path=minio_url,
        extraction_method="auto"
    )

    await user_service.update_profile(user_data['email'], result)
    return {"success": True}
```

## Core Implementation Strategy

### 1. Leverage Optional Parameters

FastAPI supports optional parameters with defaults, which is the key to making this work:

```python
async def handler(required_param: str, optional_agent: McpAgent = None):
    pass

# FastAPI calls: handler(required_param="value", optional_agent=None)
# Our proxy intercepts and replaces None with injected dependency
```

### 2. Proxy Hijacking Mechanism

Use the same function pointer replacement pattern as FastMCP:

**FastMCP (Current)**:

```python
# Discovery: tool.fn = original_function
# Replacement: tool.fn = dependency_wrapper
# When MCP call comes in, FastMCP calls tool.fn (which is now our proxy)
```

**FastAPI (New)**:

```python
# Discovery: route.endpoint = original_handler
# Replacement: route.endpoint = dependency_wrapper
# When HTTP request comes in, FastAPI calls route.endpoint (which is now our proxy)
```

### 3. Same Proxy Logic

The dependency injection wrapper logic remains identical:

```python
def dependency_wrapper(*args, **kwargs):
    # Replace None values with injected dependencies
    for param_name, param_value in kwargs.items():
        if param_value is None and param_name in dependency_map:
            kwargs[param_name] = get_dependency(dependency_map[param_name])

    return original_function(*args, **kwargs)
```

## Technical Architecture

### Pipeline Integration

Extend the existing startup pipeline with new steps:

```
Current Pipeline:
1. decorator_collection.py      ← Collect @mesh.tool decorators
2. fastmcpserver_discovery.py  ← Find FastMCP instances
3. fastapiserver_setup.py      ← Create FastAPI + mount FastMCP

New Pipeline Addition:
1. decorator_collection.py      ← Collect @mesh.tool AND @mesh.route decorators
2. fastmcpserver_discovery.py  ← Find FastMCP instances
3. fastapiapp_discovery.py     ← Find user's FastAPI instances (NEW)
4. fastapiserver_setup.py      ← Integrate with user FastAPI OR create new one
```

### New Components

#### 1. FastAPI App Discovery (`fastapiapp_discovery.py`)

```python
class FastAPIAppDiscoveryStep(PipelineStep):
    def _discover_fastapi_instances(self):
        # Scan global namespace for FastAPI instances
        # Extract route handlers from app.router.routes
        # Store original handler functions with metadata
        # Return discovered FastAPI apps and their routes
```

#### 2. FastAPI Integration Decorator

```python
# In mesh/__init__.py
def route(**kwargs):
    """FastAPI route handler dependency injection decorator."""
    dependencies = kwargs.get('dependencies', [])

    def decorator(func):
        # Mark function for discovery
        func._mesh_route_dependencies = dependencies
        func._mesh_route_kwargs = kwargs
        return func

    return decorator
```

#### 3. Route Handler Replacement

```python
# Extend dependency_injector.py
def register_fastapi_handler(self, route, handler, dependencies):
    # Create dependency wrapper (same as FastMCP)
    dependency_wrapper = self._create_dependency_wrapper(handler, dependencies)

    # Replace FastAPI's route handler pointer
    route.endpoint = dependency_wrapper

    # Register for dependency updates
    self._function_registry[handler_id] = dependency_wrapper
```

### Lifecycle Management

#### User FastAPI Integration

When user declares their own FastAPI instance:

```python
# User's main.py
from fastapi import FastAPI
import mesh

app = FastAPI()  # User controls this

@app.post("/upload")
@mesh.route(dependencies=["pdf-extractor"])
async def upload(request, file, pdf_agent=None):
    return await pdf_agent.process(file)

# User runs: uvicorn main:app
```

**Lifespan Integration Strategy**:

```python
# Inject MCP Mesh lifespan into user's FastAPI
@asynccontextmanager
async def mesh_lifespan_wrapper(app):
    # Start MCP Mesh background tasks (heartbeat, registry connection)
    mesh_tasks = await start_mesh_background_tasks()

    # Call user's existing lifespan if present
    if original_lifespan:
        async with original_lifespan(app):
            yield
    else:
        yield

    # Cleanup MCP Mesh tasks
    await cleanup_mesh_background_tasks(mesh_tasks)

# Replace user's FastAPI lifespan
user_app.router.lifespan = mesh_lifespan_wrapper
```

#### MCP Mesh Controlled FastAPI (Current Behavior)

When no user FastAPI found, continue current behavior:

- Create MCP Mesh FastAPI server
- Mount discovered FastMCP instances
- Control entire lifecycle

## Implementation Components

### File Structure

```
src/runtime/python/_mcp_mesh/
├── pipeline/startup/
│   ├── fastapiapp_discovery.py      (NEW)
│   ├── fastmcpserver_discovery.py   (EXISTS)
│   └── fastapiserver_setup.py       (EXTEND)
├── engine/
│   ├── dependency_injector.py       (EXTEND)
│   └── fastapi_integration.py       (NEW)
└── decorators.py                    (EXTEND - add @mesh.route)
```

### Key Implementation Points

#### 1. Route Discovery

```python
def _extract_fastapi_routes(app):
    """Extract route handlers from FastAPI instance."""
    discovered_routes = {}

    for route in app.router.routes:
        if hasattr(route, 'endpoint') and hasattr(route.endpoint, '_mesh_route_dependencies'):
            route_info = {
                'handler': route.endpoint,
                'dependencies': route.endpoint._mesh_route_dependencies,
                'path': route.path,
                'methods': route.methods
            }
            discovered_routes[route.path] = route_info

    return discovered_routes
```

#### 2. Handler Replacement

```python
def _replace_route_handlers(app, routes_info):
    """Replace route handlers with dependency-injecting proxies."""
    for route in app.router.routes:
        if route.path in routes_info:
            original_handler = route.endpoint
            route_info = routes_info[route.path]

            # Create proxy with same mechanism as FastMCP
            proxy_handler = create_dependency_wrapper(
                original_handler,
                route_info['dependencies']
            )

            # Replace the handler pointer
            route.endpoint = proxy_handler
```

#### 3. Service Discovery Integration

Reuse existing registry client and service discovery:

```python
# Same dependency resolution as agents
dependency_instance = await registry_client.resolve_capability("pdf-extractor")
proxy_client = create_mcp_client_proxy(dependency_instance)
```

## Benefits

### For Developers

- **Consistent Patterns**: Same dependency injection as agents
- **Reduced Boilerplate**: Eliminates manual MCP client code
- **Type Safety**: Full IDE support and autocompletion
- **Easy Testing**: Simple mocking of injected agents
- **Service Discovery**: Automatic agent resolution

### For Architecture

- **Unified Patterns**: Backend and agents use identical approaches
- **Maintainability**: Single dependency injection system
- **Scalability**: Automatic load balancing and failover
- **Observability**: Integrated tracing and monitoring
- **Configuration**: Centralized service configuration

### Compatibility

- **Existing Agents**: No changes required
- **FastMCP Integration**: Continues to work as before
- **User FastAPI**: Integrates seamlessly with existing apps
- **Docker/Kubernetes**: Same deployment patterns
- **Development Workflow**: No changes to existing processes

## Migration Path

### Phase 1: Core Implementation

1. Implement FastAPI app discovery
2. Extend dependency injector for route handlers
3. Add `@mesh.route()` decorator
4. Basic lifespan integration

### Phase 2: Advanced Features

1. Enhanced proxy configuration (timeouts, retries)
2. Session affinity for stateful operations
3. Advanced routing and load balancing
4. Comprehensive error handling

### Phase 3: Developer Experience

1. IDE plugins and tooling
2. Enhanced debugging and tracing
3. Performance monitoring and metrics
4. Documentation and examples

## Conclusion

This implementation extends MCP Mesh's elegant dependency injection to FastAPI using the same proven patterns that work seamlessly with FastMCP. By leveraging optional parameters and function pointer replacement, we can provide a clean, type-safe developer experience while eliminating boilerplate backend code.

The key insight is that FastAPI's optional parameter handling allows our proxy hijacking mechanism to work transparently - FastAPI calls our proxy with `None` values, and we replace them with injected dependencies before calling the original handler.

This creates a unified development experience where both agents and backend services use identical dependency injection patterns, significantly reducing complexity and improving maintainability.

The `@mesh.route()` decorator name aligns with FastAPI's route-centric paradigm while clearly indicating MCP Mesh integration.
