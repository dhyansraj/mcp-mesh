# MCP Mesh Fast Heartbeat Optimization

## Problem Statement

Current agent recognition latency in MCP Mesh has significant delays:
- **Agent discovery**: Up to 90 seconds (60s registry detection + 30s propagation)
- **Failure detection**: Up to 60 seconds for registry to mark unhealthy
- **Network overhead**: Full heartbeat payload every 30 seconds

**Target**: Sub-10 second recognition times with reduced network overhead.

## Solution: Event-Driven HEAD Request Optimization

### Core Strategy

1. **Dual-frequency heartbeat architecture**:
   - **HEAD requests** (5s interval): Lightweight "I'm alive" checks
   - **POST requests** (event-driven): Full state sync only when topology changes

2. **Event-driven topology detection**:
   - Registry tracks topology changes via events table
   - HEAD responses guide when full heartbeat needed
   - No complex dependency tracking - simple event timestamp comparison

3. **Database-level deduplication**:
   - Handle multiple registry instances cleanly
   - Prevent duplicate events via unique constraints

## Implementation Plan

### Phase 1: OpenAPI Specification Update ✅

The OpenAPI specification has been updated with the new endpoints:

- `HEAD /heartbeat/{agent_id}`: Fast health check with response codes
- `DELETE /agents/{agent_id}`: Graceful agent unregistration

**Key Response Codes for HEAD endpoint:**
- `200 OK`: No topology changes detected
- `202 Accepted`: Topology changed, send full POST heartbeat  
- `410 Gone`: Unknown agent, please register
- `503 Service Unavailable`: Registry error, back off

### Phase 2: Regenerate API Clients

After updating the OpenAPI specification, regenerate both Go and Python clients to include the new endpoints:

#### 2.1 Generate Go Registry Server
```bash
# Regenerate Go server with new HEAD and DELETE endpoints
./tools/codegen/generate.sh registry-go
```

This generates:
- Go server stubs from `api/mcp-mesh-registry.openapi.yaml`
- Outputs to `src/core/registry/generated/server.go`
- Includes new `FastHeartbeatCheck()` and `UnregisterAgent()` handler interfaces

#### 2.2 Generate Python Registry Client  
```bash
# Regenerate Python client with new endpoints
./tools/codegen/generate.sh registry-python
```

This generates:
- Python client from the OpenAPI specification
- Outputs to `src/runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/`  
- Provides Python methods for the new HEAD and DELETE operations

#### 2.3 Generate Both Registry Clients
```bash
# Regenerate both Go server and Python client
./tools/codegen/generate.sh registry
```

#### 2.4 Update Python Registry Client Wrapper
Add support for new endpoints in the registry client wrapper:

**File: `src/runtime/python/_mcp_mesh/shared/registry_client_wrapper.py`**
```python
async def fast_heartbeat_check(self, agent_id: str) -> Optional[int]:
    """
    Perform fast heartbeat check for agent.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        HTTP status code (200=OK, 202=topology changed, 410=unknown agent, 503=error)
        or None if failed
    """
    try:
        response = self.agents_api.fast_heartbeat_check_with_http_info(agent_id)
        return response.status_code
    except Exception as e:
        self.logger.error(f"Fast heartbeat check failed for {agent_id}: {e}")
        return None

async def unregister_agent(self, agent_id: str) -> bool:
    """
    Gracefully unregister agent from registry.
    
    Args:
        agent_id: Agent identifier to unregister
        
    Returns:
        True if successful, False if failed
    """
    try:
        response = self.agents_api.unregister_agent_with_http_info(agent_id)
        return response.status_code == 204
    except Exception as e:
        self.logger.error(f"Failed to unregister agent {agent_id}: {e}")
        return False
```

#### 2.5 Fix Registry Connection Bug
**File: `src/runtime/python/_mcp_mesh/pipeline/shared/registry_connection.py`**
```python
# Fix typo on line 60 and undefined variable on line 65
registry_wrapper = RegistryClientWrapper(registry_client)  # Fixed: was registry_wrapperg
```

#### 2.6 Verify Generated Code
After regeneration, verify both generated implementations include:

**Go Server (`src/core/registry/generated/server.go`):**
- `FastHeartbeatCheck(ctx echo.Context, agentId string)` handler interface
- `UnregisterAgent(ctx echo.Context, agentId string)` handler interface
- Proper parameter binding and response types

