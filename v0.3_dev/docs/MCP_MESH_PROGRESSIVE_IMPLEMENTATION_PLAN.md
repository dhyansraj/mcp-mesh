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

## Phase 1: OpenAPI Schema and Client Generation for kwargs Support

**Goal**: Update OpenAPI specification and regenerate Python clients to support kwargs in heartbeat registration
**Risk**: Low - Schema-only changes, backward compatible (new optional fields)
**Timeline**: 1-2 days
**Files**: OpenAPI spec, Python generated models, Go generated types

### Current State Analysis:

- ✅ `@mesh.tool` decorator already supports kwargs in Python
- ✅ kwargs stored in local metadata during tool registration
- ❌ OpenAPI schema doesn't include kwargs/additional_properties fields
- ❌ Python client models can't send kwargs in heartbeat
- ❌ Go registry can't receive kwargs in heartbeat

### TDD Approach - Update Schema First:

#### 1. Update OpenAPI specification to support kwargs

**File**: `src/core/registry/docs/openapi.yaml`
**Location**: Update MeshToolRegistration model

```yaml
MeshToolRegistration:
  type: object
  required:
    - function_name
    - capability
  properties:
    function_name:
      type: string
      minLength: 1
      description: Name of the decorated function
    capability:
      type: string
      minLength: 1
      description: Capability provided by this function
    version:
      type: string
      default: "1.0.0"
      description: Function/capability version
    tags:
      type: array
      items:
        type: string
      description: Tags for this capability
    dependencies:
      type: array
      items:
        $ref: "#/components/schemas/MeshToolDependencyRegistration"
      description: Dependencies required by this function
    description:
      type: string
      description: Function description
  # NEW: Enable additional properties for kwargs
  additionalProperties: true
  example:
    function_name: "enhanced_tool"
    capability: "data_processing"
    version: "1.0.0"
    description: "Process data with enhanced features"
    timeout: 45
    retry_count: 3
    streaming: true
    custom_headers:
      X-API-Version: "v2"

# Also update dependency resolution response to include kwargs
DependencyResolution:
  type: object
  properties:
    capability:
      type: string
    endpoint:
      type: string
    function_name:
      type: string
    status:
      type: string
    agent_id:
      type: string
  # NEW: Enable additional properties for kwargs in responses
  additionalProperties: true
  description: |
    Dependency resolution information including any custom kwargs
    from the original tool registration
  example:
    capability: "data_processing"
    endpoint: "http://service:8080"
    function_name: "enhanced_tool"
    status: "available"
    agent_id: "data-service-123"
    timeout: 45
    retry_count: 3
    streaming: true
```

#### 2. Regenerate Python client models

**Command**: Generate updated Python models with kwargs support

```bash
# Regenerate Python models from updated OpenAPI spec
cd src/core/registry
openapi-generator generate \
  -i docs/openapi.yaml \
  -g python \
  -o ../../runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/ \
  --additional-properties=packageName=mcp_mesh_registry_client \
  --enable-post-process-file
```

#### 3. Verify generated models support kwargs

**File**: `src/runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/models/mesh_tool_registration.py`
**Expected**: Model should now accept additional properties

```python
# Generated model should now support:
tool_reg = MeshToolRegistration(
    function_name="test_function",
    capability="test_capability",
    # Standard fields
    version="1.0.0",
    tags=["tag1"],
    description="Test tool",
    # NEW: kwargs as additional properties
    timeout=45,
    retry_count=3,
    streaming=True,
    custom_headers={"X-Version": "v2"}
)
```

#### 4. Write test to verify kwargs support in models

**File**: `src/runtime/python/tests/unit/test_01_openapi_kwargs_support.py`

```python
import pytest
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import MeshToolRegistration

class TestOpenAPIKwargsSupport:
    """Test that generated models support kwargs via additionalProperties."""

    def test_mesh_tool_registration_accepts_kwargs(self):
        """Test MeshToolRegistration accepts additional properties."""
        # Standard required fields
        tool_reg = MeshToolRegistration(
            function_name="test_function",
            capability="test_capability"
        )

        # Should be able to set additional properties (kwargs)
        tool_reg.timeout = 45
        tool_reg.retry_count = 3
        tool_reg.streaming = True
        tool_reg.custom_headers = {"X-API-Version": "v2"}

        # Convert to dict to verify additional properties are preserved
        tool_dict = tool_reg.to_dict()

        assert tool_dict["function_name"] == "test_function"
        assert tool_dict["capability"] == "test_capability"
        assert tool_dict["timeout"] == 45
        assert tool_dict["retry_count"] == 3
        assert tool_dict["streaming"] is True
        assert tool_dict["custom_headers"]["X-API-Version"] == "v2"

    def test_mesh_tool_registration_from_dict_with_kwargs(self):
        """Test creating MeshToolRegistration from dict with kwargs."""
        tool_data = {
            "function_name": "enhanced_function",
            "capability": "enhanced_capability",
            "version": "1.0.0",
            "description": "Enhanced tool with kwargs",
            # Additional properties (kwargs)
            "timeout": 60,
            "retry_count": 5,
            "auth_required": True,
            "custom_config": {"setting1": "value1", "setting2": "value2"}
        }

        tool_reg = MeshToolRegistration.from_dict(tool_data)

        # Standard fields
        assert tool_reg.function_name == "enhanced_function"
        assert tool_reg.capability == "enhanced_capability"

        # Additional properties should be accessible
        assert hasattr(tool_reg, 'timeout') or 'timeout' in tool_reg.to_dict()
        assert hasattr(tool_reg, 'auth_required') or 'auth_required' in tool_reg.to_dict()

    def test_backwards_compatibility_without_kwargs(self):
        """Test that tools without kwargs continue to work."""
        tool_reg = MeshToolRegistration(
            function_name="simple_function",
            capability="simple_capability",
            version="1.0.0"
        )

        tool_dict = tool_reg.to_dict()

        assert tool_dict["function_name"] == "simple_function"
        assert tool_dict["capability"] == "simple_capability"
        assert tool_dict["version"] == "1.0.0"

        # Should not have any additional properties
        expected_keys = {"function_name", "capability", "version"}
        extra_keys = set(tool_dict.keys()) - expected_keys
        # Only expected additional keys are None/empty values
        assert all(tool_dict[key] in [None, [], {}] for key in extra_keys)
```

### What Phase 1 Accomplishes:

- ✅ **OpenAPI schema updated**: MeshToolRegistration supports additionalProperties
- ✅ **Python models regenerated**: Generated classes can handle kwargs
- ✅ **Backward compatibility**: Tools without kwargs continue working
- ✅ **Foundation for Phase 2**: Python can now send kwargs in heartbeat
- ✅ **TDD validation**: Tests verify kwargs support in generated models

### What Doesn't Work Yet:

- ❌ Python heartbeat doesn't use kwargs yet (Phase 2)
- ❌ Go registry doesn't handle kwargs (Phase 2)
- ❌ Registry doesn't store kwargs (Phase 7)
- ❌ Enhanced client proxies don't exist (Phase 9)

### Testing Phase 1:

```bash
# Test 1: Validate OpenAPI spec
cd src/core/registry
swagger-codegen validate -i docs/openapi.yaml

# Test 2: Regenerate Python models
openapi-generator generate -i docs/openapi.yaml -g python -o generated/

# Test 3: Test generated models
python -m pytest src/runtime/python/tests/unit/test_01_openapi_kwargs_support.py

# Test 4: Verify additionalProperties support
python3 -c "
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import MeshToolRegistration
tool = MeshToolRegistration(function_name='test', capability='test')
tool.timeout = 45  # This should work with additionalProperties
print('✅ additionalProperties supported')
"
```

### Phase 1 → Phase 2 Connection:

**Phase 1** creates the OpenAPI foundation for kwargs. **Phase 2** can then use the updated models:

```python
# Phase 2 will be able to do this:
tool_reg = MeshToolRegistration(
    function_name="enhanced_tool",
    capability="data_processing",
    timeout=45,           # ✅ Now supported via additionalProperties
    retry_count=3,        # ✅ Now supported
    streaming=True        # ✅ Now supported
)
```

