# MCP Mesh kwargs Enhancement and Enhanced Client Proxies Implementation Plan

## Overview

This document outlines the implementation plan for adding **kwargs support** and **enhanced client proxies** to MCP Mesh. This feature enables declarative tool configuration through the `@mesh.tool` decorator, with automatic client proxy configuration throughout the distributed system.

## Problem Statement

Currently, `@mesh.tool` decorator supports kwargs locally, but they are lost during registry storage and don't reach client proxies for automatic configuration. This limits the ability to declaratively specify tool behavior like timeouts, retries, custom headers, and streaming preferences.

## Solution Overview

Create a complete declarative configuration system where tool behavior is specified at decoration time and automatically applied throughout the distributed system:

```python
@mesh.tool(
    capability="enhanced_api",
    timeout=45,
    retry_count=3,
    custom_headers={"X-API-Version": "v2"},
    streaming=True,
    auth_required=True
)
def my_enhanced_tool(query: str):
    return f"Enhanced result for: {query}"
```

The system automatically creates enhanced client proxies with the specified configuration, providing sophisticated distributed system behaviors with a simple developer experience.

## Architecture Flow

```
@mesh.tool(timeout=45)
    ↓ (Phase 1: OpenAPI Schema)
OpenAPI models support kwargs
    ↓ (Phase 2: Heartbeat)
Registry receives kwargs
    ↓ (Phase 3: Database Storage)
Registry stores kwargs in PostgreSQL
    ↓ (Phase 4: Dependency Resolution)
Registry returns kwargs to other agents
    ↓ (Phase 5: Enhanced Proxies)
Client proxies auto-configure with timeout=45
```

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

#### 2. Regenerate client models for both Go and Python

**Command**: Generate updated models with kwargs support for both languages

```bash
# 1. Update OpenAPI spec with additionalProperties for kwargs support
# (First update api/mcp-mesh-registry.openapi.yaml to add additionalProperties: true)

# 2. Use existing codegen tools to regenerate both Go and Python models
cd tools/codegen

# Generate Go registry server (includes types/models)
./generate.sh registry-go

# Generate Python registry client (used by agents)
./generate.sh registry-python

# Alternative: Generate both registry components at once
# ./generate.sh registry

# 3. Verify kwargs support in generated Python models
cd ../../src/runtime/python
python3 -c "
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import MeshToolRegistration

# Test additionalProperties support
tool_data = {
    'function_name': 'test_function',
    'capability': 'test_capability',
    'timeout': 30,
    'retry_count': 3,
    'streaming': True
}

tool = MeshToolRegistration.from_dict(tool_data)
print('✅ kwargs supported in Python models')
print('Tool dict:', tool.to_dict())
"

# 4. Verify kwargs support in generated Go models
cd ../../core/registry
go run -c "
package main

import (
    \"encoding/json\"
    \"fmt\"
    \"./generated\"
)

func main() {
    // Test additionalProperties support in Go models
    tool := &generated.MeshToolRegistration{
        FunctionName: \"test_function\",
        Capability:   \"test_capability\",
        // Additional properties should be supported via map[string]interface{}
    }

    // Test JSON marshaling with additional properties
    data, _ := json.Marshal(tool)
    fmt.Println(\"✅ kwargs supported in Go models\")
    fmt.Println(\"Tool JSON:\", string(data))
}
"
```

#### 3. Write test to verify kwargs support in models

**File**: `src/runtime/python/tests/unit/test_kwargs_01_openapi_support.py`

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

### Testing Phase 1:

```bash
# Test 1: Validate OpenAPI spec
cd api
swagger-codegen validate -i mcp-mesh-registry.openapi.yaml

# Test 2: Regenerate both Python and Go models using existing tools
cd ../tools/codegen
./generate.sh registry  # Generates both Go server and Python client

# Test 3: Test generated Python models
cd ../../src/runtime/python
python -m pytest tests/unit/test_kwargs_01_openapi_support.py

# Test 4: Test generated Go models
cd ../../core/registry
go test ./generated -v

# Test 5: Verify additionalProperties support in Python
cd ../runtime/python
python3 -c "
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import MeshToolRegistration
tool = MeshToolRegistration(function_name='test', capability='test')
tool.timeout = 45  # This should work with additionalProperties
print('✅ additionalProperties supported in Python models')
"

# Test 6: Verify additionalProperties support in Go
cd ../../core/registry
go run -c "
package main
import (
    \"fmt\"
    \"./generated\"
)
func main() {
    // Test that Go models can handle additional properties
    tool := &generated.MeshToolRegistration{}
    fmt.Println(\"✅ additionalProperties supported in Go models\")
}
"

# Test 7: Full contract validation
cd ../../tools/codegen
./generate.sh all  # Generate and validate everything
```

---

## Phase 2: Database Storage with JSON Fields and Ent Migrations

**Goal**: Implement Go registry database storage for kwargs using JSON fields (PostgreSQL JSONB/SQLite JSON) and Ent migrations
**Risk**: Medium - Database schema changes, requires careful migration
**Timeline**: 2-3 days
**Files**: Go registry Ent schemas, migration files, heartbeat handlers

### Current State Analysis (Post-Phase 1):

