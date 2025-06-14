# MCP Mesh Registration Redesign

## Overview

Redesign the registration system to use a standardized decorator-based approach with unified request/response schemas and resilient dependency resolution.

## Key Design Principles

1. **Unified Schema**: Same request/response format for both registration and heartbeat
2. **Decorator-Centric**: Each decorator is a self-contained unit with its dependencies
3. **Resilient**: Registration can happen on multiple endpoints with graceful fallbacks
4. **Passive Registry**: Agents continue working even when registry is unavailable
5. **Cached Dependencies**: Only update proxies when dependency resolution changes

---

## Task 1: Define OpenAPI Schema

### Request Schema (Used by both `/agents/register` and `/heartbeat`)

```yaml
AgentRequest:
  type: object
  required:
    - agent_id
    - timestamp
    - metadata
  properties:
    agent_id:
      type: string
      example: "agent-hello-world-123"
    timestamp:
      type: string
      format: date-time
    metadata:
      type: object
      required:
        - name
        - agent_type
        - namespace
        - endpoint
        - decorators
      properties:
        name:
          type: string
          example: "hello-world"
        agent_type:
          type: string
          enum: ["mcp_agent"]
        namespace:
          type: string
          default: "default"
        endpoint:
          type: string
          example: "stdio://agent-hello-world-123"
        version:
          type: string
          example: "1.0.0"
        decorators:
          type: array
          items:
            $ref: "#/components/schemas/DecoratorInfo"

DecoratorInfo:
  type: object
  required:
    - function_name
    - capability
    - dependencies
  properties:
    function_name:
      type: string
      example: "hello_mesh_simple"
    capability:
      type: string
      example: "greeting"
    dependencies:
      type: array
      items:
        $ref: "#/components/schemas/DependencySpec"
    description:
      type: string
      example: "Simple greeting with date dependency"
    version:
      type: string
      example: "1.0.0"
    tags:
      type: array
      items:
        type: string

DependencySpec:
  type: object
  required:
    - capability
  properties:
    capability:
      type: string
      example: "date_service"
    tags:
      type: array
      items:
        type: string
      example: ["system", "general"]
    version:
      type: string
      example: ">=1.0.0"
    namespace:
      type: string
      default: "default"
```

### Response Schema (Used by both `/agents/register` and `/heartbeat`)

```yaml
AgentResponse:
  type: object
  required:
    - agent_id
    - status
    - message
    - timestamp
  properties:
    agent_id:
      type: string
    status:
      type: string
      enum: ["success", "error"]
    message:
      type: string
    timestamp:
      type: string
      format: date-time
    dependencies_resolved:
      type: array
      items:
        $ref: "#/components/schemas/ResolvedDecorator"

ResolvedDecorator:
  type: object
  required:
    - function_name
    - capability
    - dependencies
  properties:
    function_name:
      type: string
    capability:
      type: string
    dependencies:
      type: array
      items:
        $ref: "#/components/schemas/ResolvedDependency"

ResolvedDependency:
  type: object
  required:
    - capability
  properties:
    capability:
      type: string
    mcp_tool_info:
      type: object
      properties:
        name:
          type: string
          description: "Actual function name on provider agent"
        endpoint:
          type: string
          description: "HTTP/stdio endpoint to call"
        agent_id:
          type: string
          description: "Provider agent ID"
    status:
      type: string
      enum: ["resolved", "pending", "failed"]
      default: "resolved"
```

---

## Task 2: Unified Endpoints

### Implementation Requirements

- Both `/agents/register` and `/heartbeat` accept `AgentRequest` schema
- Both endpoints return `AgentResponse` schema
- Both endpoints perform dependency resolution
- Response includes all resolved dependencies for all decorators

### Endpoint Behavior

```
POST /agents/register  -> AgentRequest -> AgentResponse
POST /heartbeat        -> AgentRequest -> AgentResponse
```

---

## Task 3: Resilient Registration

### Registration Logic

1. **Primary**: Agent tries `/agents/register` first
2. **Fallback**: If registration fails (network/4xx/5xx), use `/heartbeat`
3. **Idempotent**: Both endpoints handle existing agents gracefully
4. **Upsert Logic**: If agent already exists, update and return success