#### 2. Add metadata endpoint for local introspection (optional but helpful)

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Add after health endpoints

```python
@app.get("/metadata")
async def get_routing_metadata():
    """Get routing metadata for all capabilities on this agent."""
    from ...engine.decorator_registry import DecoratorRegistry
    from datetime import datetime

    capabilities_metadata = {}

    try:
        registered_tools = DecoratorRegistry.get_all_mesh_tools()

        for func_name, decorated_func in registered_tools.items():
            metadata = decorated_func.metadata
            capability_name = metadata.get('capability', func_name)

            # Extract kwargs for metadata endpoint
            standard_fields = {
                'capability', 'function_name', 'version', 'tags',
                'description', 'dependencies'
            }
            kwargs_dict = {
                k: v for k, v in metadata.items()
                if k not in standard_fields and not k.startswith('_')
            }

            capabilities_metadata[capability_name] = {
                "function_name": func_name,
                "capability": capability_name,
                "version": metadata.get('version', '1.0.0'),
                "tags": metadata.get('tags', []),
                "description": metadata.get('description', ''),
                # Include kwargs for routing intelligence
                **kwargs_dict
            }
    except Exception as e:
        logger.warning(f"Failed to get mesh tools metadata: {e}")
        capabilities_metadata = {}

    return {
        "agent_id": context.get('agent_config', {}).get('agent_id', 'unknown'),
        "capabilities": capabilities_metadata,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy"
    }
```

### What Phase 1 Accomplishes:

- ✅ **Heartbeat kwargs flow**: Python agents send kwargs to registry during heartbeat
- ✅ **Registry receives kwargs**: Foundation for storing tool configuration metadata
- ✅ **Metadata endpoint**: Local introspection of tool kwargs configuration
- ✅ **Backward compatibility**: Tools without kwargs continue working normally
- ✅ **Foundation for DI**: Sets up kwargs to flow to other agents' dependency injection

### What Doesn't Work Yet (waiting for Phase 7-8):

- ❌ Registry doesn't store kwargs (needs database schema changes)
- ❌ Dependency resolution responses don't include kwargs
- ❌ Enhanced client proxies don't exist

### Testing Phase 1:

```python
# Test 1: Verify kwargs in heartbeat registration
@mesh.tool(
    capability="test_capability",
    timeout=30,
    retry_count=3,
    streaming=True,
    custom_priority="high"
)
def test_function():
    return "test"

# Check that kwargs are included in heartbeat
# (Will be visible in registry logs when Phase 7 is implemented)

# Test 2: Verify metadata endpoint shows kwargs
curl http://localhost:8080/metadata

# Expected response:
{
  "agent_id": "agent-123",
  "capabilities": {
    "test_capability": {
      "function_name": "test_function",
      "capability": "test_capability",
      "timeout": 30,
      "retry_count": 3,
      "streaming": true,
      "custom_priority": "high"
    }
  },
  "timestamp": "2025-07-04T12:00:00.000Z",
  "status": "healthy"
}

# Test 3: Verify backward compatibility
@mesh.tool(capability="simple_capability")  # No kwargs
def simple_function():
    return "simple"

# Should work without any kwargs
curl http://localhost:8080/metadata | jq '.capabilities.simple_capability'
```

### Phase 1 → Phase 7-9 Connection:

**Phase 1** establishes the flow of kwargs from tools to heartbeat registration. **Phases 7-9** complete the cycle:

1. **Phase 7**: Registry stores kwargs in database
2. **Phase 8**: Registry returns kwargs in dependency resolution responses
3. **Phase 9**: Client proxies auto-configure from received kwargs

This creates the complete **declarative configuration loop**:

```
@mesh.tool(timeout=45) → Heartbeat → Registry Storage → Dependency Resolution → Enhanced Proxy
```

---

## Phase 2: Heartbeat Enhancement for kwargs Registration

**Goal**: Enhance `/heartbeat` endpoint to register and distribute kwargs information using updated OpenAPI models
**Risk**: Low - Extends existing heartbeat flow, uses Phase 1 foundation
**Timeline**: 2-3 days
**Files**: `src/runtime/python/_mcp_mesh/shared/registry_client_wrapper.py`, Go registry heartbeat handler

### Current State Analysis (Post-Phase 1):

- ✅ OpenAPI schema supports additionalProperties for kwargs
- ✅ Python models regenerated to handle kwargs
- ✅ `@mesh.tool` decorator already supports kwargs in Python
- ✅ kwargs stored in local metadata during tool registration
- ❌ Heartbeat doesn't send kwargs to registry
- ❌ Go registry doesn't handle kwargs in heartbeat
- ❌ Dependency resolution responses don't include kwargs

### Precise Changes Required:

#### 1. Update Python heartbeat registration to include kwargs

**File**: `src/runtime/python/_mcp_mesh/shared/registry_client_wrapper.py`
**Location**: Update `create_mesh_agent_registration` method (around line 280)

```python
def create_mesh_agent_registration(self, health_status) -> MeshAgentRegistration:
    """Create mesh agent registration with kwargs for heartbeat."""

    tools = []
    decorators = DecoratorRegistry.get_all_mesh_tools()

    for func_name, decorated_func in decorators.items():
        metadata = decorated_func.metadata

        # Extract standard MCP fields
        standard_fields = {
            'capability', 'function_name', 'version', 'tags',
            'description', 'dependencies'
        }

        # NEW: Extract kwargs (everything else) for registry storage
        kwargs_dict = {
            k: v for k, v in metadata.items()
            if k not in standard_fields and not k.startswith('_')
        }

        # Convert dependencies to registry format
        dep_registrations = []
        for dep in metadata.get("dependencies", []):
            dep_reg = MeshToolDependencyRegistration(
                capability=dep["capability"],
                tags=dep.get("tags", []),
                version=dep.get("version"),
                namespace=dep.get("namespace", "default"),
            )
            dep_registrations.append(dep_reg)

        # Create tool registration with kwargs for heartbeat
        # Now possible thanks to Phase 1 additionalProperties support
        tool_reg = MeshToolRegistration(
            function_name=func_name,
            capability=metadata.get("capability"),
            tags=metadata.get("tags", []),
            version=metadata.get("version", "1.0.0"),
            dependencies=dep_registrations,
            description=metadata.get("description"),
        )

        # NEW: Set kwargs as additional properties (Phase 1 made this possible)
        for key, value in kwargs_dict.items():
            setattr(tool_reg, key, value)

        tools.append(tool_reg)

        self.logger.debug(f"🔧 Tool '{func_name}' heartbeat includes kwargs: {kwargs_dict}")

    # Rest of method unchanged...
    return MeshAgentRegistration(...)
```

#### 2. Add metadata endpoint for local introspection

**File**: `src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py`
**Location**: Add after health endpoints

```python
@app.get("/metadata")
async def get_routing_metadata():
    """Get routing metadata for all capabilities on this agent."""
    from ...engine.decorator_registry import DecoratorRegistry
    from datetime import datetime

    capabilities_metadata = {}

    try:
        registered_tools = DecoratorRegistry.get_all_mesh_tools()

        for func_name, decorated_func in registered_tools.items():
            metadata = decorated_func.metadata
            capability_name = metadata.get('capability', func_name)

            # Extract kwargs for metadata endpoint
            standard_fields = {
                'capability', 'function_name', 'version', 'tags',
                'description', 'dependencies'
            }
            kwargs_dict = {
                k: v for k, v in metadata.items()
                if k not in standard_fields and not k.startswith('_')
            }

            capabilities_metadata[capability_name] = {
                "function_name": func_name,
                "capability": capability_name,
                "version": metadata.get('version', '1.0.0'),
                "tags": metadata.get('tags', []),
                "description": metadata.get('description', ''),
                # Include kwargs for routing intelligence
                **kwargs_dict
            }
    except Exception as e:
        logger.warning(f"Failed to get mesh tools metadata: {e}")
        capabilities_metadata = {}

    return {
        "agent_id": context.get('agent_config', {}).get('agent_id', 'unknown'),
        "capabilities": capabilities_metadata,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy"
    }
```