**Python Client (`src/runtime/python/_mcp_mesh/generated/mcp_mesh_registry_client/`):**
- `fast_heartbeat_check(agent_id)` method for HEAD requests
- `unregister_agent(agent_id)` method for graceful shutdown
- Proper response code handling (200, 202, 410, 503)

### Phase 3: Database Schema Enhancement

Since we use Ent ORM, we need to modify the schema definitions and regenerate the code, not write raw SQL.

#### 3.1 Update Agent Schema
Add `last_full_refresh` field to track when agent last sent full heartbeat:

**File: `src/core/ent/schema/agent.go`**
```go
// Add this field to the Agent Fields() method
field.Time("last_full_refresh").
    Default(time.Now).
    UpdateDefault(time.Now).
    Comment("Last time agent sent full heartbeat for topology change detection"),
```

#### 3.2 Update RegistryEvent Schema  
Add "unhealthy" event type for missed heartbeat detection:

**File: `src/core/ent/schema/registryevent.go`**
```go
// Update the event_type enum to include "unhealthy"
field.Enum("event_type").
    Values("register", "heartbeat", "expire", "update", "unregister", "unhealthy").
    Comment("Type of registry event"),
```

#### 3.3 Add Database Unique Constraint
Add unique index to prevent duplicate unhealthy events by adding to RegistryEvent schema:

**File: `src/core/ent/schema/registryevent.go`**
```go
// Add this to the Indexes() method
index.Fields("agent_id", "event_type", "timestamp").
    Annotations(entsql.Annotation{
        Desc: "Prevent duplicate events within time window",
    }),
```

#### 3.4 Regenerate Ent Code
After schema changes, regenerate Ent code to create migrations:

```bash
# Generate new Ent code with schema changes
go generate ./src/core/ent
```

#### 3.5 Apply Database Migration
The schema changes will be automatically applied when the registry starts due to this code in `ent_database.go`:

```go
// Initialize schema using Ent migrations
if err := client.Schema.Create(
    ctx,
    migrate.WithGlobalUniqueID(true),
    migrate.WithDropIndex(true),
    migrate.WithDropColumn(true),
); err != nil {
    return nil, fmt.Errorf("failed to create schema: %w", err)
}
```

#### 3.6 Verify Schema Changes
After running the registry, verify the changes in the database:
- `last_full_refresh` column added to `agents` table
- `unhealthy` event type available in `registry_events` table
- Unique constraint prevents duplicate events

### Phase 4: Test-Driven Development (TDD) for Go Registry

Before implementing the Go registry changes, we'll follow a TDD approach to ensure robust, well-tested code.

#### 4.1 TDD Strategy

Go provides excellent built-in testing capabilities that make TDD natural:
- Built-in `testing` package with `go test`
- `httptest` package for HTTP handler testing
- Table-driven tests for comprehensive coverage
- Testify library for assertions and mocking

#### 4.2 Test Structure Setup

Create test files alongside implementation:
```bash
src/core/registry/
├── ent_handlers.go          # Implementation
├── ent_handlers_test.go     # Tests
├── ent_service.go           # Implementation  
├── ent_service_test.go      # Tests
└── test_helpers.go          # Shared test utilities
```

#### 4.3 Test Cases to Write First

**4.3.1 HEAD /heartbeat/{agent_id} Response Codes**
```go
func TestFastHeartbeatCheck(t *testing.T) {
    tests := []struct {
        name           string
        agentID        string
        agentExists    bool
        hasChanges     bool
        serviceError   bool
        expectedStatus int
        expectedBody   string
    }{
        {"healthy_no_changes", "agent1", true, false, false, 200, ""},
        {"topology_changed", "agent1", true, true, false, 202, ""},
        {"unknown_agent", "nonexistent", false, false, false, 410, ""},
        {"service_unavailable", "agent1", true, false, true, 503, ""},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Setup: Create test server with mocked EntService
            // Execute: Send HEAD request to /heartbeat/{agent_id}
            // Assert: Verify status code and empty body
        })
    }
}
```