### Database Behavior

- Use `INSERT OR REPLACE` / `UPSERT` patterns
- No errors for duplicate agent_id
- Update timestamp and dependency resolution on each call

---

## Task 4: Dependency Resolution on Both Endpoints

### Resolution Algorithm

1. **Parse Request**: Extract all unique dependencies from all decorators
2. **Query Database**: Find matching agents/capabilities in registry
3. **Tag Matching**: Match dependencies by capability + tags + version constraints
4. **Build Response**: Create `ResolvedDecorator` array with resolved dependencies

### Database Queries

```sql
-- Find agents providing a capability
SELECT agent_id, endpoint, decorators_json
FROM agents
WHERE JSON_EXTRACT(decorators_json, '$[*].capability') LIKE '%capability_name%'
  AND status = 'healthy'

-- Tag-based matching within decorators JSON
```

---

## Task 5: Python Decorator Processor Caching

### Cache Structure

```python
class DependencyCache:
    def __init__(self):
        self._cache = {}  # function_name -> resolved_dependencies

    def should_update(self, new_response: dict) -> dict[str, bool]:
        """
        Check which functions have changed dependency resolution.

        Note: Only compares dependency data, ignores timestamp/metadata to avoid
        false positives when registry updates timestamp but dependencies unchanged.

        Returns:
            Dict mapping function_name -> needs_update (bool)
        """
        updates_needed = {}

        for resolved_decorator in new_response.get("dependencies_resolved", []):
            function_name = resolved_decorator["function_name"]

            # Compare only the dependencies array, ignore metadata
            old_deps = self._cache.get(function_name, {}).get("dependencies", [])
            new_deps = resolved_decorator.get("dependencies", [])

            updates_needed[function_name] = old_deps != new_deps

        return updates_needed

    def update_cache(self, response: dict):
        """Update cache for all functions and apply proxies only where needed"""
        updates_needed = self.should_update(response)

        for resolved_decorator in response.get("dependencies_resolved", []):
            function_name = resolved_decorator["function_name"]

            # Always update cache with latest data
            self._cache[function_name] = {
                "dependencies": resolved_decorator.get("dependencies", [])
            }

            # Only apply proxies if dependencies actually changed
            if updates_needed.get(function_name, False):
                self._apply_proxies(function_name, resolved_decorator["dependencies"])
```

### Processor Logic

1. **Send Request**: Try registration/heartbeat with all decorators
2. **Parse Response**: Extract `dependencies_resolved` array
3. **Check Cache**: For ALL functions, compare dependency data (ignore timestamp)
4. **Apply Changes**: Only update proxies for functions with changed dependencies
5. **Update Cache**: Store new resolution for ALL functions for future comparison

---

## Task 6: Passive Registry Design

### Network Error Handling

```python
def handle_registry_response(response_or_error):
    if isinstance(response_or_error, NetworkError):
        # Don't clear cache or remove existing proxies
        logger.warning("Registry unavailable, using cached dependencies")
        return  # Keep existing state

    if response_or_error.status_code >= 400:
        # 4xx/5xx errors - don't clear cache
        logger.error(f"Registry error {response_or_error.status_code}")
        return  # Keep existing state

    # Only on 2xx success - process dependency updates
    process_dependency_resolution(response_or_error.json())
```

### Resilient Operation

- **Graceful Degradation**: Functions work with existing proxies when registry unavailable
- **No Disruption**: Network failures don't remove working dependency injections
- **Heartbeat Retry**: Periodic heartbeats automatically reconnect to registry when it comes back online

---

## Test-Driven Development Strategy

### Testing Philosophy

**"Test First, Code Second, Sleep Better"**

All issues we encountered today could have been caught with proper TDD:

- Schema mismatches between Go and Python
- Serialization/deserialization errors
- Missing fields in database vs struct
- Response format incompatibilities
- Cache comparison logic errors

### Smart Cross-Language Testing (No Live Systems Needed!)

**"Capture Real Go Data → Perfect Python Mock → Test Everything"**

#### Phase 1: Perfect Go Implementation with Captured Data