#### 3. Write test for heartbeat kwargs integration

**File**: `src/runtime/python/tests/unit/test_02_heartbeat_kwargs_integration.py`

```python
import pytest
from unittest.mock import patch, MagicMock

from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import MeshToolRegistration

class TestHeartbeatKwargsIntegration:
    """Test kwargs integration in heartbeat registration."""

    def test_heartbeat_includes_kwargs_from_decorator(self):
        """Test that heartbeat registration includes kwargs from @mesh.tool."""

        # Mock decorator registry with tool that has kwargs
        mock_decorated_func = MagicMock()
        mock_decorated_func.metadata = {
            "capability": "enhanced_service",
            "function_name": "enhanced_function",
            "version": "1.0.0",
            "description": "Enhanced function with kwargs",
            # kwargs that should be included
            "timeout": 45,
            "retry_count": 3,
            "streaming": True,
            "custom_headers": {"X-API-Version": "v2"}
        }

        with patch.object(DecoratorRegistry, 'get_all_mesh_tools') as mock_get_tools:
            mock_get_tools.return_value = {
                "enhanced_function": mock_decorated_func
            }

            wrapper = RegistryClientWrapper("http://registry:8080")

            # Mock health status
            mock_health_status = MagicMock()
            mock_health_status.agent_name = "test-agent"
            mock_health_status.version = "1.0.0"
            mock_health_status.timestamp = "2025-07-04T12:00:00Z"
            mock_health_status.metadata = {
                "http_host": "localhost",
                "http_port": 8080,
                "namespace": "default"
            }

            # Create registration
            registration = wrapper.create_mesh_agent_registration(mock_health_status)

            # Verify tool includes kwargs
            assert len(registration.tools) == 1
            tool_reg = registration.tools[0]

            # Standard fields
            assert tool_reg.function_name == "enhanced_function"
            assert tool_reg.capability == "enhanced_service"

            # Kwargs should be set as additional properties
            tool_dict = tool_reg.to_dict()
            assert tool_dict["timeout"] == 45
            assert tool_dict["retry_count"] == 3
            assert tool_dict["streaming"] is True
            assert tool_dict["custom_headers"]["X-API-Version"] == "v2"

    def test_heartbeat_backward_compatibility_no_kwargs(self):
        """Test that heartbeat works for tools without kwargs."""

        # Mock decorator registry with simple tool (no kwargs)
        mock_decorated_func = MagicMock()
        mock_decorated_func.metadata = {
            "capability": "simple_service",
            "function_name": "simple_function",
            "version": "1.0.0",
            "description": "Simple function without kwargs"
        }

        with patch.object(DecoratorRegistry, 'get_all_mesh_tools') as mock_get_tools:
            mock_get_tools.return_value = {
                "simple_function": mock_decorated_func
            }

            wrapper = RegistryClientWrapper("http://registry:8080")
            mock_health_status = MagicMock()
            mock_health_status.agent_name = "test-agent"
            mock_health_status.version = "1.0.0"
            mock_health_status.timestamp = "2025-07-04T12:00:00Z"
            mock_health_status.metadata = {"http_host": "localhost", "http_port": 8080}

            # Should work without kwargs
            registration = wrapper.create_mesh_agent_registration(mock_health_status)

            assert len(registration.tools) == 1
            tool_reg = registration.tools[0]
            assert tool_reg.function_name == "simple_function"
            assert tool_reg.capability == "simple_service"

            # Should not have additional properties beyond standard fields
            tool_dict = tool_reg.to_dict()
            # Remove None/empty values that might be added by model
            tool_dict = {k: v for k, v in tool_dict.items() if v not in [None, [], {}]}

            expected_keys = {
                "function_name", "capability", "version", "description"
            }
            assert set(tool_dict.keys()).issubset(expected_keys)

    def test_mixed_tools_some_with_kwargs_some_without(self):
        """Test heartbeat with mix of tools (some with kwargs, some without)."""

        # Tool with kwargs
        enhanced_func = MagicMock()
        enhanced_func.metadata = {
            "capability": "enhanced_service",
            "function_name": "enhanced_function",
            "timeout": 60,
            "streaming": True
        }

        # Tool without kwargs
        simple_func = MagicMock()
        simple_func.metadata = {
            "capability": "simple_service",
            "function_name": "simple_function"
        }

        with patch.object(DecoratorRegistry, 'get_all_mesh_tools') as mock_get_tools:
            mock_get_tools.return_value = {
                "enhanced_function": enhanced_func,
                "simple_function": simple_func
            }

            wrapper = RegistryClientWrapper("http://registry:8080")
            mock_health_status = MagicMock()
            mock_health_status.agent_name = "test-agent"
            mock_health_status.version = "1.0.0"
            mock_health_status.timestamp = "2025-07-04T12:00:00Z"
            mock_health_status.metadata = {"http_host": "localhost", "http_port": 8080}

            registration = wrapper.create_mesh_agent_registration(mock_health_status)

            assert len(registration.tools) == 2

            # Find tools by capability
            tools_by_capability = {
                tool.capability: tool for tool in registration.tools
            }

            # Enhanced tool should have kwargs
            enhanced_tool = tools_by_capability["enhanced_service"]
            enhanced_dict = enhanced_tool.to_dict()
            assert enhanced_dict["timeout"] == 60
            assert enhanced_dict["streaming"] is True

            # Simple tool should not have additional properties
            simple_tool = tools_by_capability["simple_service"]
            simple_dict = simple_tool.to_dict()
            assert "timeout" not in simple_dict
            assert "streaming" not in simple_dict
```

### What Phase 2 Accomplishes:

- ✅ **Heartbeat kwargs flow**: Python agents send kwargs to registry during heartbeat
- ✅ **Uses Phase 1 foundation**: Leverages additionalProperties from updated OpenAPI models
- ✅ **Registry receives kwargs**: Foundation for storing tool configuration metadata
- ✅ **Metadata endpoint**: Local introspection of tool kwargs configuration
- ✅ **Backward compatibility**: Tools without kwargs continue working normally
- ✅ **Mixed tool support**: Agents can have both kwargs and non-kwargs tools
- ✅ **TDD validation**: Comprehensive tests verify kwargs flow

### What Doesn't Work Yet (waiting for Phase 7-8):

- ❌ Go registry doesn't store kwargs (needs database schema changes in Phase 7)
- ❌ Dependency resolution responses don't include kwargs (Phase 8)
- ❌ Enhanced client proxies don't exist (Phase 9)

### Testing Phase 2:

```python
# Test 1: Verify kwargs in heartbeat registration
@mesh.tool(
    capability="test_capability",
    timeout=30,
    retry_count=3,
    streaming=True,
    custom_priority="high"
)
def test_function():
    return "test"

# Test 2: Verify metadata endpoint shows kwargs
curl http://localhost:8080/metadata

# Expected response:
{
  "agent_id": "agent-123",
  "capabilities": {
    "test_capability": {
      "function_name": "test_function",
      "capability": "test_capability",
      "timeout": 30,
      "retry_count": 3,
      "streaming": true,
      "custom_priority": "high"
    }
  },
  "timestamp": "2025-07-04T12:00:00.000Z",
  "status": "healthy"
}

# Test 3: Run kwargs integration tests
python -m pytest src/runtime/python/tests/unit/test_02_heartbeat_kwargs_integration.py

# Test 4: Verify backward compatibility
@mesh.tool(capability="simple_capability")  # No kwargs
def simple_function():
    return "simple"

# Should work without any kwargs
curl http://localhost:8080/metadata | jq '.capabilities.simple_capability'
```

### Phase 2 → Phase 7-9 Connection:

**Phase 2** establishes the flow of kwargs from tools to heartbeat registration. **Phases 7-9** complete the cycle:

1. **Phase 7**: Go registry stores kwargs in database
2. **Phase 8**: Registry returns kwargs in dependency resolution responses
3. **Phase 9**: Client proxies auto-configure from received kwargs

This creates the complete **declarative configuration loop**:

