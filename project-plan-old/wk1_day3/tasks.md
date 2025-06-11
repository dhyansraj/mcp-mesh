# Week 1, Day 3: Pull-Based Registry Service Foundation - Tasks

## Morning (4 hours)
### Pull-Based Registry Service Architecture
**⚠️ CRITICAL: Registry is PASSIVE - agents call registry, registry does NOT call agents!**
- [ ] Design Registry Service using FastMCP server architecture (Kubernetes API server pattern)
- [ ] Create registry database schema for agent metadata and wiring configuration
- [ ] Implement PULL-based agent endpoints:
  - POST /heartbeat (agents call this with status updates)
  - GET /agents (for service discovery)
  - GET /capabilities (for capability discovery)
- [ ] Add SQLite persistence layer for agent registry and capability wiring

### Pull-Based Service Discovery Implementation
**⚠️ CRITICAL: Agents poll registry for updates, not push notifications!**
- [ ] Implement pull-based service discovery MCP tools:
  - agent_heartbeat(agent_id, status, capabilities) -> WiringResponse
  - list_available_agents() -> List[AgentInfo]
  - get_capability_providers(capability: str) -> List[AgentInfo]
- [ ] Add pull-based capability filtering and search
- [ ] Create agent metadata validation schema
- [ ] Implement response caching for agent polling

## Afternoon (4 hours)
### Timer-Based Health Monitoring System
**⚠️ CRITICAL: Registry uses timers, not active health checks!**
- [ ] Implement passive health monitoring:
  - Timer reset mechanism when agents call heartbeat
  - Configurable timeout thresholds per agent type
  - Automatic agent eviction when timers expire
  - Health status tracking (healthy, degraded, expired)
- [ ] Create health monitoring tools:
  - get_agent_health_status(agent_id: str) -> HealthStatus
  - get_registry_metrics() -> RegistryMetrics
  - export_prometheus_metrics() -> PrometheusMetrics

### Integration and Testing
- [ ] Create Registry Service main application with pull-based architecture
- [ ] Test agent heartbeat and discovery workflows
- [ ] Verify pull-based MCP protocol compliance
- [ ] Write integration tests for pull-based service discovery
- [ ] Document Pull-Based Registry API patterns and usage
**⚠️ Testing Note: Ensure all tests verify pull-based behavior, not push!**