# Task 2: Registry Business Logic Implementation (2 hours)

## Overview: Critical Architecture Preservation

**⚠️ IMPORTANT**: This migration only replaces the registry service and CLI with Go. ALL Python decorator functionality must remain unchanged:

- `@mesh_agent` decorator analysis and metadata extraction (Python)
- Dependency injection and resolution (Python)
- Service discovery and proxy creation (Python)
- Auto-registration and heartbeat mechanisms (Python)

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Core decorator implementation
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry_server.py` - Current registry API

## CRITICAL PRESERVATION REQUIREMENT

**MANDATORY**: This Go implementation must preserve 100% of existing Python registry business logic.

**Reference Preservation**:

- Keep ALL Python registry business logic code as reference during migration
- Test EVERY existing health monitoring behavior and timer interval
- Maintain IDENTICAL service discovery query capabilities and filtering logic
- Preserve ALL passive architecture patterns (registry never initiates connections)

**Implementation Validation**:

- Each Go business logic function must pass Python registry behavior tests
- Health assessment timers and thresholds must match Python exactly
- Service discovery filtering must produce identical results to Python
- Passive monitoring behavior must be preserved (timer-based, not polling)

## Objective

Port all registry business logic maintaining passive architecture and health monitoring

## Reference

`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry.py`

## Detailed Sub-tasks

### 2.1: Implement passive health monitoring (CRITICAL - registry remains passive)

```go
// internal/registry/health.go
func (rs *RegistryService) StartHealthMonitoring() {
    go func() {
        ticker := time.NewTicker(10 * time.Second) // Same interval as Python
        for range ticker.C {
            rs.assessAgentHealth()
        }
    }()
}

func (rs *RegistryService) assessAgentHealth() {
    var agents []Agent
    rs.db.Find(&agents)

    now := time.Now()
    for _, agent := range agents {
        // Same logic as Python implementation
        timeSinceLastSeen := now.Sub(agent.LastSeen)

        if timeSinceLastSeen > 90*time.Second { // expired threshold
            agent.Status = "expired"
        } else if timeSinceLastSeen > 60*time.Second { // degraded threshold
            agent.Status = "degraded"
        } else {
            agent.Status = "healthy"
        }

        rs.db.Save(&agent)
    }
}
```

### 2.2: Implement service discovery with same query capabilities

```go
func (rs *RegistryService) ListAgents(c *gin.Context) {
    // Same query parameters as Python FastAPI
    capabilities := c.QueryArray("capabilities")
    status := c.Query("status")
    labels := c.Query("labels")

    query := rs.db.Model(&Agent{})

    // Same filtering logic as Python
    if len(capabilities) > 0 {
        // JSON array contains check for capabilities
        for _, cap := range capabilities {
            query = query.Where("JSON_CONTAINS(capabilities, ?)", fmt.Sprintf(`"%s"`, cap))
        }
    }

    if status != "" {
        query = query.Where("status = ?", status)
    }

    var agents []Agent
    query.Find(&agents)

    // EXACT same response format as Python
    c.JSON(200, gin.H{
        "agents": agents,
        "count":  len(agents),
    })
}
```

### 2.3: Implement heartbeat handling

```go
func (rs *RegistryService) Heartbeat(c *gin.Context) {
    var request struct {
        AgentID string `json:"agent_id"`
        Status  string `json:"status"`
    }

    c.ShouldBindJSON(&request)

    // Update last_seen timestamp (passive monitoring)
    rs.db.Model(&Agent{}).Where("id = ?", request.AgentID).Updates(map[string]interface{}{
        "last_seen": time.Now(),
        "status":    "healthy",
    })

    c.JSON(200, gin.H{"status": "ok"})
}
```

## Success Criteria

- [ ] Passive health monitoring implemented with same timers and thresholds as Python
- [ ] Service discovery supports same query parameters and filtering logic
- [ ] Heartbeat endpoint updates agent status with same behavior as Python
- [ ] Registry never initiates connections to agents (passive architecture preserved)
- [ ] All response formats match Python implementation exactly