```
@mesh.tool(timeout=45) → Heartbeat (Phase 2) → Registry Storage (Phase 7) → Dependency Resolution (Phase 8) → Enhanced Proxy (Phase 9)
```

---

## Phase 3: Full MCP Protocol Support

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

## Phase 7: Registry Schema Enhancement - kwargs Support Foundation

**Goal**: Extend registry database schema and OpenAPI models to support kwargs storage and retrieval
**Risk**: Medium - Database schema changes require migration
**Timeline**: 3-4 days
**Files**: Go registry service, OpenAPI spec, Python generated models

### Current State Analysis:

- ✅ `mesh.tool` decorator already supports kwargs in Python
- ✅ kwargs stored in local metadata during tool registration
- ❌ Registry database doesn't have kwargs column
- ❌ OpenAPI schema doesn't include additional_properties field
- ❌ kwargs lost during heartbeat registration process

### TDD Approach - Tests First:

#### 1. Write Go registry tests for kwargs storage

**File**: `src/core/registry/internal/storage/tools_test.go`
**Location**: Add new test cases

```go
func TestToolsStorage_KwargsSupport(t *testing.T) {
    // Test 1: Basic kwargs storage and retrieval
    t.Run("store_and_retrieve_basic_kwargs", func(t *testing.T) {
        tool := &ent.Tool{
            FunctionName: "test_function",
            Capability:   "test_capability",
            Kwargs:       `{"timeout": 30, "retry_count": 3}`,
        }

        // Store tool with kwargs
        stored, err := toolsStorage.Create(ctx, tool)
        assert.NoError(t, err)
        assert.JSONEq(t, `{"timeout": 30, "retry_count": 3}`, stored.Kwargs)

        // Retrieve and verify kwargs
        retrieved, err := toolsStorage.GetByCapability(ctx, "test_capability")
        assert.NoError(t, err)
        assert.JSONEq(t, `{"timeout": 30, "retry_count": 3}`, retrieved.Kwargs)
    })

    // Test 2: Complex kwargs with nested objects
    t.Run("store_complex_kwargs", func(t *testing.T) {
        complexKwargs := `{
            "auth_config": {"type": "bearer", "required": true},
            "rate_limits": [{"requests": 100, "window": "1m"}],
            "custom_headers": {"X-API-Version": "v2"}
        }`

        tool := &ent.Tool{
            FunctionName: "complex_function",
            Capability:   "complex_capability",
            Kwargs:       complexKwargs,
        }

        stored, err := toolsStorage.Create(ctx, tool)
        assert.NoError(t, err)
        assert.JSONEq(t, complexKwargs, stored.Kwargs)
    })

    // Test 3: Empty kwargs handling
    t.Run("handle_empty_kwargs", func(t *testing.T) {
        tool := &ent.Tool{
            FunctionName: "simple_function",
            Capability:   "simple_capability",
            Kwargs:       "",
        }

        stored, err := toolsStorage.Create(ctx, tool)
        assert.NoError(t, err)
        assert.Equal(t, "", stored.Kwargs)
    })

    // Test 4: kwargs in dependency resolution response
    t.Run("kwargs_in_dependency_resolution", func(t *testing.T) {
        // Register tool with kwargs
        tool := &ent.Tool{
            FunctionName: "timeout_tool",
            Capability:   "time_service",
            Kwargs:       `{"timeout": 60, "streaming": true}`,
        }
        toolsStorage.Create(ctx, tool)

        // Resolve dependencies
        resolution, err := dependencyResolver.ResolveDependencies(ctx, "dependent_agent")
        assert.NoError(t, err)

        // Verify kwargs included in resolution
        timeService := resolution["time_service"]
        assert.Contains(t, timeService.Kwargs, "timeout")
        assert.Contains(t, timeService.Kwargs, "streaming")
    })
}
```

#### 2. Write Python client tests for kwargs handling

**File**: `src/runtime/python/tests/unit/test_17_kwargs_support.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from _mcp_mesh.engine.mcp_client_proxy import EnhancedMCPClientProxy
from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper

class TestKwargsSupport:
    """Test kwargs support throughout the system."""

    def test_tool_registration_preserves_kwargs(self):
        """Test that tool registration preserves kwargs in registry."""
        # Mock registry response with kwargs
        mock_response = {
            "function_name": "enhanced_tool",
            "capability": "test_capability",
            "kwargs": '{"timeout": 45, "retry_count": 2, "auth_required": true}'
        }

        wrapper = RegistryClientWrapper("http://registry:8080")

        with patch.object(wrapper, '_register_tool') as mock_register:
            mock_register.return_value = mock_response

            # Verify kwargs are preserved during registration
            result = wrapper.register_tool({
                "function_name": "enhanced_tool",
                "capability": "test_capability",
                "timeout": 45,
                "retry_count": 2,
                "auth_required": True
            })

            assert "kwargs" in result
            assert "timeout" in result["kwargs"]

    def test_heartbeat_response_includes_kwargs(self):
        """Test that heartbeat responses include kwargs."""
        mock_heartbeat_response = {
            "dependencies_resolved": {
                "enhanced_tool": [{
                    "capability": "test_capability",
                    "endpoint": "http://service:8080",
                    "function_name": "enhanced_tool",
                    "kwargs": {
                        "timeout": 45,
                        "retry_count": 2,
                        "streaming": True
                    }
                }]
            }
        }

        # Verify kwargs parsing from heartbeat
        wrapper = RegistryClientWrapper("http://registry:8080")
        parsed = wrapper.parse_tool_dependencies(mock_heartbeat_response)

        assert "enhanced_tool" in parsed
        tool_info = parsed["enhanced_tool"][0]
        assert tool_info["kwargs"]["timeout"] == 45
        assert tool_info["kwargs"]["streaming"] is True

    def test_enhanced_proxy_creation_with_kwargs(self):
        """Test creating enhanced proxy with kwargs configuration."""
        kwargs_config = {
            "timeout": 60,
            "retry_count": 3,
            "custom_headers": {"X-API-Version": "v2"},
            "streaming": True
        }

        proxy = EnhancedMCPClientProxy(
            "http://service:8080",
            "enhanced_tool",
            **kwargs_config
        )

        assert proxy.timeout == 60
        assert proxy.retry_count == 3
        assert proxy.custom_headers["X-API-Version"] == "v2"
        assert proxy.streaming_capable is True
```

### Database Schema Changes (TDD Implementation):

#### 1. Create Ent migration for kwargs column

**File**: `src/core/registry/ent/migrate/migrations/20250704_add_kwargs_column.go`

```go
package migrations

import (
    "context"
    "fmt"

    "entgo.io/ent/dialect/sql"
    "entgo.io/ent/dialect/sql/schema"
)

// AddKwargsColumn adds kwargs JSON column to tools table
func AddKwargsColumn(ctx context.Context, tx *sql.Tx) error {
    // Add kwargs column as TEXT (JSON) with default empty object
    _, err := tx.ExecContext(ctx, `
        ALTER TABLE tools
        ADD COLUMN kwargs TEXT DEFAULT '{}' NOT NULL
    `)
    if err != nil {
        return fmt.Errorf("failed to add kwargs column: %w", err)
    }

    // Add index on kwargs for better query performance
    _, err = tx.ExecContext(ctx, `
        CREATE INDEX idx_tools_kwargs ON tools USING GIN ((kwargs::jsonb))
    `)
    if err != nil {
        return fmt.Errorf("failed to create kwargs index: %w", err)
    }

    return nil
}
```

#### 2. Update Ent schema definition

**File**: `src/core/registry/ent/schema/tool.go`
**Location**: Add kwargs field to Tool schema