**4.3.2 HasTopologyChanges Database Query**
```go
func TestHasTopologyChanges(t *testing.T) {
    tests := []struct {
        name         string
        agentID      string
        lastRefresh  time.Time
        events       []RegistryEvent
        expected     bool
        expectError  bool
    }{
        {
            "no_changes", 
            "agent1", 
            time.Now().Add(-5*time.Minute),
            []RegistryEvent{}, 
            false, 
            false,
        },
        {
            "register_event_after_refresh", 
            "agent1", 
            time.Now().Add(-5*time.Minute),
            []RegistryEvent{{EventType: "register", EventTime: time.Now()}}, 
            true, 
            false,
        },
        {
            "heartbeat_event_ignored", 
            "agent1", 
            time.Now().Add(-5*time.Minute),
            []RegistryEvent{{EventType: "heartbeat", EventTime: time.Now()}}, 
            false, 
            false,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Setup: Create test database with events
            // Execute: Call HasTopologyChanges()
            // Assert: Verify result and error handling
        })
    }
}
```

**4.3.3 DELETE /agents/{agent_id} Graceful Unregistration**
```go
func TestUnregisterAgent(t *testing.T) {
    tests := []struct {
        name           string
        agentID        string
        agentExists    bool
        expectedStatus int
        expectEvent    bool
        expectDeleted  bool
    }{
        {"successful_unregister", "agent1", true, 204, true, true},
        {"nonexistent_agent", "missing", false, 204, false, false}, // Idempotent
        {"database_error", "agent1", true, 500, false, false},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Setup: Create test database with agent
            // Execute: Send DELETE request to /agents/{agent_id}
            // Assert: Status code, event creation, agent deletion
        })
    }
}
```

**4.3.4 Background Health Monitor**
```go
func TestHealthMonitor(t *testing.T) {
    tests := []struct {
        name              string
        agents            []Agent
        unhealthyThreshold time.Duration
        expectedUnhealthy  []string
        expectedEvents     int
    }{
        {
            "no_unhealthy_agents",
            []Agent{{ID: "agent1", UpdatedAt: time.Now()}},
            90 * time.Second,
            []string{},
            0,
        },
        {
            "one_unhealthy_agent",
            []Agent{{ID: "agent1", UpdatedAt: time.Now().Add(-120 * time.Second)}},
            90 * time.Second,
            []string{"agent1"},
            1,
        },
        {
            "mixed_healthy_unhealthy",
            []Agent{
                {ID: "agent1", UpdatedAt: time.Now()},
                {ID: "agent2", UpdatedAt: time.Now().Add(-120 * time.Second)},
                {ID: "agent3", UpdatedAt: time.Now().Add(-150 * time.Second)},
            },
            90 * time.Second,
            []string{"agent2", "agent3"},
            2,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Setup: Create test database with agents
            // Execute: Run health monitor check cycle
            // Assert: Unhealthy events created, agents deleted
        })
    }
}
```

**4.3.5 Database Schema Validation**
```go
func TestDatabaseSchema(t *testing.T) {
    t.Run("agent_has_last_full_refresh", func(t *testing.T) {
        // Test that Agent entity has last_full_refresh field
        // Verify default and update behavior
    })
    
    t.Run("registry_event_supports_unhealthy", func(t *testing.T) {
        // Test that RegistryEvent supports "unhealthy" event type
        // Verify enum constraint
    })
    
    t.Run("unique_constraint_prevents_duplicates", func(t *testing.T) {
        // Test unique index on (agent_id, event_type, timestamp)
        // Verify duplicate prevention
    })
}
```

#### 4.4 Test Utilities and Mocking

**4.4.1 Test Database Setup**
```go
// test_helpers.go
func SetupTestDB(t *testing.T) *ent.Client {
    client, err := ent.Open("sqlite3", ":memory:")
    require.NoError(t, err)
    
    err = client.Schema.Create(context.Background())
    require.NoError(t, err)
    
    t.Cleanup(func() {
        client.Close()
    })
    
    return client
}
```

**4.4.2 HTTP Test Helpers**
```go
func SetupTestServer(entService *EntService) *httptest.Server {
    handler := setupRoutes(entService) // Your router setup
    return httptest.NewServer(handler)
}
```

**4.4.3 Mock EntService**
```go
type MockEntService struct {
    mock.Mock
}

func (m *MockEntService) GetAgent(ctx context.Context, agentID string) (*ent.Agent, error) {
    args := m.Called(ctx, agentID)
    return args.Get(0).(*ent.Agent), args.Error(1)
}

func (m *MockEntService) HasTopologyChanges(ctx context.Context, agentID string, lastRefresh time.Time) (bool, error) {
    args := m.Called(ctx, agentID, lastRefresh)
    return args.Bool(0), args.Error(1)
}
```

