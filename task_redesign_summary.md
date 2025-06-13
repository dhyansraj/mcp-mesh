# MCP Mesh Redesign Summary

## Core Architecture Change

**One Agent = One Process** (multiple tools/functions per agent)

## Key Benefits

1. **No Function Name Collisions**: Each agent has unique ID with UUID suffix
2. **Efficient Networking**: One registration + one heartbeat for all tools
3. **Rich Dependencies**: Version constraints and tag-based filtering
4. **Clean Design**: No backward compatibility baggage

## Registry Endpoints

### Core Runtime Endpoints (Python uses these)

1. **POST /agents/register**

   - Registers all tools in one call
   - Returns initial dependency resolution

2. **POST /heartbeat**

   - Lightweight "I'm alive" signal
   - Always returns full dependency resolution
   - Python compares and updates only if changed

3. **GET /agents/{id}**
   - Full agent state with dependencies
   - Used for recovery/reconnection

### Discovery Endpoints (Dashboard/CLI uses these)

4. **GET /capabilities**

   - Search tools by capability
   - Supports version constraints and tags

5. **GET /agents**

   - List all agents with summary
   - For monitoring and overview

6. **GET /health**
   - Registry health status

## Database Design (Clean, No Legacy)

```sql
-- Three simple tables
agents (id, name, endpoint, status, ...)
tools (agent_id, name, capability, version, dependencies, config)
registry_events (event_type, agent_id, timestamp, data)
```

## Python Changes

1. Generate agent ID: `{name}-{uuid}`
2. Batch all function registrations
3. Single heartbeat loop for all tools
4. Preserve all decorator parameters

## Go Registry Changes

1. Handle tools array in registration
2. Resolve dependencies per tool
3. Track heartbeat at agent level
4. Rich querying for discovery

## Implementation Order

1. ✅ Write tests (TDD approach)
2. ✅ Design database schema
3. ✅ Design API endpoints
4. ⏳ Implement Python batching
5. ⏳ Implement Go registry handlers
6. ⏳ Integration testing
7. ⏳ Update documentation

## Critical Notes

- Decorator order matters: `@server.tool()` first
- Heartbeat = healthy (no status needed)
- Dependencies resolved during registration/heartbeat
- No migration needed (not yet open sourced)