```go
func (Tool) Fields() []ent.Field {
    return []ent.Field{
        field.String("function_name").NotEmpty(),
        field.String("capability").NotEmpty(),
        field.String("version").Default("1.0.0"),
        field.Strings("tags").Optional(),
        field.String("description").Optional(),

        // NEW: Add kwargs field for custom metadata
        field.Text("kwargs").
            Default("{}").
            Comment("JSON object containing custom tool metadata from **kwargs"),

        field.Time("created_at").Default(time.Now),
        field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
    }
}

// Add helper methods for kwargs handling
func (Tool) Mixin() []ent.Mixin {
    return []ent.Mixin{
        KwargsMixin{},
    }
}

type KwargsMixin struct{}

func (KwargsMixin) Fields() []ent.Field {
    return []ent.Field{}
}

func (KwargsMixin) Hooks() []ent.Hook {
    return []ent.Hook{
        // Validate kwargs is valid JSON before saving
        hook.On(
            func(next ent.Mutator) ent.Mutator {
                return hook.ToolFunc(func(ctx context.Context, m *gen.ToolMutation) (ent.Value, error) {
                    if kwargs, exists := m.Kwargs(); exists {
                        if !isValidJSON(kwargs) {
                            return nil, fmt.Errorf("kwargs must be valid JSON: %s", kwargs)
                        }
                    }
                    return next.Mutate(ctx, m)
                })
            },
            ent.OpCreate|ent.OpUpdate,
        ),
    }
}

func isValidJSON(s string) bool {
    var js interface{}
    return json.Unmarshal([]byte(s), &js) == nil
}
```

### OpenAPI Schema Updates:

#### 3. Update OpenAPI specification

**File**: `src/core/registry/docs/openapi.yaml`
**Location**: Update MeshToolRegistration model

```yaml
MeshToolRegistration:
  type: object
  required:
    - function_name
    - capability
  properties:
    function_name:
      type: string
      minLength: 1
      description: Name of the decorated function
    capability:
      type: string
      minLength: 1
      description: Capability provided by this function
    version:
      type: string
      default: "1.0.0"
      description: Function/capability version
    tags:
      type: array
      items:
        type: string
      description: Tags for this capability
    dependencies:
      type: array
      items:
        $ref: "#/components/schemas/MeshToolDependencyRegistration"
      description: Dependencies required by this function
    description:
      type: string
      description: Function description
    # NEW: Add kwargs for custom metadata
    kwargs:
      type: object
      additionalProperties: true
      description: Custom metadata from **kwargs in @mesh.tool decorator
      example:
        timeout: 30
        retry_count: 3
        auth_required: true
        custom_headers:
          X-API-Version: "v2"

# Also update dependency resolution response
DependencyResolution:
  type: object
  properties:
    capability:
      type: string
    endpoint:
      type: string
    function_name:
      type: string
    status:
      type: string
    agent_id:
      type: string
    # NEW: Include kwargs in dependency resolution
    kwargs:
      type: object
      additionalProperties: true
      description: Custom tool metadata for client configuration
```

### What Works After Phase 7:

- ✅ **Database kwargs storage**: Registry stores kwargs as JSON in PostgreSQL
- ✅ **Schema validation**: Ent validates kwargs as proper JSON before storage
- ✅ **OpenAPI specification**: Updated models support additional_properties
- ✅ **TDD foundation**: Comprehensive tests for kwargs storage and retrieval
- ✅ **Migration ready**: Database migration script for production deployment
- ✅ **Query optimization**: GIN index on kwargs JSON column for performance

### What Doesn't Work Yet:

- ❌ Python client doesn't send kwargs during registration
- ❌ Heartbeat responses don't include kwargs
- ❌ Enhanced client proxies don't exist yet

### Testing Phase 7:

```bash
# Test 1: Database migration
cd src/core/registry
go run cmd/migrate/main.go up

# Test 2: Run kwargs storage tests
go test ./internal/storage -run TestToolsStorage_KwargsSupport

# Test 3: Verify schema generation
go generate ./ent

# Test 4: Test OpenAPI spec validation
swagger-codegen validate -i docs/openapi.yaml

# Test 5: Generate Python models
openapi-generator generate -i docs/openapi.yaml -g python -o generated/
```

---

## Phase 8: Python Client Integration - kwargs Preservation

**Goal**: Update Python runtime to preserve kwargs during registration and parse them from heartbeat responses
**Risk**: Low - Additive changes to existing registration flow
**Timeline**: 2-3 days
**Files**: `registry_client_wrapper.py`, `dependency_resolution.py`, Python generated models

### Current State Analysis (Post-Phase 7):

- ✅ Registry database stores kwargs as JSON
- ✅ OpenAPI models support kwargs field
- ❌ Python client strips kwargs during tool registration
- ❌ Heartbeat response parsing ignores kwargs
- ❌ Dependency injection doesn't receive kwargs

### TDD Approach - Python Integration Tests:

#### 1. Write integration tests for kwargs flow

**File**: `src/runtime/python/tests/integration/test_kwargs_end_to_end.py`

```python
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper
from _mcp_mesh.pipeline.heartbeat.dependency_resolution import DependencyResolutionStep
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

class TestKwargsEndToEnd:
    """Test kwargs preservation from decorator to client proxy."""

    @pytest.mark.asyncio
    async def test_full_kwargs_flow(self):
        """Test complete kwargs flow: decorator -> registry -> heartbeat -> proxy."""

        # Step 1: Mock tool with kwargs
        test_metadata = {
            "capability": "enhanced_service",
            "function_name": "enhanced_function",
            "timeout": 45,
            "retry_count": 3,
            "streaming": True,
            "custom_headers": {"X-Version": "v2"}
        }

        # Step 2: Test registry registration preserves kwargs
        wrapper = RegistryClientWrapper("http://localhost:8080")

        with patch.object(wrapper, '_make_request') as mock_request:
            # Mock registry accepting kwargs
            mock_request.return_value = {
                "status": "success",
                "tool": {
                    "function_name": "enhanced_function",
                    "capability": "enhanced_service",
                    "kwargs": {
                        "timeout": 45,
                        "retry_count": 3,
                        "streaming": True,
                        "custom_headers": {"X-Version": "v2"}
                    }
                }
            }

            registration_result = await wrapper.register_mesh_tool(test_metadata)

            # Verify kwargs were sent to registry
            sent_data = mock_request.call_args[1]['json']
            assert sent_data['tools'][0]['kwargs']['timeout'] == 45
            assert sent_data['tools'][0]['kwargs']['streaming'] is True

        # Step 3: Test heartbeat response includes kwargs
        mock_heartbeat_response = {
            "dependencies_resolved": {
                "enhanced_function": [{
                    "capability": "enhanced_service",
                    "endpoint": "http://remote:8080",
                    "function_name": "enhanced_function",
                    "kwargs": {
                        "timeout": 45,
                        "retry_count": 3,
                        "streaming": True,
                        "custom_headers": {"X-Version": "v2"}
                    }
                }]
            }
        }

        # Step 4: Test dependency resolution processes kwargs
        resolution_step = DependencyResolutionStep()

        with patch('_mcp_mesh.engine.dependency_injector.get_global_injector') as mock_injector:
            mock_injector_instance = MagicMock()
            mock_injector.return_value = mock_injector_instance

            # Mock the hash comparison to trigger update
            with patch.object(resolution_step, '_hash_dependency_state', side_effect=['hash1', 'hash2']):
                await resolution_step.process_heartbeat_response_for_rewiring(mock_heartbeat_response)

                # Verify enhanced proxy creation with kwargs
                mock_injector_instance.register_dependency.assert_called()
                call_args = mock_injector_instance.register_dependency.call_args
                capability, proxy = call_args[0]

                assert capability == "enhanced_service"
                assert hasattr(proxy, 'kwargs_config')
                assert proxy.kwargs_config['timeout'] == 45
                assert proxy.kwargs_config['streaming'] is True

    def test_kwargs_backward_compatibility(self):
        """Test that tools without kwargs continue to work."""
        simple_metadata = {
            "capability": "simple_service",
            "function_name": "simple_function"
        }

        wrapper = RegistryClientWrapper("http://localhost:8080")

        with patch.object(wrapper, '_make_request') as mock_request:
            mock_request.return_value = {"status": "success"}

            # Should work without kwargs
            result = wrapper.register_mesh_tool(simple_metadata)

            sent_data = mock_request.call_args[1]['json']
            # kwargs should be empty dict, not cause errors
            assert sent_data['tools'][0].get('kwargs', {}) == {}
```

