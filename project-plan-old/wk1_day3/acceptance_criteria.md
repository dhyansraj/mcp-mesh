# Week 1, Day 3: Registry Service Foundation - Acceptance Criteria

## Developer Rules Compliance
- [ ] **MCP SDK First**: All MCP features use official SDK (@app.tool(), protocol handling) without bypassing or reimplementing
- [ ] **Package Architecture**: Interfaces/stubs in mcp-mesh-types, implementations in mcp-mesh, samples import from types only
- [ ] **Types Separation**: mcp-mesh-types package contains only interfaces/types, enabling samples to work in vanilla MCP SDK environment with minimal dependencies
- [ ] **MCP Compatibility**: Code works in vanilla MCP environment with types package, enhanced features activate with full package
- [ ] **Community Ready**: Examples demonstrate proper MCP SDK patterns first, mesh features as optional enhancements
- [ ] **Samples Extracted**: Examples and sample agents are not part of main source (/src) packages. They should be in examples directory

## Registry Service Core Architecture Criteria
✅ **AC-1.1**: Pull-based architecture implemented correctly (CRITICAL)
- [ ] Registry Service operates in pull-based mode - agents call registry, NOT vice versa
- [ ] Agent registration API accepts agent capability announcements
- [ ] Service discovery API returns available agents based on queries
- [ ] No push-based communication from registry to agents implemented

✅ **AC-1.2**: SQLite database persistence operational
- [ ] SQLite database stores agent registration data persistently
- [ ] Database schema supports agent metadata, capabilities, and health status
- [ ] Data integrity maintained through proper transaction handling
- [ ] Database migrations supported for schema evolution

✅ **AC-1.3**: Timer-based health monitoring system functional
- [ ] Health monitoring operates on timer intervals, not active polling
- [ ] Agents report health status when calling registry APIs
- [ ] Stale agent records automatically marked as unhealthy
- [ ] Health status influences service discovery results

## Service Discovery Mechanism Criteria
✅ **AC-2.1**: Agent registration and discovery API operational
- [ ] `register_agent(agent_info: AgentInfo) -> RegistrationResult` accepts registrations
- [ ] `discover_agents(capabilities: List[str]) -> List[AgentInfo]` returns matching agents
- [ ] `get_agent_status(agent_id: str) -> AgentStatus` provides health information
- [ ] API responses follow consistent format and error handling

✅ **AC-2.2**: Capability-based service discovery functional
- [ ] Agents can register multiple capabilities with metadata
- [ ] Discovery queries support capability filtering and matching
- [ ] Capability metadata includes version and compatibility information
- [ ] Fuzzy matching supports flexible capability discovery

✅ **AC-2.3**: Basic load balancing algorithm implemented
- [ ] Service discovery distributes requests across healthy agents
- [ ] Load balancing considers agent capacity and current load
- [ ] Unhealthy agents excluded from load balancing decisions
- [ ] Round-robin or weighted algorithms implemented

## Database and Persistence Criteria
✅ **AC-3.1**: SQLite schema supports complete agent lifecycle
- [ ] Agent table stores identity, capabilities, and contact information
- [ ] Health table tracks status history and monitoring data
- [ ] Capability table enables flexible capability management
- [ ] Indexes optimize query performance for discovery operations

✅ **AC-3.2**: Data consistency and transaction handling robust
- [ ] Agent registration operations are atomic
- [ ] Concurrent access handled without data corruption
- [ ] Database locks prevent race conditions
- [ ] Transaction rollback maintains consistency on failures

## Health Monitoring and Lifecycle Criteria
✅ **AC-4.1**: Timer-based health monitoring operates correctly
- [ ] Health check timer runs at configurable intervals
- [ ] Agent last-seen timestamps updated during registry interactions
- [ ] Stale detection marks agents unhealthy after timeout period
- [ ] Health status propagates to service discovery results

✅ **AC-4.2**: Agent lifecycle management functional
- [ ] Agent registration establishes initial healthy status
- [ ] Graceful shutdown removes agents from active registry
- [ ] Crash detection identifies unresponsive agents
- [ ] Recovery process handles agent restarts correctly

## API Design and Interface Criteria
✅ **AC-5.1**: RESTful API follows standard conventions
- [ ] HTTP methods used appropriately (GET for discovery, POST for registration)
- [ ] URL patterns follow RESTful resource naming
- [ ] HTTP status codes indicate operation results correctly
- [ ] Content-Type headers specify JSON data format

✅ **AC-5.2**: Error handling provides clear diagnostics
- [ ] Validation errors include specific field information
- [ ] Internal errors logged without exposing sensitive data
- [ ] Rate limiting prevents abuse with appropriate error responses
- [ ] API documentation describes all error scenarios

## Integration and Testing Criteria
✅ **AC-6.1**: Registry Service integrates with existing agents
- [ ] File Agent successfully registers capabilities with registry
- [ ] Command Agent and Developer Agent registration functional
- [ ] Service discovery returns accurate agent information
- [ ] Health monitoring correctly tracks agent status
- [ ] Agents should gracefully handle if registry is not available. All agents should continue work with available capability and routing details without interuption in the case of registry is down
- [ ] When registry comes back online, agents should resume get updates

✅ **AC-6.2**: Comprehensive testing validates registry functionality
- [ ] Unit tests cover all API endpoints and error scenarios
- [ ] Integration tests validate agent registration and discovery
- [ ] Load testing ensures performance under concurrent access
- [ ] Failure testing validates recovery mechanisms

## Success Validation Criteria
✅ **AC-7.1**: Pull-based architecture validated end-to-end
- [ ] Agents successfully register capabilities by calling registry
- [ ] Service discovery works through agent-initiated API calls
- [ ] No registry-initiated communication to agents exists


✅ **AC-7.2**: Registry Service supports multi-agent scenarios
- [ ] Multiple agents can register simultaneously without conflicts
- [ ] Service discovery correctly filters and returns relevant agents
- [ ] Health monitoring accurately reflects agent availability across the network
