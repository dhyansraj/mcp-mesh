# Task 7: Development Workflow Validation (1 hour)

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
**MANDATORY**: This validation must ensure 100% preservation of development workflow patterns.

**Reference Preservation**:
- Validate ALL development scenarios documented in architecture guide
- Test EVERY multi-shell workflow pattern with Go backend
- Maintain IDENTICAL developer experience with Go implementation
- Preserve ALL Python decorator functionality in workflow scenarios

**Implementation Validation**:
- Development workflows must work identically with Go registry
- Multi-shell scenarios must preserve agent independence and dependency injection
- Auto-registry-start patterns must work with Go registry embedding

## Objective
Validate the complete development workflow scenarios work identically with Go backend

## Detailed Sub-tasks

### 7.1: Multi-shell development workflow validation
```bash
#!/bin/bash
# test/workflow/test_3_shell_development.sh

echo "🔧 Testing 3-shell development workflow with Go backend..."

# Test Scenario: Standard Development Workflow
echo "📋 Scenario 1: Registry-first development workflow"

# Shell 1: Start Go registry only
echo "🗄️ Shell 1: Starting Go registry..."
./bin/mcp-mesh-dev start --registry-only &
REGISTRY_PID=$!
sleep 3

# Verify registry is running
curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -ne 0 ]; then
    echo "❌ Go registry failed to start"
    exit 1
fi
echo "✅ Go registry running on port 8080"

# Shell 2: Start first Python agent connecting to existing Go registry
echo "🐍 Shell 2: Starting hello_world.py agent..."
MCP_MESH_REGISTRY_URL=http://localhost:8080 timeout 10 python examples/hello_world.py &
AGENT1_PID=$!
sleep 5

# Verify agent registration with Go registry
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -ne 0 ]; then
    echo "❌ hello_world.py failed to register with Go registry"
    exit 1
fi
echo "✅ hello_world.py registered with Go registry"

# Shell 3: Start second Python agent connecting to existing Go registry
echo "🔧 Shell 3: Starting system_agent.py..."
MCP_MESH_REGISTRY_URL=http://localhost:8080 timeout 10 python examples/system_agent.py &
AGENT2_PID=$!
sleep 5

# Verify second agent registration
curl -s http://localhost:8080/agents | grep -q "system-agent"
if [ $? -ne 0 ]; then
    echo "❌ system_agent.py failed to register with Go registry"
    exit 1
fi
echo "✅ system_agent.py registered with Go registry"

# Test cross-shell dependency injection
echo "🔄 Testing cross-shell dependency injection..."
AGENT_COUNT=$(curl -s http://localhost:8080/agents | jq '.count')
if [ "$AGENT_COUNT" -ge 2 ]; then
    echo "✅ Cross-shell dependency injection ready (both agents registered)"
else
    echo "❌ Cross-shell dependency injection failed ($AGENT_COUNT agents registered)"
    exit 1
fi

# Cleanup
kill $AGENT1_PID $AGENT2_PID $REGISTRY_PID 2>/dev/null
echo "✅ 3-shell development workflow validated with Go backend"
```

### 7.2: Auto-registry-start workflow validation
```bash
#!/bin/bash
# test/workflow/test_auto_registry_start.sh

echo "🚀 Testing auto-registry-start workflow with Go backend..."

# Ensure no registry is running
pkill -f "mcp-mesh-registry\|mcp-mesh-dev" 2>/dev/null
sleep 2

# Test Scenario: Agent Auto-Starts Go Registry
echo "📋 Scenario 2: Auto-registry-start workflow"

# Start Python agent when no registry running (should auto-start Go registry)
echo "🐍 Starting hello_world.py with auto-registry-start..."
./bin/mcp-mesh-dev start examples/hello_world.py &
AUTO_AGENT_PID=$!
sleep 8  # Allow time for auto-registry-start + agent registration

# Verify Go registry was auto-started
curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -ne 0 ]; then
    echo "❌ Go registry was not auto-started by agent"
    exit 1
fi
echo "✅ Go registry auto-started successfully"

# Verify agent registered with auto-started Go registry
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -ne 0 ]; then
    echo "❌ Agent failed to register with auto-started Go registry"
    exit 1
fi
echo "✅ Agent registered with auto-started Go registry"

# Start second agent connecting to auto-started Go registry
echo "🔧 Starting system_agent.py connecting to auto-started registry..."
./bin/mcp-mesh-dev start examples/system_agent.py &
SECOND_AGENT_PID=$!
sleep 5

# Verify second agent registration
curl -s http://localhost:8080/agents | grep -q "system-agent"
if [ $? -ne 0 ]; then
    echo "❌ Second agent failed to connect to auto-started Go registry"
    exit 1
fi
echo "✅ Second agent connected to auto-started Go registry"

# Cleanup
kill $AUTO_AGENT_PID $SECOND_AGENT_PID 2>/dev/null
pkill -f "mcp-mesh-registry\|mcp-mesh-dev" 2>/dev/null
echo "✅ Auto-registry-start workflow validated with Go backend"
```

### 7.3: Agent independence and graceful degradation validation
```bash
#!/bin/bash
# test/workflow/test_agent_independence.sh

echo "🛡️ Testing agent independence and graceful degradation with Go backend..."

# Start Go registry and agent
./bin/mcp-mesh-dev start --registry-only &
REGISTRY_PID=$!
sleep 3

./bin/mcp-mesh-dev start examples/hello_world.py &
AGENT_PID=$!
sleep 5

# Verify initial connection
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -ne 0 ]; then
    echo "❌ Initial agent registration failed"
    exit 1
fi
echo "✅ Agent initially connected to Go registry"

# Kill Go registry to test graceful degradation
echo "🔥 Killing Go registry to test graceful degradation..."
kill $REGISTRY_PID
sleep 3

# Agent should continue running (graceful degradation)
if kill -0 $AGENT_PID 2>/dev/null; then
    echo "✅ Agent survived Go registry failure (graceful degradation)"
else
    echo "❌ Agent died when Go registry failed"
    exit 1
fi

# Restart Go registry to test reconnection
echo "🔄 Restarting Go registry to test auto-reconnection..."
./bin/mcp-mesh-dev start --registry-only &
NEW_REGISTRY_PID=$!
sleep 5

# Agent should auto-reconnect and re-register
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -eq 0 ]; then
    echo "✅ Agent auto-reconnected and re-registered with new Go registry"
else
    echo "❌ Agent failed to auto-reconnect to new Go registry"
    exit 1
fi

# Cleanup
kill $AGENT_PID $NEW_REGISTRY_PID 2>/dev/null
echo "✅ Agent independence and graceful degradation validated"
```


## Success Criteria
- [ ] **CRITICAL**: 3-shell development workflow works identically with Go backend
- [ ] **CRITICAL**: Auto-registry-start workflow preserves Python agent functionality  
- [ ] **CRITICAL**: Agent independence patterns work with Go registry (startup, death, reconnection)
- [ ] **CRITICAL**: Graceful degradation preserved when Go registry becomes unavailable
- [ ] **CRITICAL**: Cross-shell dependency injection works via Go registry
- [ ] **CRITICAL**: Python decorator functionality remains identical in all workflow scenarios
- [ ] **CRITICAL**: Developer experience is preserved - no workflow changes required
- [ ] **CRITICAL**: Core workflow patterns from architecture guide validated with Go implementation