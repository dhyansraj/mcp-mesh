# SQL Compatibility Analysis: SQLite vs PostgreSQL

## Overview
This document identifies all locations in the Go codebase that require changes to support both SQLite (for local/Docker) and PostgreSQL (for Kubernetes) using the same codebase.

## Summary of Required Changes
- **6 Go files** need modifications
- **25+ SQL statements** need database-specific versions
- **3 main categories** of differences: auto-increment, parameters, and SQLite-specific features

---

## 1. Core Database Files

### `/src/core/database/database.go`

#### **Schema Creation (Lines 145, 162, 177)**
**Current Issue**: Uses variable `{autoIncrement}` placeholder
```sql
-- Current template
CREATE TABLE IF NOT EXISTS capabilities (
    id {autoIncrement},  -- ❌ Template placeholder
    ...
)
```

**Required Fix**:
```sql
-- SQLite version
CREATE TABLE IF NOT EXISTS capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ...
)

-- PostgreSQL version  
CREATE TABLE IF NOT EXISTS capabilities (
    id SERIAL PRIMARY KEY,
    ...
)
```

#### **Parameter Syntax (Lines 231-233, 236)**
**Current Issue**: Mixed parameter syntax
```sql
-- Current (Working for PostgreSQL)
insertSQL = "INSERT INTO schema_version (version, applied_at) VALUES ($1, $2)"

-- Current (Working for SQLite)  
insertSQL = "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)"
```

**Required Fix**: Extend existing detection pattern to all queries

#### **SQLite PRAGMA Statements (Lines 89-94)**
**Current Issue**: Applied to all databases
```sql
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = %d  
PRAGMA journal_mode = %s
PRAGMA synchronous = %s
PRAGMA cache_size = -%d
```

**Required Fix**: Only apply to SQLite connections

---

## 2. Registry Service Files

### `/src/core/registry/service.go`

#### **Agent Existence Check (Line 167)**
```sql
-- Current (SQLite syntax)
SELECT agent_id FROM agents WHERE agent_id = ?

-- PostgreSQL version needed
SELECT agent_id FROM agents WHERE agent_id = $1
```

#### **Agent Update Statement (Lines 251-256)**
```sql
-- Current (Multi-parameter SQLite)
UPDATE agents SET 
    name = ?, version = ?, http_host = ?, http_port = ?, 
    total_dependencies = ?, dependencies_resolved = ?, updated_at = ?
WHERE agent_id = ?

-- PostgreSQL version needed
UPDATE agents SET 
    name = $1, version = $2, http_host = $3, http_port = $4,
    total_dependencies = $5, dependencies_resolved = $6, updated_at = $7
WHERE agent_id = $8
```

#### **Agent Insert Statement (Lines 259-264)**
```sql
-- Current (SQLite syntax)
INSERT INTO agents (agent_id, agent_type, name, version, http_host, http_port, namespace, total_dependencies, dependencies_resolved, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

-- PostgreSQL version needed  
INSERT INTO agents (agent_id, agent_type, name, version, http_host, http_port, namespace, total_dependencies, dependencies_resolved, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
```

#### **Heartbeat Check (Line 327)**
```sql
-- Current (SQLite syntax)
SELECT agent_id FROM agents WHERE agent_id = ?

-- PostgreSQL version needed
SELECT agent_id FROM agents WHERE agent_id = $1
```

#### **Dynamic Update Query (Line 439)**
**Complex case**: Dynamically built UPDATE with variable parameters
- Need parameter counting and conversion

#### **Heartbeat Update (Lines 501-519)**
```sql
-- Current (SQLite syntax)
UPDATE agents SET updated_at = ? WHERE agent_id = ?

-- PostgreSQL version needed
UPDATE agents SET updated_at = $1 WHERE agent_id = $2
```

---

## 3. Capability Management

### `/src/core/registry/service_capabilities.go`

#### **Capability Deletion (Line 25)**
```sql
-- Current (SQLite syntax)
DELETE FROM capabilities WHERE agent_id = ?

-- PostgreSQL version needed
DELETE FROM capabilities WHERE agent_id = $1
```

#### **Capability Insert (Lines 59-62)**
```sql
-- Current (SQLite syntax)
INSERT INTO capabilities (agent_id, function_name, capability, version, description, tags, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)

-- PostgreSQL version needed
INSERT INTO capabilities (agent_id, function_name, capability, version, description, tags, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
```

#### **Capability Query (Lines 74-76)**
```sql
-- Current (SQLite syntax)
SELECT agent_id, function_name, capability, version, description, tags FROM capabilities WHERE agent_id = ?

-- PostgreSQL version needed
SELECT agent_id, function_name, capability, version, description, tags FROM capabilities WHERE agent_id = $1
```