#### 4.5 TDD Workflow

1. **Red**: Write failing test first
2. **Green**: Write minimal code to pass test  
3. **Refactor**: Improve code while keeping tests green
4. **Repeat**: For each new feature/edge case

**Example TDD Cycle:**
```bash
# 1. Write test for HEAD endpoint 200 response
go test ./src/core/registry -run TestFastHeartbeatCheck/healthy_no_changes -v
# FAIL: function doesn't exist

# 2. Write minimal implementation
# Add FastHeartbeatCheck handler returning 200

# 3. Test passes, refactor if needed
go test ./src/core/registry -run TestFastHeartbeatCheck/healthy_no_changes -v  
# PASS

# 4. Add next test case (202 response)
go test ./src/core/registry -run TestFastHeartbeatCheck/topology_changed -v
# FAIL: need to implement topology change detection

# 5. Implement HasTopologyChanges, test passes
```

#### 4.6 Test Coverage Goals

- **Unit tests**: 90%+ coverage for new handler functions
- **Integration tests**: End-to-end HTTP request/response flows
- **Database tests**: Schema changes and query correctness
- **Error handling**: Network failures, database errors, timeouts
- **Edge cases**: Malformed requests, missing agents, concurrent access

#### 4.7 Continuous Testing

```bash
# Run tests during development
go test ./src/core/registry -v

# Run with coverage
go test ./src/core/registry -coverprofile=coverage.out
go tool cover -html=coverage.out

# Run tests on file changes (using entr or similar)
find src/core/registry -name "*.go" | entr -r go test ./src/core/registry -v
```

This TDD approach ensures we build robust, well-tested fast heartbeat functionality with confidence in edge case handling and error scenarios.

### Phase 5: Go Registry Implementation

#### 2.1 Add HEAD /heartbeat Endpoint

```go
// Add to ent_handlers.go
func (s *Server) HeartbeatHEAD(ctx echo.Context, agentId string) error {
    agent, err := s.entService.GetAgent(ctx.Request().Context(), agentId)
    if err != nil || agent == nil {
        return ctx.NoContent(410) // Gone - unknown agent, please register
    }
    
    // Check for topology changes since last full refresh
    hasChanges, err := s.entService.HasTopologyChanges(ctx.Request().Context(), 
        agentId, agent.LastFullRefresh)
    if err != nil {
        return ctx.NoContent(503) // Service unavailable
    }
    
    if hasChanges {
        return ctx.NoContent(202) // Accepted - please send full heartbeat
    }
    
    return ctx.NoContent(200) // OK - no changes
}
```

#### 2.2 Add Topology Change Detection

```go
// Add to ent_service.go
func (s *EntService) HasTopologyChanges(ctx context.Context, agentID string, lastRefresh time.Time) (bool, error) {
    count, err := s.client.RegistryEvent.Query().
        Where(
            registryevent.EventTimeGT(lastRefresh),
            registryevent.EventTypeIn("register", "unregister", "unhealthy"),
        ).
        Count(ctx)
    
    return count > 0, err
}
```

#### 2.3 Update POST Heartbeat Handler

```go
// Modify existing UpdateHeartbeat in ent_service.go
func (s *EntService) UpdateHeartbeat(ctx context.Context, req HeartbeatRequest) (*HeartbeatResponse, error) {
    // ... existing logic ...
    
    // Update last_full_refresh timestamp
    agent, err := s.client.Agent.UpdateOneID(req.AgentID).
        SetLastFullRefresh(time.Now()).
        SetUpdatedAt(time.Now()).
        Save(ctx)
    
    // ... rest of existing logic ...
}
```

#### 2.4 Add Background Health Monitor