1. **Implement Go handlers** with new schema and comprehensive unit tests
2. **Test Go with mock database** until dependency resolution works perfectly
3. **Capture working requests** that Go accepts and validates
4. **Capture Go responses** for various scenarios (success, failures, edge cases)
5. **Save captured data** as test fixtures for Python

```bash
# Test Go thoroughly with mocks
go test ./src/core/registry/... -v

# Once Go works, capture real request/response data
curl -X POST http://localhost:8000/agents/register \
  -d @test_data/hello_world_request.json > test_data/go_response_register.json

curl -X POST http://localhost:8000/heartbeat \
  -d @test_data/hello_world_request.json > test_data/go_response_heartbeat.json

# Capture edge cases
curl -X POST http://localhost:8000/agents/register \
  -d @test_data/multi_decorator_request.json > test_data/go_response_multi_tools.json
```

#### Phase 2: Perfect Python Mock with Go Data (No Registry Needed!)

1. **Update MockRegistryClient** to return exact Go response formats
2. **Test Python processors** with captured Go responses
3. **Test dependency injection** with real MCP calls using mock
4. **Validate request generation** matches what Go expects

```python
# Update existing MockRegistryClient with Go's captured responses
class GoCompatibleMockRegistryClient(MockRegistryClient):
    def __init__(self):
        super().__init__()
        # Load real Go responses
        self.go_responses = {
            "register": load_json("test_data/go_response_register.json"),
            "heartbeat": load_json("test_data/go_response_heartbeat.json"),
            "multi_tools": load_json("test_data/go_response_multi_tools.json")
        }

    async def post(self, endpoint: str, json: dict) -> MockHTTPResponse:
        """Return exact Go response formats"""
        if endpoint == "/agents/register":
            # Validate that Python generates what Go expects
            assert_compatible_with_go_schema(json, "test_data/go_request_register.json")
            return MockHTTPResponse(self.go_responses["register"], 201)

        elif endpoint == "/heartbeat":
            assert_compatible_with_go_schema(json, "test_data/go_request_heartbeat.json")
            return MockHTTPResponse(self.go_responses["heartbeat"], 200)

# Test full dependency injection with real MCP calls
def test_dependency_injection_with_real_mcp():
    """Test that DI works with real MCP protocol calls using Go-compatible mock"""

    # Create mock that returns Go's exact response format
    mock_registry = GoCompatibleMockRegistryClient()

    # Set up provider agent in mock
    mock_registry.add_agent(MockAgent(
        "date-agent", "date-agent",
        capabilities=["date_service"],
        endpoint="http://localhost:8888/date_service"
    ))

    # Create real MCP server with @mesh_agent
    server = FastMCP(name="test-consumer")

    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=[{"capability": "date_service"}]
    )
    def greet_with_date(date_service=None):
        if date_service is None:
            return "No date service"
        return f"Hello! Date: {date_service()}"

    # Inject mock registry into processor
    processor = DecoratorProcessor(mock_registry)

    # This should:
    # 1. Send request in Go-compatible format
    # 2. Receive Go-compatible response
    # 3. Parse response correctly
    # 4. Apply dependency injection
    # 5. Work with real MCP calls
    processor.process_agents()

    # Test real MCP call with injected dependency
    result = greet_with_date()  # Should call real injected proxy
    assert "Date:" in result  # Dependency was injected and called
```

### Testing Framework Structure

#### Unit Tests (Fast, No Network)

```
tests/
├── unit/
│   ├── go/
│   │   ├── schema_validation_test.go      # OpenAPI schema compliance
│   │   ├── request_parsing_test.go        # JSON unmarshaling
│   │   ├── response_building_test.go      # JSON marshaling
│   │   ├── dependency_resolution_test.go  # Mock database queries
│   │   └── database_operations_test.go    # SQLite in-memory
│   └── python/
│       ├── test_schema_generation.py      # Request building
│       ├── test_response_parsing.py       # Response parsing
│       ├── test_cache_logic.py           # Cache comparison
│       └── test_decorator_processing.py   # Decorator metadata
```

#### Integration Tests (Medium, Local Services)