- ✅ OpenAPI schema supports additionalProperties for kwargs
- ✅ Python models regenerated to handle kwargs
- ✅ `@mesh.tool` decorator already supports kwargs in Python
- ✅ kwargs stored in local metadata during tool registration
- ❌ Go registry database doesn't store kwargs
- ❌ Ent schema lacks kwargs JSON fields
- ❌ Database migrations needed for kwargs storage (PostgreSQL + SQLite)

### Implementation:

#### 1. Update Ent schema to include kwargs JSON field

**File**: `src/core/registry/internal/ent/schema/tool.go`
**Location**: Add kwargs field to Tool schema

```go
package schema

import (
    "entgo.io/ent"
    "entgo.io/ent/schema/field"
    "entgo.io/ent/schema/index"
)

// Tool holds the schema definition for the Tool entity.
type Tool struct {
    ent.Schema
}

// Fields of the Tool.
func (Tool) Fields() []ent.Field {
    return []ent.Field{
        field.String("function_name").NotEmpty(),
        field.String("capability").NotEmpty(),
        field.String("version").Default("1.0.0"),
        field.Strings("tags").Optional(),
        field.String("description").Optional(),
        field.String("agent_id").NotEmpty(),
        field.Time("created_at"),
        field.Time("updated_at"),

        // NEW: Add kwargs JSON field for storing additional properties
        // Works with both PostgreSQL JSONB and SQLite JSON
        field.JSON("kwargs", map[string]interface{}{}).
            Optional().
            Comment("Additional properties/kwargs from @mesh.tool decorator"),
    }
}

// Indexes of the Tool.
func (Tool) Indexes() []ent.Index {
    return []ent.Index{
        index.Fields("capability"),
        index.Fields("agent_id"),
        index.Fields("function_name", "agent_id").Unique(),

        // NEW: Add index for kwargs JSON field
        // PostgreSQL: GIN index for JSONB optimization
        // SQLite: Standard index (GIN not supported)
        index.Fields("kwargs").
            Type("GIN").
            Comment("JSON index for kwargs field queries (PostgreSQL GIN, SQLite standard)"),
    }
}
```

#### 2. Generate Ent migration for kwargs field

**Command**: Generate migration file for kwargs field

```bash
cd src/core/registry

# Generate migration for kwargs field
go run -mod=mod entgo.io/ent/cmd/ent generate ./internal/ent/schema

# Create migration file
go run ./cmd/migrate create add_kwargs_to_tools

# The migration should look like:
```

**File**: `src/core/registry/internal/migrations/add_kwargs_to_tools.sql`

```sql
-- Add kwargs JSON field to tools table
-- PostgreSQL: Use JSONB for better performance
-- SQLite: Use TEXT with JSON constraint
ALTER TABLE tools ADD COLUMN kwargs JSONB;

-- Add index for kwargs JSON field
-- PostgreSQL: GIN index for JSONB optimization
-- SQLite: Ent will handle index creation automatically
CREATE INDEX CONCURRENTLY idx_tools_kwargs ON tools USING GIN (kwargs);

-- Add comment for documentation (PostgreSQL only)
COMMENT ON COLUMN tools.kwargs IS 'Additional properties/kwargs from @mesh.tool decorator';
```

**Note**: Ent will automatically generate database-appropriate SQL:

- **PostgreSQL**: Uses JSONB with GIN indexes for optimal JSON querying
- **SQLite**: Uses TEXT with JSON validation and standard indexes

#### 3. Update Go registry to store kwargs in database

**File**: `src/core/registry/internal/handlers/agent_handlers.go`
**Location**: Update `SendHeartbeat` method to store kwargs

```go
func (h *AgentHandlers) SendHeartbeat(ctx context.Context, req *api.MeshAgentRegistration) (*api.MeshAgentRegistrationResponse, error) {
    // ... existing validation ...

    // Process tools and extract kwargs
    for _, toolReg := range req.Tools {
        // Extract kwargs from OpenAPI additionalProperties
        kwargsMap := make(map[string]interface{})

        // Use reflection to get all fields not in standard schema
        toolValue := reflect.ValueOf(toolReg)
        toolType := reflect.TypeOf(toolReg)

        standardFields := map[string]bool{
            "FunctionName": true,
            "Capability":   true,
            "Version":      true,
            "Tags":         true,
            "Description":  true,
            "Dependencies": true,
        }

        for i := 0; i < toolValue.NumField(); i++ {
            field := toolType.Field(i)
            if !standardFields[field.Name] {
                fieldValue := toolValue.Field(i)
                if fieldValue.IsValid() && !fieldValue.IsZero() {
                    kwargsMap[strings.ToLower(field.Name)] = fieldValue.Interface()
                }
            }
        }

        // Store tool with kwargs in database
        _, err := h.db.Tool.Create().
            SetFunctionName(toolReg.FunctionName).
            SetCapability(toolReg.Capability).
            SetVersion(toolReg.Version).
            SetTags(toolReg.Tags).
            SetDescription(toolReg.Description).
            SetAgentID(req.AgentID).
            SetKwargs(kwargsMap).  // NEW: Store kwargs as JSON
            SetCreatedAt(time.Now()).
            SetUpdatedAt(time.Now()).
            OnConflict(
                sql.ConflictColumns("function_name", "agent_id"),
            ).
            UpdateNewValues().
            Exec(ctx)

        if err != nil {
            return nil, fmt.Errorf("failed to store tool with kwargs: %w", err)
        }

        h.logger.Debug("Stored tool with kwargs",
            zap.String("function_name", toolReg.FunctionName),
            zap.String("capability", toolReg.Capability),
            zap.Any("kwargs", kwargsMap))
    }

    // Return response with kwargs for dependency resolution (Phase 3)
    return &api.MeshAgentRegistrationResponse{
        Status: "success",
        DependenciesResolved: h.buildDependencyResolutionWithKwargs(ctx, req),
    }, nil
}
            tool_dict = tool_reg.to_dict()
            # Remove None/empty values that might be added by model
            tool_dict = {k: v for k, v in tool_dict.items() if v not in [None, [], {}]}

            expected_keys = {
                "function_name", "capability", "version", "description"
            }
            assert set(tool_dict.keys()).issubset(expected_keys)
```