### Implementation - Update Python Client:

#### 2. Update registry client wrapper to preserve kwargs

**File**: `src/runtime/python/_mcp_mesh/shared/registry_client_wrapper.py`
**Location**: Update `create_mesh_agent_registration` method (around line 280)

```python
def create_mesh_agent_registration(self, health_status) -> MeshAgentRegistration:
    """Create mesh agent registration with kwargs preservation."""

    tools = []
    decorators = DecoratorRegistry.get_all_mesh_tools()

    for func_name, decorated_func in decorators.items():
        metadata = decorated_func.metadata

        # Extract standard MCP fields
        standard_fields = {
            'capability', 'function_name', 'version', 'tags',
            'description', 'dependencies'
        }

        # NEW: Extract kwargs (everything else)
        kwargs_dict = {
            k: v for k, v in metadata.items()
            if k not in standard_fields and not k.startswith('_')
        }

        # Convert dependencies to registry format
        dep_registrations = []
        for dep in metadata.get("dependencies", []):
            dep_reg = MeshToolDependencyRegistration(
                capability=dep["capability"],
                tags=dep.get("tags", []),
                version=dep.get("version"),
                namespace=dep.get("namespace", "default"),
            )
            dep_registrations.append(dep_reg)

        # Create tool registration with kwargs
        tool_reg = MeshToolRegistration(
            function_name=func_name,
            capability=metadata.get("capability"),
            tags=metadata.get("tags", []),
            version=metadata.get("version", "1.0.0"),
            dependencies=dep_registrations,
            description=metadata.get("description"),
            kwargs=kwargs_dict  # NEW: Include kwargs
        )
        tools.append(tool_reg)

        self.logger.debug(f"🔧 Tool '{func_name}' registered with kwargs: {kwargs_dict}")

    # Rest of method unchanged...
    return MeshAgentRegistration(...)
```

#### 3. Update heartbeat response parsing to extract kwargs

**File**: `src/runtime/python/_mcp_mesh/shared/registry_client_wrapper.py`
**Location**: Update `parse_tool_dependencies` method (around line 400)

```python
def parse_tool_dependencies(self, heartbeat_response: dict) -> dict:
    """Parse tool dependencies from heartbeat response with kwargs support."""

    dependencies_resolved = heartbeat_response.get("dependencies_resolved", {})
    parsed_dependencies = {}

    for function_name, dependency_list in dependencies_resolved.items():
        if not isinstance(dependency_list, list):
            continue

        parsed_dependencies[function_name] = []

        for dep_resolution in dependency_list:
            if not isinstance(dep_resolution, dict):
                continue

            # Standard dependency fields
            parsed_dep = {
                "capability": dep_resolution.get("capability", ""),
                "endpoint": dep_resolution.get("endpoint", ""),
                "function_name": dep_resolution.get("function_name", ""),
                "status": dep_resolution.get("status", ""),
                "agent_id": dep_resolution.get("agent_id", ""),
            }

            # NEW: Extract kwargs if present
            if "kwargs" in dep_resolution:
                parsed_dep["kwargs"] = dep_resolution["kwargs"]
                self.logger.debug(f"🔧 Parsed kwargs for {dep_resolution.get('capability')}: {dep_resolution['kwargs']}")

            parsed_dependencies[function_name].append(parsed_dep)

    return parsed_dependencies
```

#### 4. Update dependency resolution to pass kwargs to proxy creation

**File**: `src/runtime/python/_mcp_mesh/pipeline/heartbeat/dependency_resolution.py`
**Location**: Update proxy creation logic (around line 320)

```python
# In process_heartbeat_response_for_rewiring method
for function_name, dependencies in current_state.items():
    for capability, dep_info in dependencies.items():
        status = dep_info["status"]
        endpoint = dep_info["endpoint"]
        dep_function_name = dep_info["function_name"]
        kwargs_config = dep_info.get("kwargs", {})  # NEW: Extract kwargs

        if status == "available" and endpoint and dep_function_name:
            # ... existing self-dependency logic ...

            if is_self_dependency:
                # ... existing self-dependency creation ...
            else:
                # NEW: Create cross-service proxy with kwargs configuration
                proxy_type = self._determine_proxy_type_for_capability(capability, injector)

                if proxy_type == "FullMCPProxy":
                    new_proxy = FullMCPProxy(
                        endpoint,
                        dep_function_name,
                        kwargs_config=kwargs_config  # NEW: Pass kwargs
                    )
                    self.logger.debug(
                        f"🔧 Created FullMCPProxy with kwargs: {kwargs_config}"
                    )
                else:
                    new_proxy = MCPClientProxy(
                        endpoint,
                        dep_function_name,
                        kwargs_config=kwargs_config  # NEW: Pass kwargs
                    )
                    self.logger.debug(
                        f"🔧 Created MCPClientProxy with kwargs: {kwargs_config}"
                    )

            # Update in injector
            await injector.register_dependency(capability, new_proxy)
            updated_count += 1
```

### Regenerate Python Models:

#### 5. Update generated Python models to include kwargs

**File**: `src/runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/models/mesh_tool_registration.py`
**Action**: Regenerate from updated OpenAPI spec

```bash
# Regenerate Python models from updated OpenAPI spec
cd src/core/registry
openapi-generator generate \
  -i docs/openapi.yaml \
  -g python \
  -o ../../runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/ \
  --additional-properties=packageName=mcp_mesh_registry_client
```

### What Works After Phase 8:

- ✅ **Kwargs registration**: Python client preserves kwargs during tool registration
- ✅ **Heartbeat kwargs**: Dependency resolution responses include kwargs
- ✅ **Kwargs parsing**: Python client extracts kwargs from heartbeat responses
- ✅ **Proxy configuration**: kwargs passed to proxy constructors for configuration
- ✅ **Backward compatibility**: Tools without kwargs continue working normally
- ✅ **End-to-end flow**: kwargs flow from decorator through registry to client proxy

### What Doesn't Work Yet:

- ❌ Client proxies don't use kwargs for auto-configuration
- ❌ No enhanced proxy classes that leverage kwargs
- ❌ No automatic timeout/retry/header configuration

### Testing Phase 8:

```python
# Test 1: Verify kwargs registration
@mesh.tool(
    capability="enhanced_test",
    timeout=60,
    retry_count=5,
    custom_headers={"X-Test": "true"}
)
def enhanced_test_function():
    return "test"

# Check that kwargs are preserved in registry
curl http://localhost:8080/api/tools/enhanced_test
# Expected: kwargs field contains timeout, retry_count, custom_headers

# Test 2: Verify heartbeat includes kwargs
curl http://localhost:8080/api/agents/test-agent/heartbeat
# Expected: dependencies_resolved includes kwargs for each tool

# Test 3: Verify dependency resolution receives kwargs
# (Check logs for "Created [proxy type] with kwargs: {...}")

# Test 4: Integration test
python -m pytest src/runtime/python/tests/integration/test_kwargs_end_to_end.py
```

---

## Phase 9: Enhanced Client Proxies - Auto-Configuration

**Goal**: Create enhanced client proxy classes that auto-configure based on kwargs from registry
**Risk**: Low - New proxy classes, existing proxies unchanged
**Timeline**: 3-4 days
**Files**: `mcp_client_proxy.py`, new enhanced proxy classes

### Current State Analysis (Post-Phase 8):

- ✅ kwargs flow end-to-end from decorator to dependency resolution
- ✅ Registry stores and returns kwargs in heartbeat responses
- ✅ Python client passes kwargs to proxy constructors
- ❌ Proxy classes don't use kwargs for auto-configuration
- ❌ No enhanced timeout, retry, headers, or streaming configuration

### TDD Approach - Enhanced Proxy Tests:

#### 1. Write tests for enhanced proxy auto-configuration

**File**: `src/runtime/python/tests/unit/test_18_enhanced_proxy_configuration.py`