```
tests/
├── integration/
│   ├── test_cross_language.py           # Go ↔ Python compatibility
│   ├── test_schema_roundtrip.go         # Request → Response cycles
│   ├── test_database_persistence.py     # End-to-end data flow
│   └── captured_data/
│       ├── go_requests/                  # Working Go requests
│       ├── go_responses/                 # Working Go responses
│       ├── python_requests/              # Generated Python requests
│       └── comparison_reports/           # Diff analysis
```

#### End-to-End Tests (Slow, Full System)

```
tests/
├── e2e/
│   ├── test_hello_world_registration.py  # Real agent registration
│   ├── test_dependency_injection.py      # Multi-agent scenarios
│   └── test_registry_failover.py         # Network failure scenarios
```

### Mock Testing Strategy

#### Go Mocks

```go
// Mock database for dependency resolution tests
type MockDatabase struct {
    agents map[string]Agent
    tools  map[string]Tool
}

func TestDependencyResolution(t *testing.T) {
    mockDB := &MockDatabase{
        agents: map[string]Agent{
            "date-agent": {ID: "date-agent", Decorators: `[{"capability":"date_service"}]`},
        },
    }

    service := NewService(mockDB, defaultConfig)
    request := &AgentRegistrationRequest{ /* test data */ }

    response, err := service.RegisterAgent(request)

    assert.NoError(t, err)
    assert.Equal(t, "success", response.Status)
    assert.Len(t, response.DependenciesResolved, 2) // Expected count
}
```

#### Python Mocks

```python
@pytest.fixture
def mock_registry_client():
    """Mock registry client that returns captured Go responses"""
    client = Mock()
    client.register_agent.return_value = load_json("test_data/go_response_register.json")
    client.send_heartbeat.return_value = load_json("test_data/go_response_heartbeat.json")
    return client

def test_dependency_cache_with_real_response(mock_registry_client):
    """Test cache logic with actual Go response format"""
    cache = DependencyCache()
    processor = DecoratorProcessor(mock_registry_client)

    # Process response - should not throw
    result = processor.process_registry_response()

    # Verify cache behavior
    assert len(cache._cache) == 3  # hello_world has 3 functions
```

### Schema Validation Tests

#### OpenAPI Compliance

```go
func TestOpenAPICompliance(t *testing.T) {
    // Load OpenAPI spec
    spec := loadOpenAPISpec("api/mcp-mesh-registry.openapi.yaml")

    // Test all request formats
    testCases := []string{
        "test_data/hello_world_request.json",
        "test_data/system_agent_request.json",
        "test_data/multi_decorator_request.json",
    }

    for _, testFile := range testCases {
        request := loadJSON(testFile)
        assert.True(t, validateAgainstSchema(spec.AgentRequest, request))
    }
}
```

#### Request/Response Roundtrip

```python
def test_request_response_roundtrip():
    """Test that Python can generate requests and parse responses compatible with Go"""

    # Generate Python request
    decorators = load_test_decorators("hello_world")
    python_request = build_registration_request(decorators)

    # Should match Go's expected format
    go_request = load_json("test_data/go_working_request.json")
    assert_compatible_schemas(python_request, go_request)

    # Parse Go response
    go_response = load_json("test_data/go_working_response.json")
    cache = DependencyCache()

    # Should not throw
    updates = cache.should_update(go_response)
    assert isinstance(updates, dict)
```

### Continuous Testing Pipeline

#### Pre-commit Hooks

```bash
# Run before every commit
make test-unit          # Fast unit tests
make test-schemas       # OpenAPI validation
make test-cross-lang    # Go ↔ Python compatibility
```

#### CI/CD Pipeline

```yaml
test:
  script:
    - make test-unit # Unit tests with mocks
    - make test-integration # Local integration tests
    - make capture-test-data # Update captured requests/responses
    - make test-cross-language # Validate compatibility
    - make test-e2e # Full system tests
```

---

## Implementation Tasks (Smart TDD Approach)

### Task A: Perfect Go Implementation (Zero Python Dependencies) ⏳ IN PROGRESS

1. **Write Go unit tests** for new decorator schema with mock database
2. **Define OpenAPI schemas** to match test requirements
3. **Implement Go handlers** until all tests pass
4. **Test dependency resolution** thoroughly with various scenarios
5. **Capture working requests/responses** as JSON fixtures