```go
// Add to registry startup
func (s *EntService) StartHealthMonitor(ctx context.Context) {
    ticker := time.NewTicker(30 * time.Second)
    go func() {
        for {
            select {
            case <-ticker.C:
                s.checkUnhealthyAgents(ctx)
            case <-ctx.Done():
                ticker.Stop()
                return
            }
        }
    }()
}

func (s *EntService) checkUnhealthyAgents(ctx context.Context) {
    unhealthyThreshold := time.Now().Add(-90 * time.Second) // 90s timeout
    
    agents, err := s.client.Agent.Query().
        Where(agent.UpdatedAtLT(unhealthyThreshold)).
        All(ctx)
    
    if err != nil {
        log.Error("Failed to check unhealthy agents", "error", err)
        return
    }
    
    for _, a := range agents {
        // Try to create unhealthy event (database constraint prevents duplicates)
        event := &RegistryEvent{
            AgentID:   a.ID,
            EventType: "unhealthy",
            EventTime: time.Now(),
            Data:      map[string]interface{}{"reason": "missed_heartbeat"},
        }
        
        err := s.client.RegistryEvent.Create().
            SetAgentID(event.AgentID).
            SetEventType(event.EventType).
            SetEventTime(event.EventTime).
            SetData(event.Data).
            Exec(ctx)
        
        if err != nil && !IsUniqueConstraintError(err) {
            log.Error("Failed to create unhealthy event", "agent", a.ID, "error", err)
        }
        
        // Remove agent from active registry
        s.client.Agent.DeleteOneID(a.ID).Exec(ctx)
    }
}
```

#### 2.5 Add Graceful Shutdown Endpoint

```go
// Add to ent_handlers.go
func (s *Server) UnregisterAgent(ctx echo.Context, agentId string) error {
    err := s.entService.UnregisterAgent(ctx.Request().Context(), agentId)
    if err != nil {
        return ctx.JSON(500, map[string]string{"error": err.Error()})
    }
    
    return ctx.NoContent(204) // No content - successfully unregistered
}

// Add to ent_service.go
func (s *EntService) UnregisterAgent(ctx context.Context, agentID string) error {
    // Create unregister event
    err := s.client.RegistryEvent.Create().
        SetAgentID(agentID).
        SetEventType("unregister").
        SetEventTime(time.Now()).
        SetData(map[string]interface{}{"reason": "graceful_shutdown"}).
        Exec(ctx)
    
    if err != nil {
        return err
    }
    
    // Remove agent from registry
    return s.client.Agent.DeleteOneID(agentID).Exec(ctx)
}
```

### Phase 5: Python Runtime Changes

#### 4.1 Clean Heartbeat Loop Implementation

```python
# Replace heartbeat_orchestrator.py with clean implementation
class FastHeartbeatOrchestrator:
    def __init__(self):
        self.head_interval = int(os.getenv('MCP_MESH_HEAD_INTERVAL', '5'))
        self.full_heartbeat_every = int(os.getenv('MCP_MESH_FULL_HEARTBEAT_EVERY', '10'))
        self.head_count = 0
    
    async def run_heartbeat_loop(self):
        """Clean dual-frequency heartbeat loop - no legacy support"""
        while True:
            try:
                self.head_count += 1
                
                # Periodic full heartbeat for discovery
                if self.head_count >= self.full_heartbeat_every:
                    await self._send_post_heartbeat()
                    self.head_count = 0
                else:
                    response = await self._send_head_heartbeat()
                    if response and response.status_code in [202, 410]:
                        # Registry requests full heartbeat
                        await self._send_post_heartbeat()
                        self.head_count = 0
                
                await asyncio.sleep(self.head_interval)
            
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(5)  # Retry faster on failure
```

#### 4.2 HEAD Request Implementation

```python
# Add to heartbeat_send_step.py
class HeartbeatSendStep(PipelineStep):
    async def execute(self, context: PipelineContext) -> PipelineStepResult:
        if context.get('request_type') == 'HEAD':
            return await self._send_head_request(context)
        else:
            return await self._send_post_request(context)
    
    async def _send_head_request(self, context: PipelineContext) -> PipelineStepResult:
        """Send lightweight HEAD request for health check"""
        registry_url = context['registry_url']
        agent_id = context['agent_id']
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{registry_url}/heartbeat/{agent_id}"
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    context['head_response'] = response
                    context['head_status_code'] = response.status
                    
                    logger.debug(f"💓 HEAD heartbeat response: {response.status}")
                    
                    return PipelineStepResult(
                        success=True,
                        data={"status_code": response.status}
                    )
        
        except Exception as e:
            logger.error(f"HEAD heartbeat failed: {e}")
            return PipelineStepResult(
                success=False,
                error=str(e)
            )
    
    async def _send_post_request(self, context: PipelineContext) -> PipelineStepResult:
        """Send full POST heartbeat (existing implementation)"""
        # ... existing POST heartbeat logic ...
```