#### 4. Add database query helpers for kwargs

**File**: `src/core/registry/internal/services/kwargs_service.go`
**Location**: New service for kwargs-related queries

```go
package services

import (
    "context"
    "encoding/json"
    "fmt"

    "github.com/mcp-mesh/registry/internal/ent"
    "github.com/mcp-mesh/registry/internal/ent/tool"
    "go.uber.org/zap"
)

type KwargsService struct {
    db     *ent.Client
    logger *zap.Logger
}

func NewKwargsService(db *ent.Client, logger *zap.Logger) *KwargsService {
    return &KwargsService{
        db:     db,
        logger: logger,
    }
}

// GetToolKwargs retrieves kwargs for a specific tool
func (s *KwargsService) GetToolKwargs(ctx context.Context, capability string) (map[string]interface{}, error) {
    tools, err := s.db.Tool.Query().
        Where(tool.Capability(capability)).
        All(ctx)

    if err != nil {
        return nil, fmt.Errorf("failed to query tools: %w", err)
    }

    if len(tools) == 0 {
        return map[string]interface{}{}, nil
    }

    // Return kwargs from first matching tool
    // In Phase 4, we'll merge kwargs from multiple tools
    return tools[0].Kwargs, nil
}

// GetAllToolsWithKwargs retrieves all tools with their kwargs
func (s *KwargsService) GetAllToolsWithKwargs(ctx context.Context) (map[string]map[string]interface{}, error) {
    tools, err := s.db.Tool.Query().
        Select(tool.FieldCapability, tool.FieldKwargs).
        All(ctx)

    if err != nil {
        return nil, fmt.Errorf("failed to query tools with kwargs: %w", err)
    }

    result := make(map[string]map[string]interface{})
    for _, t := range tools {
        result[t.Capability] = t.Kwargs
    }

    return result, nil
}

// QueryToolsByKwargs finds tools with specific kwargs values
func (s *KwargsService) QueryToolsByKwargs(ctx context.Context, kwargsQuery map[string]interface{}) ([]*ent.Tool, error) {
    // Use PostgreSQL JSON operators for querying
    query := s.db.Tool.Query()

    for key, value := range kwargsQuery {
        jsonPath := fmt.Sprintf("$.%s", key)
        query = query.Where(tool.KwargsContains(jsonPath, value))
    }

    tools, err := query.All(ctx)
    if err != nil {
        return nil, fmt.Errorf("failed to query tools by kwargs: %w", err)
    }

    return tools, nil
}
```

### Unit Test Phase 2:

```bash
# Test 1: Run Ent schema generation
cd src/core/registry
go generate ./ent

# Test 2: Test kwargs storage with mocked database
go test ./internal/handlers -run TestKwargsStorage

# Test 3: Test kwargs queries with mocked database
go test ./internal/services -run TestKwargsService

# Test 4: Test kwargs extraction from HTTP requests
go test ./registry -run TestKwargsInHeartbeatRegistration

# Test 5: Test kwargs JSON validation
go test ./internal/ent -run TestKwargsValidation
```

**File**: `src/core/registry/kwargs_unit_test.go`

