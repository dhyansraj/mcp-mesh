# Status Change Detection Implementation Plan

## Overview

Replace the current health monitor timer-based approach with a status-change-driven system that only creates registry events when actual status transitions occur. This eliminates the logic overlap issue where unhealthy events are created for agents that are already healthy.

## Current System Analysis

### 1. **Ent ORM System**

- **Database Support**: SQLite (development) and PostgreSQL (production)
- **Schema Management**: Uses Ent ORM with code-generated schemas in `/src/core/ent/schema/`
- **Migrations**: Automatic schema creation via `migrate.WithGlobalUniqueID(true)`
- **Transactions**: Built-in transaction support with rollback capabilities

### 2. **Existing Hook/Trigger System**

- **Ent Hooks**: Full hook system available in `/src/core/ent/hook/hook.go`
- **Hook Types**: AgentFunc, CapabilityFunc, RegistryEventFunc with mutation context
- **Conditions**: Support for conditional hooks (And, Or, Not, HasOp, HasFields, etc.)
- **Operations**: Can hook on Create, Update, Delete, UpdateOne operations

### 3. **Current Status Change Detection**

- **Health Monitor**: `/src/core/registry/health_monitor.go` - background process that detects unhealthy agents
- **Status Transitions**: Manual status updates in service layer with event creation
- **Registry Events**: Existing event system for `register`, `heartbeat`, `expire`, `update`, `unregister`, `unhealthy`

### 4. **Agent Schema Structure**

```go
// Agent status field
field.Enum("status").
    Values("healthy", "unhealthy", "unknown").
    Default("healthy")
```

### 5. **Existing Status Change Patterns**

- Health monitor marks agents unhealthy and creates events
- Service layer handles status recovery (unhealthy → healthy)
- Manual event creation in transactions
- No automatic triggers for status changes

## Implementation Plan

### **Approach: Ent Hooks for Status Change Detection**

#### **Phase 1: Create Status Change Hook System**

1. **Create new hook file**: `/src/core/registry/status_hooks.go`
2. **Implement AgentStatusChangeHook** that:
   - Detects when `status` field changes during Agent updates
   - Extracts old vs new status values from mutation
   - Creates appropriate RegistryEvent records
   - Handles all status transitions (healthy↔unhealthy↔unknown)

#### **Phase 2: Hook Registration & Integration**

1. **Register hooks in EntService initialization**
2. **Add hook to Agent schema** via `Hooks()` method
3. **Ensure compatibility** with existing health monitor and service patterns

#### **Phase 3: Event Enhancement**

1. **Enhance event data** with transition details (old_status, new_status, reason)
2. **Maintain backward compatibility** with existing event consumers
3. **Add status change timestamps** and audit trail

#### **Phase 4: Refactor Health Monitor**

1. **Simplify health monitor** to only update agent status (no event creation)
2. **Use SQL UPDATE with WHERE clause** for efficient status updates:
   ```sql
   UPDATE agents
   SET status = 'unhealthy', updated_at = NOW()
   WHERE updated_at < (NOW() - INTERVAL '20 seconds')
   AND status != 'unhealthy'
   ```
3. **Let hooks automatically create events** when status changes
4. **Remove manual event creation** from health monitor

#### **Phase 5: Testing & Validation**

1. **Unit tests** for hook functionality
2. **Integration tests** with existing status change scenarios
3. **Verify no duplicate events** with existing manual event creation
4. **Performance testing** for hook overhead

### **Technical Advantages of This Approach**

- **Database-agnostic**: Works with both SQLite and PostgreSQL
- **Transaction-safe**: Hooks execute within existing transactions
- **Type-safe**: Leverages Ent's type system and mutation detection
- **Non-intrusive**: Doesn't require changes to existing service logic
- **Automatic**: Triggers on any status change regardless of update path

### **Key Benefits**

- **Comprehensive coverage**: Catches all status changes, not just health monitor
- **Audit trail**: Automatic event creation for compliance/debugging
- **Real-time detection**: Immediate event creation on status transitions
- **Maintainable**: Uses existing Ent patterns and infrastructure

## Database Query Optimization

### **Efficient Status Updates**

Instead of querying and then updating individual agents, use batch updates:

```sql
-- SQLite
UPDATE agents
SET status = 'unhealthy', updated_at = datetime('now')
WHERE updated_at < datetime('now', '-20 seconds')
AND status != 'unhealthy';

-- PostgreSQL
UPDATE agents
SET status = 'unhealthy', updated_at = NOW()
WHERE updated_at < (NOW() - INTERVAL '20 seconds')
AND status != 'unhealthy';
```

### **Hook-Triggered Events**

- Only agents whose status actually changes will trigger hooks
- No duplicate events for already-unhealthy agents
- Automatic event creation with proper context

## Migration Strategy

### **Step 1: Implement Hooks (Non-Breaking)**

- Add status change hooks alongside existing system
- Test hook functionality without affecting current behavior

### **Step 2: Enable Hook Events**

- Start creating events via hooks
- Keep existing manual event creation for comparison

### **Step 3: Refactor Health Monitor**

- Remove manual event creation from health monitor
- Use efficient batch status updates
- Rely on hooks for event creation

### **Step 4: Clean Up**

- Remove redundant event creation code
- Simplify health monitor logic
- Update tests and documentation

## Expected Outcomes

1. **Eliminate duplicate events**: Only create events when status actually changes
2. **Better performance**: Efficient batch updates instead of individual queries
3. **Cleaner code**: Separation of concerns between status updates and event creation
4. **Audit compliance**: Comprehensive status change tracking
5. **Debugging ease**: Clear event trail for all status transitions

## Files to Modify

- `/src/core/registry/status_hooks.go` - New hook implementation
- `/src/core/registry/health_monitor.go` - Simplified health monitoring
- `/src/core/ent/schema/agent.go` - Add hooks to schema
- `/src/core/registry/ent_service.go` - Hook registration
- Tests and documentation updates

## Success Criteria

- [ ] No duplicate unhealthy events for already-unhealthy agents
- [ ] All status transitions automatically create appropriate events
- [ ] Performance improvement in health monitoring
- [ ] Backward compatibility maintained
- [ ] Comprehensive test coverage