---

## 4. Dependency Resolution

### `/src/core/registry/dependency_resolver.go`

#### **Provider Query (Lines 145-152)**
**Current Issue**: SQLite datetime functions
```sql
-- Current (SQLite-specific datetime functions)
SELECT c.agent_id, c.function_name, c.capability, c.version, c.tags,
       a.http_host, a.http_port, a.updated_at
FROM capabilities c
JOIN agents a ON c.agent_id = a.agent_id
WHERE c.capability = ?
AND datetime(a.updated_at, '+' || ? || ' seconds') > datetime('now')
ORDER BY a.updated_at DESC

-- PostgreSQL version needed
SELECT c.agent_id, c.function_name, c.capability, c.version, c.tags,
       a.http_host, a.http_port, a.updated_at
FROM capabilities c
JOIN agents a ON c.agent_id = a.agent_id
WHERE c.capability = $1
AND a.updated_at + INTERVAL '$2 seconds' > NOW()
ORDER BY a.updated_at DESC
```

---

## 5. Decorator Handlers

### `/src/core/registry/decorator_handlers.go`

#### **INSERT OR REPLACE (Lines 213-232)**
**Current Issue**: SQLite-specific syntax
```sql
-- Current (SQLite-specific)
INSERT OR REPLACE INTO agents (id, agent_id, name, version, endpoint, status, total_dependencies, dependencies_resolved, last_heartbeat, registered_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

-- PostgreSQL version needed (use UPSERT)
INSERT INTO agents (id, agent_id, name, version, endpoint, status, total_dependencies, dependencies_resolved, last_heartbeat, registered_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (agent_id) DO UPDATE SET
    name = EXCLUDED.name,
    version = EXCLUDED.version,
    endpoint = EXCLUDED.endpoint,
    status = EXCLUDED.status,
    total_dependencies = EXCLUDED.total_dependencies,
    dependencies_resolved = EXCLUDED.dependencies_resolved,
    last_heartbeat = EXCLUDED.last_heartbeat,
    updated_at = EXCLUDED.updated_at
```

#### **Tool Operations (Lines 240, 254-268)**
Multiple parameter conversion needed

---

## 6. Tool Management  

### `/src/core/registry/service_tools.go`

#### **Tool Deletion (Line 29)**
```sql
-- Current (SQLite syntax)
DELETE FROM tools WHERE agent_id = ?

-- PostgreSQL version needed
DELETE FROM tools WHERE agent_id = $1
```

#### **Tool Insert (Lines 79-82)**
Multiple parameter conversion needed

---

## Implementation Strategy

### **Quick Fix Approach**

1. **Extend Existing Pattern** (database.go lines 227-234)
   ```go
   isPostgreSQL := strings.HasPrefix(db.config.DatabaseURL, "postgres://") || 
                   strings.HasPrefix(db.config.DatabaseURL, "postgresql://")
   ```

2. **Create Helper Functions**
   ```go
   func (db *Database) getParameterPlaceholder(position int) string {
       if db.isPostgreSQL {
           return fmt.Sprintf("$%d", position)
       }
       return "?"
   }
   
   func (db *Database) buildParameterList(count int) string {
       // Returns "?, ?, ?" or "$1, $2, $3"
   }
   ```

3. **Query Builder Functions**
   ```go
   func (db *Database) getAgentExistsQuery() string {
       if db.isPostgreSQL {
           return "SELECT agent_id FROM agents WHERE agent_id = $1"
       }
       return "SELECT agent_id FROM agents WHERE agent_id = ?"
   }
   ```

### **Files Requiring Changes**
1. `/src/core/database/database.go` - **HIGH PRIORITY**
2. `/src/core/registry/service.go` - **HIGH PRIORITY** 
3. `/src/core/registry/service_capabilities.go` - **MEDIUM**
4. `/src/core/registry/dependency_resolver.go` - **MEDIUM**
5. `/src/core/registry/decorator_handlers.go` - **MEDIUM**
6. `/src/core/registry/service_tools.go` - **LOW**

### **Testing Strategy**
- Verify SQLite works with Docker Compose and local development
- Verify PostgreSQL works with Kubernetes deployment  
- Ensure no regression in existing functionality
- Test all CRUD operations for both database types

### **Estimated Effort**
- **Quick Fix**: 2-4 hours
- **Comprehensive Testing**: 1-2 hours
- **Documentation Update**: 30 minutes

---

## Next Steps
1. Implement helper functions in `database.go`
2. Update high-priority service files first
3. Test with both SQLite and PostgreSQL
4. Verify Kubernetes deployment works end-to-end