```go
package registry

import (
    "testing"
    "encoding/json"
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

// Unit tests for kwargs functionality in Go registry
func TestKwargsUnitTests(t *testing.T) {
    t.Run("KwargsJSONMarshaling", func(t *testing.T) {
        // Test kwargs JSON marshaling/unmarshaling
        kwargs := map[string]interface{}{
            "timeout": float64(45),
            "retry_count": float64(3),
            "streaming": true,
            "custom_headers": map[string]interface{}{
                "X-API-Version": "v2",
            },
        }

        // Marshal to JSON
        jsonBytes, err := json.Marshal(kwargs)
        require.NoError(t, err)

        // Unmarshal back
        var result map[string]interface{}
        err = json.Unmarshal(jsonBytes, &result)
        require.NoError(t, err)

        assert.Equal(t, float64(45), result["timeout"])
        assert.Equal(t, true, result["streaming"])

        headers, ok := result["custom_headers"].(map[string]interface{})
        require.True(t, ok)
        assert.Equal(t, "v2", headers["X-API-Version"])
    })

    t.Run("KwargsExtractionFromRequest", func(t *testing.T) {
        // Test kwargs extraction from tool registration
        toolReg := map[string]interface{}{
            "function_name": "test_function",
            "capability": "test_capability",
            "version": "1.0.0",
            "description": "Test function",
            // Additional kwargs
            "timeout": float64(60),
            "retry_count": float64(5),
            "custom_config": map[string]interface{}{
                "setting": "value",
            },
        }

        // Extract kwargs (non-standard fields)
        standardFields := map[string]bool{
            "function_name": true,
            "capability": true,
            "version": true,
            "description": true,
            "tags": true,
            "dependencies": true,
        }

        kwargs := make(map[string]interface{})
        for key, value := range toolReg {
            if !standardFields[key] {
                kwargs[key] = value
            }
        }

        assert.Equal(t, float64(60), kwargs["timeout"])
        assert.Equal(t, float64(5), kwargs["retry_count"])

        config, ok := kwargs["custom_config"].(map[string]interface{})
        require.True(t, ok)
        assert.Equal(t, "value", config["setting"])
    })

    t.Run("KwargsValidation", func(t *testing.T) {
        // Test valid kwargs
        validKwargs := map[string]interface{}{
            "timeout": float64(30),
            "retry_count": float64(3),
            "streaming": false,
        }

        jsonData, err := json.Marshal(validKwargs)
        require.NoError(t, err)

        var result map[string]interface{}
        err = json.Unmarshal(jsonData, &result)
        assert.NoError(t, err)

        // Test empty kwargs
        emptyKwargs := map[string]interface{}{}
        jsonData, err = json.Marshal(emptyKwargs)
        require.NoError(t, err)
        assert.Equal(t, "{}", string(jsonData))

        // Test nil kwargs handling
        var nilKwargs map[string]interface{}
        jsonData, err = json.Marshal(nilKwargs)
        require.NoError(t, err)
        assert.Equal(t, "null", string(jsonData))
    })

    t.Run("KwargsTypeFidelity", func(t *testing.T) {
        // Test that various data types are preserved
        kwargs := map[string]interface{}{
            "string_val": "test",
            "int_val": float64(42),
            "float_val": 3.14159,
            "bool_val": true,
            "null_val": nil,
            "array_val": []interface{}{"a", "b", "c"},
            "object_val": map[string]interface{}{
                "nested": "value",
            },
        }

        // Serialize and deserialize
        jsonData, err := json.Marshal(kwargs)
        require.NoError(t, err)

        var result map[string]interface{}
        err = json.Unmarshal(jsonData, &result)
        require.NoError(t, err)

        assert.Equal(t, "test", result["string_val"])
        assert.Equal(t, float64(42), result["int_val"])
        assert.InDelta(t, 3.14159, result["float_val"], 0.00001)
        assert.Equal(t, true, result["bool_val"])
        assert.Nil(t, result["null_val"])

        array, ok := result["array_val"].([]interface{})
        require.True(t, ok)
        assert.Equal(t, "a", array[0])

        obj, ok := result["object_val"].(map[string]interface{})
        require.True(t, ok)
        assert.Equal(t, "value", obj["nested"])
    })
}
```

### What Phase 2 Accomplishes:

- ✅ **Database schema updated**: Tool entity includes kwargs JSON field (PostgreSQL JSONB/SQLite TEXT)
- ✅ **Migration created**: Database migration for kwargs field with appropriate indexing
- ✅ **Kwargs storage**: Go registry stores kwargs in database JSON field
- ✅ **Query helpers**: Service layer for kwargs-related database operations
- ✅ **Multi-database support**: Works with both PostgreSQL (production) and SQLite (local dev)
- ✅ **Database optimization**: GIN indexes for PostgreSQL, standard indexes for SQLite
- ✅ **Foundation for Phase 3**: Database can now store and query kwargs

---

## Phase 3: Heartbeat Enhancement for kwargs Registration

**Goal**: Extend registry database schema and Go backend to store kwargs information
**Risk**: Medium - Database schema changes require migration
**Timeline**: 3-4 days
**Files**: Go registry service, Ent schema, database migrations

### Current State Analysis (Post-Phase 2):

- ✅ Python agents send kwargs to registry during heartbeat
- ✅ Registry receives kwargs in heartbeat requests
- ❌ Registry database doesn't have kwargs column
- ❌ Go backend doesn't store kwargs information
- ❌ kwargs lost after heartbeat processing

### TDD Approach - Database Schema Changes:

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

#### 2. Create Ent migration for kwargs column

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

#### 3. Update Ent schema definition

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

#### 4. Update Go heartbeat handler to extract and store kwargs

**File**: `src/core/registry/internal/handlers/heartbeat.go`
**Location**: Update tool registration logic

```go
func (h *HeartbeatHandler) processToolRegistration(ctx context.Context, tool *models.MeshToolRegistration) error {
    // Extract kwargs from additional properties
    kwargsMap := make(map[string]interface{})

    // Use reflection to extract additional properties beyond standard fields
    toolValue := reflect.ValueOf(tool).Elem()
    toolType := toolValue.Type()

    standardFields := map[string]bool{
        "FunctionName": true,
        "Capability":   true,
        "Version":      true,
        "Tags":         true,
        "Dependencies": true,
        "Description":  true,
    }

    for i := 0; i < toolValue.NumField(); i++ {
        field := toolType.Field(i)
        fieldValue := toolValue.Field(i)

        // Skip standard fields and unexported fields
        if standardFields[field.Name] || !field.IsExported() {
            continue
        }

        // Include additional properties as kwargs
        if !fieldValue.IsZero() {
            kwargsMap[strings.ToLower(field.Name)] = fieldValue.Interface()
        }
    }

    // Convert kwargs to JSON
    kwargsJSON := "{}"
    if len(kwargsMap) > 0 {
        if jsonBytes, err := json.Marshal(kwargsMap); err == nil {
            kwargsJSON = string(jsonBytes)
        }
    }

    // Store tool with kwargs
    return h.toolsStorage.CreateOrUpdate(ctx, &ent.Tool{
        FunctionName: tool.FunctionName,
        Capability:   tool.Capability,
        Version:      tool.Version,
        Tags:         tool.Tags,
        Description:  tool.Description,
        Kwargs:       kwargsJSON, // NEW: Store kwargs as JSON
    })
}
```