```python
import pytest
import asyncio
from unittest.mock import patch, MagicMock
import httpx

from _mcp_mesh.engine.mcp_client_proxy import EnhancedMCPClientProxy, EnhancedFullMCPProxy

class TestEnhancedProxyConfiguration:
    """Test enhanced proxy auto-configuration from kwargs."""

    def test_enhanced_proxy_timeout_configuration(self):
        """Test automatic timeout configuration from kwargs."""
        kwargs_config = {
            "timeout": 45,
            "retry_count": 3
        }

        proxy = EnhancedMCPClientProxy(
            "http://service:8080",
            "timeout_function",
            kwargs_config=kwargs_config
        )

        assert proxy.timeout == 45
        assert proxy.retry_count == 3
        assert proxy.max_retries == 3

    def test_enhanced_proxy_custom_headers(self):
        """Test automatic header configuration from kwargs."""
        kwargs_config = {
            "custom_headers": {
                "X-API-Version": "v2",
                "X-Client-ID": "mcp-mesh"
            },
            "auth_required": True
        }

        proxy = EnhancedMCPClientProxy(
            "http://service:8080",
            "header_function",
            kwargs_config=kwargs_config
        )

        assert proxy.custom_headers["X-API-Version"] == "v2"
        assert proxy.custom_headers["X-Client-ID"] == "mcp-mesh"
        assert proxy.auth_required is True

    @pytest.mark.asyncio
    async def test_enhanced_proxy_retry_logic(self):
        """Test automatic retry logic from kwargs."""
        kwargs_config = {
            "retry_count": 3,
            "retry_delay": 1.0,
            "retry_backoff": 2.0
        }

        proxy = EnhancedMCPClientProxy(
            "http://unreliable:8080",
            "flaky_function",
            kwargs_config=kwargs_config
        )

        # Mock httpx to fail twice, then succeed
        call_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("Connection failed")
            else:
                response = MagicMock()
                response.json.return_value = {
                    "jsonrpc": "2.0",
                    "id": "test",
                    "result": {"content": "success after retries"}
                }
                response.raise_for_status.return_value = None
                return response

        with patch('httpx.AsyncClient.post', side_effect=mock_post):
            result = await proxy(test_param="value")

        # Should have retried 2 times before success
        assert call_count == 3
        assert "success after retries" in str(result)

    @pytest.mark.asyncio
    async def test_enhanced_proxy_streaming_configuration(self):
        """Test automatic streaming configuration from kwargs."""
        kwargs_config = {
            "streaming": True,
            "stream_timeout": 120,
            "buffer_size": 8192
        }

        proxy = EnhancedFullMCPProxy(
            "http://streaming:8080",
            "stream_function",
            kwargs_config=kwargs_config
        )

        assert proxy.streaming_capable is True
        assert proxy.stream_timeout == 120
        assert proxy.buffer_size == 8192

        # Test streaming call auto-selection
        with patch.object(proxy, '_make_streaming_request') as mock_stream:
            mock_stream.return_value = async_generator_mock()

            # Should automatically use streaming for this proxy
            result = await proxy.call_tool_auto("stream_test", {"input": "data"})

            mock_stream.assert_called_once()

    def test_enhanced_proxy_content_type_handling(self):
        """Test automatic content type configuration from kwargs."""
        kwargs_config = {
            "accepts": ["application/json", "text/plain"],
            "content_type": "application/json",
            "max_response_size": 1024 * 1024  # 1MB
        }

        proxy = EnhancedMCPClientProxy(
            "http://service:8080",
            "content_function",
            kwargs_config=kwargs_config
        )

        assert "application/json" in proxy.accepted_content_types
        assert "text/plain" in proxy.accepted_content_types
        assert proxy.default_content_type == "application/json"
        assert proxy.max_response_size == 1024 * 1024

    def test_enhanced_proxy_fallback_to_basic(self):
        """Test fallback to basic proxy when no kwargs provided."""
        # No kwargs_config provided
        proxy = EnhancedMCPClientProxy(
            "http://service:8080",
            "basic_function"
        )

        # Should use default values
        assert proxy.timeout == 30  # Default
        assert proxy.retry_count == 1  # Default (no retries)
        assert proxy.custom_headers == {}
        assert proxy.streaming_capable is False

async def async_generator_mock():
    """Mock async generator for streaming tests."""
    yield {"chunk": 1, "data": "first"}
    yield {"chunk": 2, "data": "second"}
    yield {"chunk": 3, "data": "final", "done": True}
```

### Implementation - Enhanced Proxy Classes:

#### 2. Create EnhancedMCPClientProxy with auto-configuration

**File**: `src/runtime/python/_mcp_mesh/engine/mcp_client_proxy.py`
**Location**: Add new enhanced proxy classes

```python
class EnhancedMCPClientProxy(MCPClientProxy):
    """Enhanced MCP client proxy with kwargs-based auto-configuration.

    Auto-configures based on kwargs from @mesh.tool decorator:
    - timeout: Request timeout in seconds
    - retry_count: Number of retries for failed requests
    - retry_delay: Base delay between retries (seconds)
    - retry_backoff: Backoff multiplier for retry delays
    - custom_headers: Dict of additional headers to send
    - auth_required: Whether authentication is required
    - accepts: List of accepted content types
    - content_type: Default content type for requests
    - max_response_size: Maximum allowed response size
    """

    def __init__(self, endpoint: str, function_name: str, kwargs_config: dict = None):
        super().__init__(endpoint, function_name)

        self.kwargs_config = kwargs_config or {}

        # Auto-configure from kwargs
        self._configure_from_kwargs()

    def _configure_from_kwargs(self):
        """Auto-configure proxy settings from kwargs."""
        # Timeout configuration
        self.timeout = self.kwargs_config.get("timeout", 30)

        # Retry configuration
        self.retry_count = self.kwargs_config.get("retry_count", 1)
        self.max_retries = self.retry_count
        self.retry_delay = self.kwargs_config.get("retry_delay", 1.0)
        self.retry_backoff = self.kwargs_config.get("retry_backoff", 2.0)

        # Header configuration
        self.custom_headers = self.kwargs_config.get("custom_headers", {})
        self.auth_required = self.kwargs_config.get("auth_required", False)

        # Content type configuration
        self.accepted_content_types = self.kwargs_config.get("accepts", ["application/json"])
        self.default_content_type = self.kwargs_config.get("content_type", "application/json")
        self.max_response_size = self.kwargs_config.get("max_response_size", 10 * 1024 * 1024)  # 10MB default

        # Streaming configuration
        self.streaming_capable = self.kwargs_config.get("streaming", False)

        self.logger.info(
            f"🔧 Enhanced proxy configured - timeout: {self.timeout}s, "
            f"retries: {self.retry_count}, streaming: {self.streaming_capable}"
        )

    async def __call__(self, **kwargs) -> Any:
        """Enhanced callable with retry logic and custom configuration."""
        return await self._make_request_with_retries("tools/call", {
            "name": self.function_name,
            "arguments": kwargs
        })

    async def _make_request_with_retries(self, method: str, params: dict) -> Any:
        """Make MCP request with automatic retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._make_enhanced_request(method, params)

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries:
                    # Calculate retry delay with backoff
                    delay = self.retry_delay * (self.retry_backoff ** attempt)

                    self.logger.warning(
                        f"🔄 Request failed (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )

                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ All {self.max_retries + 1} attempts failed for {self.function_name}"
                    )

        raise last_exception

    async def _make_enhanced_request(self, method: str, params: dict) -> Any:
        """Make enhanced MCP request with custom headers and configuration."""
        request_id = str(uuid.uuid4())

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        # Build headers with custom configuration
        headers = {
            "Content-Type": self.default_content_type,
            "Accept": ", ".join(self.accepted_content_types)
        }

        # Add custom headers
        headers.update(self.custom_headers)

        # Add authentication headers if required
        if self.auth_required:
            # In production, get auth token from config/env
            auth_token = os.getenv("MCP_MESH_AUTH_TOKEN")
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            else:
                self.logger.warning("⚠️ Authentication required but no token available")

        url = f"{self.endpoint}/mcp/"

        try:
            # Use configured timeout
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                # Check response size
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_response_size:
                    raise ValueError(f"Response too large: {content_length} bytes > {self.max_response_size}")

                response.raise_for_status()

                result = response.json()
                if "error" in result:
                    raise Exception(f"MCP request failed: {result['error']}")

                # Apply existing content extraction
                from ..shared.content_extractor import ContentExtractor
                return ContentExtractor.extract_content(result.get("result"))

        except httpx.TimeoutException:
            raise Exception(f"Request timeout after {self.timeout}s")
        except httpx.ConnectError as e:
            raise Exception(f"Connection failed: {str(e)}")
        except Exception as e:
            self.logger.error(f"Enhanced request failed: {e}")
            raise


class EnhancedFullMCPProxy(FullMCPProxy):
    """Enhanced Full MCP proxy with streaming auto-configuration."""

    def __init__(self, endpoint: str, function_name: str, kwargs_config: dict = None):
        super().__init__(endpoint, function_name)

        self.kwargs_config = kwargs_config or {}
        self._configure_streaming_from_kwargs()

    def _configure_streaming_from_kwargs(self):
        """Configure streaming capabilities from kwargs."""
        self.streaming_capable = self.kwargs_config.get("streaming", False)
        self.stream_timeout = self.kwargs_config.get("stream_timeout", 300)  # 5 minutes
        self.buffer_size = self.kwargs_config.get("buffer_size", 4096)

        # Inherit all EnhancedMCPClientProxy configuration
        enhanced_proxy = EnhancedMCPClientProxy.__new__(EnhancedMCPClientProxy)
        enhanced_proxy.__init__(self.endpoint, self.function_name, self.kwargs_config)

        # Copy enhanced configuration
        self.timeout = enhanced_proxy.timeout
        self.retry_count = enhanced_proxy.retry_count
        self.custom_headers = enhanced_proxy.custom_headers
        self.auth_required = enhanced_proxy.auth_required

        self.logger.info(
            f"🌊 Enhanced Full MCP proxy configured - streaming: {self.streaming_capable}, "
            f"stream_timeout: {self.stream_timeout}s"
        )

    async def call_tool_auto(self, name: str, arguments: dict = None) -> Any:
        """Automatically choose streaming vs non-streaming based on configuration."""
        if self.streaming_capable:
            # Return async generator for streaming
            return self.call_tool_streaming(name, arguments)
        else:
            # Return regular result
            return await self.call_tool(name, arguments)

    async def call_tool_streaming(self, name: str, arguments: dict = None) -> AsyncIterator[dict]:
        """Enhanced streaming with auto-configuration."""
        if not self.streaming_capable:
            raise ValueError(f"Tool {name} not configured for streaming (streaming=False in kwargs)")

        async for chunk in self._make_streaming_request_enhanced("tools/call", {
            "name": name,
            "arguments": arguments or {}
        }):
            yield chunk

    async def _make_streaming_request_enhanced(self, method: str, params: dict) -> AsyncIterator[dict]:
        """Make enhanced streaming request with kwargs configuration."""
        request_id = str(uuid.uuid4())

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }

        # Add custom headers
        headers.update(self.custom_headers)

        url = f"{self.endpoint}/mcp/"

        try:
            # Use stream-specific timeout
            async with httpx.AsyncClient(timeout=self.stream_timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()

                    buffer = ""
                    async for chunk in response.aiter_bytes(self.buffer_size):
                        buffer += chunk.decode('utf-8')

                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)

                            if line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    yield data
                                except json.JSONDecodeError:
                                    continue

        except httpx.TimeoutException:
            raise Exception(f"Streaming timeout after {self.stream_timeout}s")
        except Exception as e:
            self.logger.error(f"Enhanced streaming request failed: {e}")
            raise
```