```bash
# Implementation verification
make test-go-registry     # All Go tests pass
make capture-test-data    # Save working JSON to test_data/
```

### Task B: Enhance MockRegistryClient (Use Existing Infrastructure)

1. **Update `tests/mocks/python/mock_registry_client.py`** with new schema support
2. **Load captured Go responses** into mock configuration
3. **Add validation** that Python requests match Go expectations
4. **Test mock compatibility** with existing test suite

```python
# Enhance existing MockRegistryClient
class MockRegistryClient:
    def __init__(self, go_compatibility_mode=True):
        if go_compatibility_mode:
            self.load_go_responses("test_data/")

    def load_go_responses(self, path: str):
        """Load captured Go responses for exact compatibility"""
        self.go_register_response = load_json(f"{path}/go_response_register.json")
        self.go_heartbeat_response = load_json(f"{path}/go_response_heartbeat.json")

    async def post(self, endpoint: str, json: dict):
        """Validate Python requests match Go format, return Go responses"""
        if endpoint == "/agents/register":
            self.validate_against_go_request(json, "register")
            return MockHTTPResponse(self.go_register_response, 201)
```

### Task C: Test Python with Go-Compatible Mock (No Live Registry!)

1. **Update decorator processor tests** to use enhanced mock
2. **Test request generation** matches captured Go requests
3. **Test response parsing** with captured Go responses
4. **Test dependency injection** with real MCP calls
5. **Test cache logic** with Go response formats

```python
# Existing test pattern - just enhance with Go compatibility
def test_dependency_injection_with_mock():
    """Test from tests/integration/test_mcp_dependency_injection.py"""
    mock_registry = MockRegistryClient(go_compatibility_mode=True)

    # Test real MCP server with dependency injection
    server = create_hello_world_server()  # From examples/
    processor = DecoratorProcessor(mock_registry)

    # Should work end-to-end with Go-compatible mock
    result = processor.process_all_decorators()
    assert result.success

    # Verify real MCP calls work with injected dependencies
    assert server.can_call_tools_with_dependencies()
```

### Task D: Cross-Validation Tests (Confidence Building)

1. **Create schema compatibility tests** between Python and captured Go data
2. **Test round-trip compatibility** (Python → Go format → Python parsing)
3. **Add regression tests** to prevent backsliding
4. **Validate with multiple agent types** (hello_world, system_agent, multi-tool)

```python
def test_schema_roundtrip():
    """Test that Python can generate and consume Go-compatible data"""
    # Generate Python request
    decorators = extract_decorators_from("examples/hello_world.py")
    python_request = build_registration_request(decorators)

    # Should match captured Go request format
    go_request = load_json("test_data/go_request_hello_world.json")
    assert_schema_compatible(python_request, go_request)

    # Should parse captured Go response
    go_response = load_json("test_data/go_response_hello_world.json")
    cache = DependencyCache()
    updates = cache.should_update(go_response)  # Should not throw
    assert isinstance(updates, dict)
```

### Task E: Final Verification (Optional Live Testing)

1. **Run enhanced mock tests** - should catch 99% of issues
2. **Optional: Quick live verification** with real Go registry
3. **Document test patterns** for future development

---

## Why This Approach Is Brilliant

### 🚀 **Eliminates System Juggling**

- No need to run Go registry + Python agents + multiple terminals
- All testing happens with fast, reliable mocks
- Debug issues in isolation without network complexity

### ⚡ **Lightning Fast Feedback**

- Go tests: ~100ms (mock database)
- Python tests: ~50ms (mock registry)
- Full test suite: <5 seconds vs. previous ~5 minutes

### 🔒 **Perfect Compatibility**

- Mock returns **exact** Go response formats
- Python tested against **real** Go data
- Cross-language issues caught immediately

### 💡 **Leverages Existing Infrastructure**

- Uses existing `MockRegistryClient` class
- Enhances existing test patterns
- Builds on proven `test_mcp_dependency_injection.py` approach

### 🎯 **100% Confidence**

- If mock tests pass → live system will work
- Captured data ensures format compatibility
- No surprises during integration

---

## Implementation Order (Smart TDD)