### What Phase 3 Accomplishes:

- ✅ **Database kwargs storage**: Registry stores kwargs as JSON in PostgreSQL
- ✅ **Schema validation**: Ent validates kwargs as proper JSON before storage
- ✅ **Migration ready**: Database migration script for production deployment
- ✅ **Query optimization**: GIN index on kwargs JSON column for performance
- ✅ **Go backend integration**: Heartbeat handler extracts and stores kwargs
- ✅ **TDD foundation**: Comprehensive tests for kwargs storage and retrieval

### Testing Phase 3:

```bash
# Test 1: Database migration
cd src/core/registry
go run cmd/migrate/main.go up

# Test 2: Run kwargs storage tests
go test ./internal/storage -run TestToolsStorage_KwargsSupport

# Test 3: Verify schema generation
go generate ./ent

# Test 4: Test heartbeat with kwargs
curl -X POST http://localhost:8080/api/agents/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent",
    "tools": [{
      "function_name": "enhanced_tool",
      "capability": "data_processing",
      "timeout": 45,
      "retry_count": 3,
      "streaming": true
    }]
  }'

# Test 5: Verify kwargs stored in database
psql -h localhost -U registry -d registry_db \
  -c "SELECT function_name, capability, kwargs FROM tools WHERE capability = 'data_processing';"
```

---

## Phase 4: Python Client Integration - kwargs in Dependency Resolution

**Goal**: Update Python runtime to parse kwargs from heartbeat responses and pass them to dependency injection
**Risk**: Low - Additive changes to existing dependency resolution flow
**Timeline**: 2-3 days
**Files**: `registry_client_wrapper.py`, `dependency_resolution.py`

### Current State Analysis (Post-Phase 3):

- ✅ Registry database stores kwargs as JSON
- ✅ Go backend extracts and stores kwargs from heartbeat
- ❌ Python client doesn't parse kwargs from heartbeat responses
- ❌ Dependency resolution doesn't include kwargs
- ❌ Dependency injection doesn't receive kwargs

### Implementation:

#### 1. Update heartbeat response parsing to extract kwargs

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

            # NEW: Extract kwargs if present (from database JSON field)
            if "kwargs" in dep_resolution:
                try:
                    # kwargs might be JSON string from database
                    kwargs_data = dep_resolution["kwargs"]
                    if isinstance(kwargs_data, str):
                        import json
                        kwargs_data = json.loads(kwargs_data) if kwargs_data else {}

                    parsed_dep["kwargs"] = kwargs_data
                    self.logger.debug(f"🔧 Parsed kwargs for {dep_resolution.get('capability')}: {kwargs_data}")
                except (json.JSONDecodeError, TypeError) as e:
                    self.logger.warning(f"Failed to parse kwargs for {dep_resolution.get('capability')}: {e}")
                    parsed_dep["kwargs"] = {}

            parsed_dependencies[function_name].append(parsed_dep)

    return parsed_dependencies
```

#### 2. Update dependency resolution to pass kwargs to proxy creation

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

#### 3. Write unit tests for end-to-end kwargs flow (mocked)

**File**: `src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py`

```python
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper
from _mcp_mesh.pipeline.heartbeat.dependency_resolution import DependencyResolutionStep