#### 4.3 Graceful Shutdown Support

```python
# Add to heartbeat_orchestrator.py
import signal
import atexit

class OptimizedHeartbeatOrchestrator:
    def __init__(self):
        # ... existing init ...
        self.shutdown_registered = False
        self._register_shutdown_handlers()
    
    def _register_shutdown_handlers(self):
        """Register handlers for graceful shutdown"""
        if self.shutdown_registered:
            return
        
        def shutdown_handler(signum, frame):
            asyncio.create_task(self._graceful_shutdown())
        
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        atexit.register(lambda: asyncio.run(self._graceful_shutdown()))
        
        self.shutdown_registered = True
    
    async def _graceful_shutdown(self):
        """Send unregister request to registry"""
        try:
            registry_url = os.getenv('MCP_MESH_REGISTRY_URL', 'http://localhost:8000')
            agent_id = self._get_agent_id()
            
            async with aiohttp.ClientSession() as session:
                url = f"{registry_url}/agents/{agent_id}"
                async with session.delete(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    logger.info(f"🏁 Graceful shutdown complete: {response.status}")
        
        except Exception as e:
            logger.error(f"Graceful shutdown failed: {e}")
```

### Phase 6: Environment Variables

```bash
# Agent-side configuration (simplified - no feature flags)
MCP_MESH_HEAD_INTERVAL=5              # HEAD request interval (seconds)
MCP_MESH_FULL_HEARTBEAT_EVERY=10      # Send full heartbeat every N HEAD requests

# Registry-side configuration  
MCP_MESH_HEALTH_CHECK_INTERVAL=30     # Health monitor interval (seconds)
MCP_MESH_UNHEALTHY_TIMEOUT=90         # Mark unhealthy after N seconds
```

## HTTP Response Code Strategy

### HEAD /heartbeat/{agent_id}

- **200 OK**: No topology changes, keep sending HEAD requests
- **202 Accepted**: Topology changed, please send full POST heartbeat
- **410 Gone**: Unknown agent, please register with POST heartbeat
- **503 Service Unavailable**: Registry error, back off

### POST /heartbeat (existing)

- **200 OK**: Registration/update successful
- **400 Bad Request**: Invalid payload
- **500 Internal Server Error**: Registry error

## Expected Performance Benefits

| Metric | Current | Optimized | Improvement |
|--------|---------|-----------|-------------|
| Agent discovery | 90s | 5-10s | **9x faster** |
| Failure detection | 60s | 15s | **4x faster** |
| Network overhead | 100% | ~20% | **80% reduction** |
| Registry CPU load | High | Low | **Significant reduction** |

## Clean Implementation Strategy

Since MCP Mesh is pre-1.0, we can implement this as a clean breaking change:

- **All agents** use the new HEAD/POST dual-frequency approach
- **Remove environment flags** - fast heartbeat is the default and only mode
- **Simplified codebase** - no legacy POST-only mode support
- **Clean registry logic** - single implementation path

## Testing Strategy

1. **Unit tests**: HEAD/POST request handling logic
2. **Integration tests**: Multi-agent scenarios with topology changes
3. **Performance tests**: Network overhead and latency measurements
4. **Failure tests**: Registry restarts, network partitions, agent crashes
5. **Database tests**: Event deduplication and timing edge cases

## Clean Implementation Rollout

1. **Phase 1**: Update OpenAPI specification ✅
2. **Phase 2**: Regenerate API clients (Go and Python)
3. **Phase 3**: Implement database schema changes
4. **Phase 4**: Implement Go registry HEAD/DELETE endpoints
5. **Phase 5**: Replace Python runtime heartbeat logic
6. **Phase 6**: Update environment variables and defaults
7. **Phase 7**: Comprehensive testing and documentation

## Monitoring and Observability

- Track HEAD vs POST request ratios
- Monitor topology change event frequency
- Measure actual discovery and failure detection times
- Alert on excessive full heartbeat fallbacks
- Dashboard for registry event patterns

This optimization maintains MCP Mesh's core simplicity while dramatically improving responsiveness and reducing network overhead.