1. **Perfect Go with mocks** (Task A) - Zero Python dependencies
2. **Capture Go data** - Working request/response fixtures
3. **Enhance Python mock** (Task B) - Use captured Go data
4. **Test Python with mock** (Task C) - Full DI + MCP testing
5. **Add cross-validation** (Task D) - Schema compatibility
6. **Optional verification** (Task E) - Quick live test

---

## Success Criteria

### Core Functionality (Must Have)

- [ ] **Single Registration Call**: Python decorator processor sends ALL `@mesh_agent` decorators from a script in ONE `/agents/register` or `/heartbeat` call
- [ ] **Complex Dependency Resolution**: Registry resolves dependencies using capability + tags + version matching from database
- [ ] **Unified Response Format**: Both `/register` and `/heartbeat` return same `dependencies_resolved` structure with per-function resolution
- [ ] **Smart Proxy Injection**: Python processes response and injects HTTP-capable proxies for resolved dependencies
- [ ] **Real MCP Calls Work**: Injected proxies can make actual MCP calls to remote servers and return results
- [ ] **Cache-Based Updates**: Python only updates injected proxies when dependency resolution actually changes (ignores timestamp)

### Example Working Scenario

```python
# examples/hello_world.py has 3 @mesh_agent decorators
# Python should send ONE request like this:
{
  "agent_id": "agent-abc123",
  "metadata": {
    "decorators": [
      {
        "function_name": "hello_mesh_simple",
        "capability": "greeting",
        "dependencies": [{"capability": "date_service"}]
      },
      {
        "function_name": "hello_mesh_typed",
        "capability": "advanced_greeting",
        "dependencies": [{"capability": "info", "tags": ["system", "general"]}]
      },
      {
        "function_name": "test_dependencies",
        "capability": "dependency_test",
        "dependencies": [
          {"capability": "date_service"},
          {"capability": "info", "tags": ["system", "disk"]}
        ]
      }
    ]
  }
}

# Registry should respond with per-function resolution:
{
  "dependencies_resolved": [
    {
      "function_name": "hello_mesh_simple",
      "dependencies": [
        {
          "capability": "date_service",
          "mcp_tool_info": {
            "name": "get_current_date",
            "endpoint": "http://date-agent:8000"
          }
        }
      ]
    },
    {
      "function_name": "hello_mesh_typed",
      "dependencies": [
        {
          "capability": "info",
          "mcp_tool_info": {
            "name": "get_system_info",
            "endpoint": "http://system-agent:8000"
          }
        }
      ]
    }
    // ... etc for all functions
  ]
}

# Python should inject proxies so this works:
def hello_mesh_simple(date_service=None):
    current_date = date_service()  # Real HTTP MCP call to date-agent:8000
    return f"Hello! Today is {current_date}"
```

### Resilience & Performance

- [ ] **Network Resilience**: Agents continue working when registry is unavailable
- [ ] **No Disruption**: Network errors don't remove existing working dependency injections
- [ ] **Heartbeat Reconnection**: Periodic heartbeats automatically reconnect and update dependencies
- [ ] **Fast Testing**: All functionality testable with enhanced MockRegistryClient (no live systems needed)

### Technical Quality

- [ ] **Schema Compliance**: All requests/responses validate against OpenAPI schema
- [ ] **Cross-Language Compatibility**: Python requests work with Go registry, Go responses work with Python processor
- [ ] **Database Consistency**: Dependencies stored and retrieved correctly with proper JSON handling
- [ ] **Test Coverage**: Unit tests with mocks + integration tests with captured data achieve >90% coverage

---

## Files to Modify

### Go Registry

- `api/mcp-mesh-registry.openapi.yaml` - Add new schemas
- `src/core/registry/handlers_impl.go` - Unified handlers
- `src/core/registry/service.go` - Dependency resolution logic

### Python Runtime

- `src/runtime/python/src/mcp_mesh/runtime/processor.py` - Caching logic
- `src/runtime/python/src/mcp_mesh/runtime/registry_client.py` - Network resilience
- `src/runtime/python/src/mcp_mesh/decorators.py` - Standardized dependency format

### Testing

- `examples/hello_world.py` - Test multiple decorators
- `examples/system_agent.py` - Test dependency provider