class TestKwargsEndToEndUnit:
    """Unit tests for kwargs preservation from decorator to client proxy (fully mocked)."""

    @pytest.mark.asyncio
    async def test_full_kwargs_flow_mocked(self):
        """Test complete kwargs flow with mocked registry and dependencies."""

        # Step 1: Mock tool with kwargs
        test_metadata = {
            "capability": "enhanced_service",
            "function_name": "enhanced_function",
            "timeout": 45,
            "retry_count": 3,
            "streaming": True,
            "custom_headers": {"X-Version": "v2"}
        }

        # Step 2: Test registry client sends kwargs correctly
        wrapper = RegistryClientWrapper("http://localhost:8080")

        with patch.object(wrapper, '_make_request') as mock_request:
            # Mock registry accepting kwargs
            mock_request.return_value = {
                "status": "success",
                "agent_id": "test-agent",
                "dependencies_resolved": {}
            }

            # Call register_mesh_tool
            registration_result = await wrapper.register_mesh_tool(test_metadata)

            # Verify kwargs were sent to registry in correct format
            mock_request.assert_called_once()
            sent_data = mock_request.call_args[1]['json']

            assert 'tools' in sent_data
            assert len(sent_data['tools']) == 1
            tool_data = sent_data['tools'][0]

            # Verify kwargs are properly extracted and sent
            assert 'kwargs' in tool_data
            kwargs = tool_data['kwargs']
            assert kwargs['timeout'] == 45
            assert kwargs['retry_count'] == 3
            assert kwargs['streaming'] is True
            assert kwargs['custom_headers']['X-Version'] == "v2"

        # Step 3: Test dependency resolution processes kwargs from heartbeat
        mock_heartbeat_response = {
            "dependencies_resolved": {
                "enhanced_function": [{
                    "capability": "enhanced_service",
                    "endpoint": "http://remote:8080",
                    "function_name": "enhanced_function",
                    "agent_id": "remote-agent",
                    "status": "available",
                    "kwargs": {  # Already parsed as dict (simulating Go->Python conversion)
                        "timeout": 45,
                        "retry_count": 3,
                        "streaming": True,
                        "custom_headers": {"X-Version": "v2"}
                    }
                }]
            }
        }

        # Step 4: Test dependency resolution extracts kwargs
        resolution_step = DependencyResolutionStep()

        # Mock the injector and proxy creation
        with patch('_mcp_mesh.engine.dependency_injector.get_global_injector') as mock_injector:
            mock_injector_instance = MagicMock()
            mock_injector.return_value = mock_injector_instance

            # Mock proxy creation to capture kwargs_config
            created_proxies = []
            def mock_register_dependency(capability, proxy):
                created_proxies.append((capability, proxy))
            mock_injector_instance.register_dependency.side_effect = mock_register_dependency

            # Mock hash comparison to trigger proxy creation
            with patch.object(resolution_step, '_hash_dependency_state', side_effect=['hash1', 'hash2']):
                with patch.object(resolution_step, '_determine_proxy_type_for_capability', return_value="MCPClientProxy"):
                    with patch('_mcp_mesh.pipeline.heartbeat.dependency_resolution.MCPClientProxy') as mock_proxy_class:
                        mock_proxy_instance = MagicMock()
                        mock_proxy_class.return_value = mock_proxy_instance

                        await resolution_step.process_heartbeat_response_for_rewiring(mock_heartbeat_response)

                        # Verify proxy was created with kwargs_config
                        mock_proxy_class.assert_called_once()
                        call_args = mock_proxy_class.call_args

                        # Should be called with (endpoint, function_name, kwargs_config=...)
                        assert call_args[0][0] == "http://remote:8080"  # endpoint
                        assert call_args[0][1] == "enhanced_function"   # function_name

                        # Verify kwargs_config was passed
                        kwargs_config = call_args[1].get('kwargs_config', {})
                        assert kwargs_config['timeout'] == 45
                        assert kwargs_config['streaming'] is True

    def test_kwargs_backward_compatibility_unit(self):
        """Test that tools without kwargs continue to work (unit test)."""
        simple_metadata = {
            "capability": "simple_service",
            "function_name": "simple_function"
        }

        wrapper = RegistryClientWrapper("http://localhost:8080")

        with patch.object(wrapper, '_make_request') as mock_request:
            mock_request.return_value = {"status": "success", "agent_id": "test"}

            # Should work without kwargs
            result = wrapper.register_mesh_tool(simple_metadata)

            sent_data = mock_request.call_args[1]['json']
            tool_data = sent_data['tools'][0]

            # kwargs should be empty dict or None, not cause errors
            kwargs = tool_data.get('kwargs', {})
            assert kwargs == {} or kwargs is None

    def test_kwargs_json_parsing_edge_cases(self):
        """Test edge cases in kwargs JSON parsing."""
        wrapper = RegistryClientWrapper("http://localhost:8080")

        # Test with JSON string kwargs (from database)
        heartbeat_response_with_json = {
            "dependencies_resolved": {
                "test_function": [{
                    "capability": "test_service",
                    "endpoint": "http://test:8080",
                    "function_name": "test_function",
                    "kwargs": '{"timeout": 30, "streaming": false}'  # JSON string
                }]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(heartbeat_response_with_json)

        assert "test_function" in parsed_deps
        dep = parsed_deps["test_function"][0]
        assert "kwargs" in dep
        assert dep["kwargs"]["timeout"] == 30
        assert dep["kwargs"]["streaming"] is False

        # Test with malformed JSON
        heartbeat_response_bad_json = {
            "dependencies_resolved": {
                "test_function": [{
                    "capability": "test_service",
                    "kwargs": '{"invalid": json}'  # Invalid JSON
                }]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(heartbeat_response_bad_json)
        dep = parsed_deps["test_function"][0]
        assert dep["kwargs"] == {}  # Should fallback to empty dict

    def test_kwargs_extraction_from_metadata(self):
        """Test kwargs extraction from tool metadata."""
        metadata_with_kwargs = {
            "capability": "test_capability",
            "function_name": "test_function",
            "version": "1.0.0",
            "description": "Test function",
            # Non-standard fields should become kwargs
            "timeout": 60,
            "retry_count": 5,
            "custom_config": {"nested": "value"},
            "boolean_flag": True,
            "number_value": 3.14
        }

        # Mock the kwargs extraction logic that would happen in registry client
        standard_fields = {"capability", "function_name", "version", "description", "tags", "dependencies"}
        kwargs = {k: v for k, v in metadata_with_kwargs.items() if k not in standard_fields}

        assert kwargs["timeout"] == 60
        assert kwargs["retry_count"] == 5
        assert kwargs["custom_config"]["nested"] == "value"
        assert kwargs["boolean_flag"] is True
        assert kwargs["number_value"] == 3.14
```

### What Phase 4 Accomplishes:

- ✅ **Kwargs parsing**: Python client extracts kwargs from heartbeat responses
- ✅ **JSON handling**: Properly parses kwargs JSON strings from database
- ✅ **Proxy configuration**: kwargs passed to proxy constructors for configuration
- ✅ **Backward compatibility**: Tools without kwargs continue working normally
- ✅ **End-to-end flow**: kwargs flow from decorator through registry to client proxy
- ✅ **Error handling**: Graceful fallback for malformed kwargs JSON

### Unit Testing Phase 4:

```bash
# Test 1: Test kwargs parsing from heartbeat responses
python -m pytest src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py::TestKwargsEndToEndUnit::test_full_kwargs_flow_mocked

# Test 2: Test backward compatibility
python -m pytest src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py::TestKwargsEndToEndUnit::test_kwargs_backward_compatibility_unit

# Test 3: Test JSON parsing edge cases
python -m pytest src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py::TestKwargsEndToEndUnit::test_kwargs_json_parsing_edge_cases

# Test 4: Test kwargs extraction from metadata
python -m pytest src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py::TestKwargsEndToEndUnit::test_kwargs_extraction_from_metadata

# Test 5: Run all Phase 4 unit tests
python -m pytest src/runtime/python/tests/unit/test_kwargs_03_end_to_end.py -v
```

---

## Phase 5: Enhanced Client Proxies - Auto-Configuration

**Goal**: Create enhanced client proxy classes that auto-configure based on kwargs from registry
**Risk**: Low - New proxy classes, existing proxies unchanged
**Timeline**: 3-4 days
**Files**: `mcp_client_proxy.py`, new enhanced proxy classes

### Current State Analysis (Post-Phase 4):

- ✅ kwargs flow end-to-end from decorator to dependency resolution
- ✅ Registry stores and returns kwargs in heartbeat responses
- ✅ Python client passes kwargs to proxy constructors
- ❌ Proxy classes don't use kwargs for auto-configuration
- ❌ No enhanced timeout, retry, headers, or streaming configuration

### TDD Approach - Enhanced Proxy Tests:

#### 1. Write tests for enhanced proxy auto-configuration

**File**: `src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py`

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

### What Phase 5 Accomplishes:

- ✅ **Auto-configuration**: Proxies auto-configure from kwargs (timeout, retries, headers)
- ✅ **Enhanced reliability**: Automatic retry logic with exponential backoff
- ✅ **Custom headers**: Authentication and API versioning headers automatically added
- ✅ **Content type handling**: Configurable accepted types and response size limits
- ✅ **Streaming optimization**: Auto-selection between streaming and non-streaming calls
- ✅ **Backward compatibility**: Standard proxies still work for tools without kwargs
- ✅ **Production ready**: Timeout, auth, and error handling for real deployments

### Unit Testing Phase 5:

```bash
# Test 1: Test enhanced proxy timeout configuration
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_timeout_configuration

# Test 2: Test custom headers configuration
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_custom_headers

# Test 3: Test retry logic with mocked failures
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_retry_logic

# Test 4: Test streaming configuration
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_streaming_configuration

# Test 5: Test content type handling
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_content_type_handling

# Test 6: Test fallback to basic proxy
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py::TestEnhancedProxyConfiguration::test_enhanced_proxy_fallback_to_basic

# Test 7: Run all Phase 5 unit tests
python -m pytest src/runtime/python/tests/unit/test_kwargs_04_enhanced_proxies.py -v
```

**Additional Unit Test Files for Phase 5:**

**File**: `src/runtime/python/tests/unit/test_kwargs_05_proxy_edge_cases.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from _mcp_mesh.engine.mcp_client_proxy import EnhancedMCPClientProxy

class TestEnhancedProxyEdgeCases:
    """Test edge cases and error conditions for enhanced proxies."""

    def test_malformed_kwargs_config(self):
        """Test proxy creation with malformed kwargs config."""
        malformed_configs = [
            None,
            {},
            {"timeout": "invalid"},  # String instead of number
            {"retry_count": -1},     # Invalid retry count
            {"custom_headers": "not-a-dict"},  # Invalid headers
        ]

        for config in malformed_configs:
            # Should not crash, should use defaults
            proxy = EnhancedMCPClientProxy(
                "http://test:8080",
                "test_function",
                kwargs_config=config
            )

            # Should have default values
            assert proxy.timeout >= 0
            assert proxy.retry_count >= 0
            assert isinstance(proxy.custom_headers, dict)

    def test_large_kwargs_handling(self):
        """Test proxy with very large kwargs config."""
        large_kwargs = {
            "timeout": 3600,  # 1 hour
            "retry_count": 100,
            "custom_headers": {f"Header-{i}": f"Value-{i}" for i in range(100)},
            "large_config": {"nested": {f"key-{i}": f"value-{i}" for i in range(1000)}}
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080",
            "test_function",
            kwargs_config=large_kwargs
        )

        assert proxy.timeout == 3600
        assert proxy.retry_count == 100
        assert len(proxy.custom_headers) == 100

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Test behavior when all retries are exhausted."""
        kwargs_config = {
            "retry_count": 2,
            "retry_delay": 0.01,  # Fast retries for testing
            "retry_backoff": 2.0
        }

        proxy = EnhancedMCPClientProxy(
            "http://unreliable:8080",
            "failing_function",
            kwargs_config=kwargs_config
        )

        # Mock all attempts to fail
        def always_fail(*args, **kwargs):
            raise Exception("Network error")

        with patch.object(proxy, '_make_enhanced_request', side_effect=always_fail):
            with pytest.raises(Exception, match="Network error"):
                await proxy(test_param="value")

    def test_kwargs_config_immutability(self):
        """Test that kwargs_config cannot be modified after creation."""
        original_config = {
            "timeout": 30,
            "retry_count": 3
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080",
            "test_function",
            kwargs_config=original_config.copy()
        )

        # Modifying original config should not affect proxy
        original_config["timeout"] = 999

        assert proxy.timeout == 30  # Should remain unchanged
```

---

## Implementation Summary

### Complete Declarative Configuration Flow

After all phases are implemented, developers can declare tool behavior once and have it automatically applied throughout the distributed system:

```python
@mesh.tool(
    capability="ai_service",
    timeout=120,                    # 2 minute timeout
    retry_count=5,                  # 5 retries with backoff
    retry_delay=2.0,               # Start with 2s delay
    retry_backoff=1.5,             # 1.5x backoff multiplier
    custom_headers={               # Custom API headers
        "X-API-Version": "v3",
        "X-Client-ID": "mcp-mesh"
    },
    auth_required=True,            # Require authentication
    streaming=True,                # Enable streaming responses
    stream_timeout=300,            # 5 minute stream timeout
    buffer_size=8192,              # 8KB streaming buffer
    accepts=["application/json", "text/event-stream"],
    max_response_size=50*1024*1024  # 50MB max response
)
def generate_ai_response(prompt: str, context: dict):
    return f"AI response for: {prompt}"
```

**System automatically creates enhanced client proxies with:**

- 120 second timeouts
- 5 retries with exponential backoff (2s, 3s, 4.5s, 6.75s, 10.125s)
- Custom headers for API versioning and client identification
- Bearer token authentication from environment
- Streaming responses for real-time data
- 50MB response size limits for safety

### Benefits of kwargs Enhancement

1. **Declarative Configuration**: Tool behavior specified at decoration time
2. **Automatic Client Optimization**: Proxies self-configure based on tool requirements
3. **Enhanced Reliability**: Built-in retries, timeouts, and error handling
4. **Protocol Flexibility**: Tools can specify their preferred communication parameters
5. **Backward Compatibility**: Existing tools continue working unchanged
6. **Production Ready**: Authentication, monitoring, and performance optimizations
7. **Developer Experience**: Simple, intuitive API with powerful capabilities

### Unit Testing Strategy

Each phase follows TDD principles with comprehensive unit test coverage (no integration tests):

#### Phase 1 Unit Tests

- **OpenAPI Schema Validation**: Test additionalProperties support in schema
- **Model Generation**: Test Python/Go model generation with kwargs support
- **Backward Compatibility**: Verify tools without kwargs continue working

#### Phase 2 Unit Tests

- **Database Storage**: Test kwargs JSON field storage (mocked database)
- **Ent Schema**: Test schema generation and validation
- **Migration**: Test migration logic (unit tests only)
- **Go Handler**: Test kwargs extraction from HTTP requests (mocked)

#### Phase 3 Unit Tests

- **Registry Service**: Test kwargs storage/retrieval with mocked database
- **Heartbeat Processing**: Test kwargs extraction from registration requests
- **JSON Handling**: Test various kwargs data types and edge cases
- **Error Handling**: Test malformed kwargs and validation

#### Phase 4 Unit Tests

- **Kwargs Parsing**: Test kwargs extraction from heartbeat responses (mocked)
- **Dependency Resolution**: Test kwargs passing to proxy creation (mocked)
- **JSON Conversion**: Test JSON string to dict parsing
- **Error Recovery**: Test graceful fallback for invalid kwargs

#### Phase 5 Unit Tests

- **Enhanced Proxy Configuration**: Test auto-configuration from kwargs
- **Retry Logic**: Test exponential backoff with mocked failures
- **Streaming Selection**: Test automatic streaming vs non-streaming choice
- **Header/Auth**: Test custom headers and authentication setup
- **Content Handling**: Test content type and size limit configuration

#### Unit Test Principles

- **Full Mocking**: Mock all external dependencies (database, HTTP, registry)
- **Isolated Testing**: Each component tested independently
- **Edge Case Coverage**: Test null, empty, malformed, and boundary values
- **Error Simulation**: Mock failures to test error handling paths
- **Performance Testing**: Test with large kwargs objects and edge cases

### Deployment Considerations

- **Database Migration**: Phase 3 requires PostgreSQL schema migration
- **Backward Compatibility**: All phases maintain compatibility with existing tools
- **Rolling Deployment**: Phases can be deployed incrementally
- **Monitoring**: Enhanced proxies provide detailed logging for observability
- **Security**: Authentication and authorization properly handled

This implementation creates a powerful declarative configuration system while maintaining the simplicity and elegance of the current `@mesh.tool` API.
