# Task 1: Go Registry Service Foundation (2 hours)

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

**MANDATORY**: This Go implementation must preserve 100% of existing Python registry functionality.

**Reference Preservation**:

- Keep ALL Python registry code as reference during migration
- Test EVERY existing API endpoint, parameter, and response format
- Maintain IDENTICAL behavior, JSON responses, and error messages
- Preserve ALL configuration handling and environment variables

**Implementation Validation**:

- Each Go API endpoint must pass Python registry behavior tests
- Database schema must be identical to Python SQLAlchemy models
- Error responses must match Python FastAPI format exactly

## Registry Deployment Architecture

The Go registry service will be implemented as a single binary that:

- ✅ Runs embedded in CLI for development (`mcp_mesh_dev start --registry-only`)
- ✅ Runs standalone for production (`mcp-mesh-registry` binary)
- ✅ Uses same codebase for both deployment modes
- ✅ Supports future K8s/Docker deployment without code changes
- ✅ Maintains passive architecture (never initiates connections to agents)

## Objective

Replace Python FastAPI registry with Go Gin server maintaining 100% API compatibility

## Implementation Requirements

```go
// cmd/mcp-mesh-registry/main.go
package main

import (
    "github.com/gin-gonic/gin"
    "mcp-mesh/internal/registry"
    "mcp-mesh/internal/database"
    "mcp-mesh/internal/config"
)

func main() {
    // Same configuration loading as Python version
    cfg := config.LoadFromEnv()

    // Same database initialization (SQLite dev, PostgreSQL prod)
    db := database.Initialize(cfg.DatabaseURL)

    // Registry service with same business logic
    registryService := registry.NewService(db, cfg)

    // Gin server with EXACT same endpoints
    server := gin.Default()

    // CRITICAL: Identical HTTP API as Python FastAPI
    server.POST("/agents/register_with_metadata", registryService.RegisterAgent)
    server.GET("/agents", registryService.ListAgents)
    server.POST("/heartbeat", registryService.Heartbeat)
    server.GET("/health", registryService.Health)
    server.GET("/capabilities", registryService.SearchCapabilities)

    server.Run(":8080")
}
```

## Detailed Sub-tasks

### 1.1: Set up Go module structure

```bash
go mod init mcp-mesh
go get github.com/gin-gonic/gin@v1.9.1
go get github.com/mattn/go-sqlite3@v1.14.17
```

### 1.2: Port database models from Python SQLAlchemy to Go database/sql

```go
// internal/database/models.go
type Agent struct {
    ID           string    `json:"id"`
    Name         string    `json:"name"`
    Capabilities []string  `json:"capabilities"`
    LastSeen     time.Time `json:"last_seen"`
    Status       string    `json:"status"` // pending, healthy, degraded, expired
    Metadata     JSON      `json:"metadata"`
    Version      string    `json:"version"`
    CreatedAt    time.Time `json:"created_at"`
    UpdatedAt    time.Time `json:"updated_at"`
}

type CapabilityMetadata struct {
    AgentID     string `json:"agent_id"`
    Name        string `json:"name"`
    Category    string `json:"category"`
    Version     string `json:"version"`
    Description string `json:"description"`
}
```

### 1.3: Implement exact JSON response formats

```go
// CRITICAL: Must match Python FastAPI responses exactly
func (rs *RegistryService) RegisterAgent(c *gin.Context) {
    var request struct {
        ID           string                 `json:"id"`
        Name         string                 `json:"name"`
        Capabilities []string               `json:"capabilities"`
        Metadata     map[string]interface{} `json:"metadata"`
    }

    if err := c.ShouldBindJSON(&request); err != nil {
        // Same error format as Python FastAPI
        c.JSON(400, gin.H{"detail": err.Error()})
        return
    }

    // Same registration logic as Python
    agent := Agent{
        ID:           request.ID,
        Name:         request.Name,
        Capabilities: request.Capabilities,
        Metadata:     JSON(request.Metadata),
        Status:       "healthy",
        LastSeen:     time.Now(),
    }

    // Use raw SQL INSERT statement
    _, err = rs.db.Exec(`INSERT INTO agents (...) VALUES (...)`, agent.ID, agent.Name, ...)

    // EXACT response format as Python
    c.JSON(200, gin.H{
        "status":   "registered",
        "agent_id": agent.ID,
    })
}
```

## Success Criteria

- [ ] Go module structure created with all required dependencies
- [ ] Database models match Python SQLAlchemy schema exactly using raw SQL operations
- [ ] JSON response formats identical to Python FastAPI
- [ ] HTTP endpoints respond with same status codes and error messages
- [ ] Database operations work with both SQLite and PostgreSQL
