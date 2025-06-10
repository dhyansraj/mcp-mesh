# Task 18: Capability-Based Agent Organization and Dynamic Dependency Updates (4 hours)

## Overview: Capability-First Service Mesh Architecture

**⚠️ CRITICAL**: This task implements the fundamental shift from agent-centric to capability-centric organization, enabling true capability-based service discovery and dynamic dependency injection updates. This is essential for scaling to enterprise Kubernetes deployments with hundreds of pods and thousands of functions.

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Architecture principles
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Current decorator implementation
- `internal/registry/service.go` - Registry capability queries
- `examples/hello_world.py` - Multi-function agent example

## ARCHITECTURAL TRANSFORMATION

**PARADIGM SHIFT**: Moving from "agents with capabilities" to "capabilities provided by agents" - a fundamental reorganization that aligns with Kubernetes service mesh patterns.

**Current State vs. Target State**:

```python
# Current: One agent with multiple capabilities
@mesh_agent(
    capabilities=["greeting", "mesh_integration"],  # All capabilities for decorator
    dependencies=["SystemAgent"]
)
def greet_from_mcp_mesh():
    pass

# Registry sees: agent_abc123 with ["greeting", "mesh_integration"]

# Target: One capability per function
@mesh_agent(
    capability="greeting",  # Single capability per function
    dependencies=["system_service", "weather_service"]  # Multiple dependencies OK
)
def greet_from_mcp_mesh():
    pass

# Registry sees: capability "greeting" provided by agent_abc123
```

**Key Benefits**:

- Logical grouping by capability in registry
- Efficient capability-based queries
- Clear separation between what a function provides (capability) vs. what it needs (dependencies)
- Scales to thousands of functions without overwhelming flat agent lists

## Implementation Requirements

### 18.1: Decorator Enhancement for Single Capability

- [ ] Modify `MeshAgentDecorator.__init__` to accept both `capability` (string) and `capabilities` (list) parameters
- [ ] Implement validation: if `capability` is provided, ignore `capabilities`
- [ ] Update `_extract_method_signatures` to map function to single capability
- [ ] Enhance metadata extraction to clearly identify function-capability mapping
- [ ] Update decorator validation to ensure exactly one capability per function
- [ ] Add deprecation warning for multi-capability usage on single functions

### 18.2: Registry Capability Tree Implementation

- [ ] Create capability index table in registry database schema
- [ ] Implement capability tree data structure in `internal/registry/types.go`
- [ ] Add `RegisterCapability` method that links capability → agent → function
- [ ] Update `GetAgentsByCapability` to use capability index for O(1) lookups
- [ ] Implement capability health aggregation (capability health = best agent health)
- [ ] Add capability-based views to registry API responses

### 18.3: Single Agent Per Dependency Resolution

- [ ] Modify registry's capability query logic to return at most one agent
- [ ] Implement selection algorithm in `GetBestAgentForCapability`:
  - Filter by health status (only healthy agents)
  - Sort by performance metrics or metadata scores
  - Return single best match or none
- [ ] Add configuration for selection strategy (random, round-robin, performance-based)
- [ ] Ensure consistent selection within TTL window for stability
- [ ] Add debug logging for selection decisions

### 18.4: Dynamic Dependency Injection Updates

- [ ] Add dependency tracking in `MeshAgentDecorator`:
  - Store resolved dependencies with version/timestamp
  - Track which functions use which dependency instances
- [ ] Implement dependency change detection in `_send_heartbeat`:
  - Query registry for current best agents for each dependency
  - Compare with cached dependency resolutions
  - Detect changes in agent assignments
- [ ] Create dependency update mechanism:
  - Invalidate affected dependency caches
  - Re-inject new dependency instances
  - Update function bindings without restart
- [ ] Add configurable update strategies:
  - Immediate update on change
  - Delayed update with grace period
  - Manual update trigger

### 18.5: Capability Grouping and Metadata

- [ ] Add grouping metadata to capability registration:
  - `pod_name` or `service_name` from K8s environment
  - `instance_id` for replica identification
  - `version` for capability versioning
- [ ] Implement capability metadata inheritance from pod/service level
- [ ] Create aggregated views showing capabilities by:
  - Kubernetes service
  - Pod/deployment
  - Namespace
- [ ] Add capability discovery endpoints that respect grouping

## Success Criteria

### Capability Organization

- [ ] **CRITICAL**: Each function registers exactly one capability
- [ ] **CRITICAL**: Registry organizes agents under capability tree structure
- [ ] **CRITICAL**: Capability queries return O(1) performance regardless of agent count
- [ ] **CRITICAL**: Capability health reflects best available provider
- [ ] **CRITICAL**: UI/API can display logical capability groupings

### Dependency Resolution

- [ ] **CRITICAL**: Each dependency query returns at most one agent
- [ ] **CRITICAL**: Selection is deterministic within TTL window
- [ ] **CRITICAL**: Failed agents are automatically excluded from selection
- [ ] **CRITICAL**: Selection algorithm is configurable and extensible
- [ ] **CRITICAL**: Debug logs clearly show selection reasoning

### Dynamic Updates

- [ ] **CRITICAL**: Dependency changes are detected within one heartbeat interval
- [ ] **CRITICAL**: Functions receive updated dependencies without restart
- [ ] **CRITICAL**: No request failures during dependency transitions
- [ ] **CRITICAL**: Update strategy is configurable per deployment
- [ ] **CRITICAL**: Rollback is possible if new dependency fails

### Kubernetes Integration

- [ ] **CRITICAL**: Capabilities are grouped by pod/service in registry views
- [ ] **CRITICAL**: Multiple replicas of same capability are handled correctly
- [ ] **CRITICAL**: Service discovery returns service URLs, not pod IPs
- [ ] **CRITICAL**: Capability versions enable blue-green deployments
- [ ] **CRITICAL**: Metadata propagation from K8s manifests works

## Implementation Notes

### Performance Considerations

1. **Capability Index**: Use hash map for O(1) capability lookups
2. **Caching**: Cache capability→agent mappings with short TTL
3. **Batch Updates**: Group dependency updates to reduce churn
4. **Health Checks**: Async health checks to avoid blocking queries

### Migration Path

1. **Phase 1**: Support both single and multiple capabilities (backward compatible)
2. **Phase 2**: Deprecation warnings for multi-capability decorators
3. **Phase 3**: Enforce single capability per function
4. **Phase 4**: Remove multi-capability support

### Future LLM Integration Points

The capability tree structure and metadata will enable future LLM-powered features:

- Semantic capability matching
- Intent-based service discovery
- Automatic capability composition
- Performance-based routing decisions

This task transforms MCP Mesh into a true capability-based service mesh, ready for enterprise-scale Kubernetes deployments where logical organization and dynamic adaptation are critical.