#### 3. Update dependency injection to use enhanced proxies

**File**: `src/runtime/python/_mcp_mesh/pipeline/heartbeat/dependency_resolution.py`
**Location**: Update proxy creation logic (around line 314)

```python
# In process_heartbeat_response_for_rewiring method
else:
    # Create cross-service proxy based on parameter types and kwargs
    proxy_type = self._determine_proxy_type_for_capability(capability, injector)

    if proxy_type == "FullMCPProxy":
        # Use enhanced proxy if kwargs available
        if kwargs_config:
            new_proxy = EnhancedFullMCPProxy(
                endpoint,
                dep_function_name,
                kwargs_config=kwargs_config
            )
            self.logger.info(
                f"🔧 Created EnhancedFullMCPProxy for '{capability}' with "
                f"timeout={kwargs_config.get('timeout', 30)}s, "
                f"streaming={kwargs_config.get('streaming', False)}"
            )
        else:
            new_proxy = FullMCPProxy(endpoint, dep_function_name)
            self.logger.debug(
                f"🔄 Created standard FullMCPProxy for '{capability}'"
            )
    else:
        # Use enhanced proxy if kwargs available
        if kwargs_config:
            new_proxy = EnhancedMCPClientProxy(
                endpoint,
                dep_function_name,
                kwargs_config=kwargs_config
            )
            self.logger.info(
                f"🔧 Created EnhancedMCPClientProxy for '{capability}' with "
                f"retries={kwargs_config.get('retry_count', 1)}, "
                f"timeout={kwargs_config.get('timeout', 30)}s"
            )
        else:
            new_proxy = MCPClientProxy(endpoint, dep_function_name)
            self.logger.debug(
                f"🔄 Created standard MCPClientProxy for '{capability}'"
            )
```

### What Works After Phase 9:

- ✅ **Auto-configuration**: Proxies auto-configure from kwargs (timeout, retries, headers)
- ✅ **Enhanced reliability**: Automatic retry logic with exponential backoff
- ✅ **Custom headers**: Authentication and API versioning headers automatically added
- ✅ **Content type handling**: Configurable accepted types and response size limits
- ✅ **Streaming optimization**: Auto-selection between streaming and non-streaming calls
- ✅ **Backward compatibility**: Standard proxies still work for tools without kwargs
- ✅ **Production ready**: Timeout, auth, and error handling for real deployments

### What Doesn't Work Yet:

- ❌ No circuit breaker integration with kwargs
- ❌ No advanced authentication methods (OAuth, mTLS)
- ❌ No parameter validation from kwargs schemas

### Testing Phase 9:

```python
# Test 1: Tool with comprehensive kwargs
@mesh.tool(
    capability="enhanced_api",
    timeout=45,
    retry_count=3,
    retry_delay=2.0,
    custom_headers={"X-API-Key": "secret", "X-Version": "v2"},
    auth_required=True,
    streaming=True,
    max_response_size=5*1024*1024  # 5MB
)
def enhanced_api_call(query: str):
    return f"Enhanced API result for: {query}"

# Test 2: Verify auto-configuration in logs
# Expected: "Enhanced proxy configured - timeout: 45s, retries: 3, streaming: True"

# Test 3: Test retry logic
# Simulate network failures, verify retries with backoff

# Test 4: Test streaming auto-selection
async def test_streaming():
    from _mcp_mesh.engine.dependency_injector import get_global_injector

    injector = get_global_injector()
    enhanced_api = injector.resolve_dependency("enhanced_api")

    # Should automatically use streaming for configured tool
    async for chunk in enhanced_api.call_tool_auto("enhanced_api_call", {"query": "test"}):
        print(f"Streaming chunk: {chunk}")

# Test 5: Integration test
python -m pytest src/runtime/python/tests/unit/test_18_enhanced_proxy_configuration.py
```

---

### Progressive Rollout:

1. **Development**: Enable all features
2. **Staging**: Enable phase by phase
3. **Production**: Conservative rollout with monitoring
4. **Rollback**: Disable features if issues occur

## Summary

Each phase builds on the previous one while maintaining full backward compatibility. The system works end-to-end at every phase, with clearly defined capabilities and limitations. This approach minimizes risk while delivering incremental value.

The key insight is that we're not breaking anything - we're **adding intelligence layer by layer** while preserving existing functionality at each step.

**Phase 7-9 Summary**: The kwargs enhancement creates a powerful declarative configuration system where tool behavior is specified at decoration time and automatically applied throughout the distributed system. This enables sophisticated client auto-configuration while maintaining the simplicity of the current @mesh.tool API.
