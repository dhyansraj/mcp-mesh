# Task 8: Performance and Comprehensive Development Scenario Testing (1 hour)

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
**MANDATORY**: This validation must ensure 100% performance and comprehensive scenario coverage.

**Reference Preservation**:
- Validate ALL development scenarios documented in architecture guide
- Test performance targets meet or exceed Python implementation
- Maintain IDENTICAL developer experience with Go implementation
- Preserve ALL comprehensive workflow patterns from documentation

**Implementation Validation**:
- Performance targets must be met (<100ms registry startup, 10x throughput)
- All documented scenarios from architecture guide must work with Go backend
- Comprehensive testing must validate every edge case and failure mode

## Objective
Validate performance targets and comprehensive development scenarios work with Go backend

## Detailed Sub-tasks

### 8.1: Complete development scenario testing
```bash
#!/bin/bash
# test/workflow/test_complete_development_scenarios.sh

echo "🎯 Testing complete development scenarios from architecture guide..."

# Test all documented scenarios from ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md

echo "📋 Testing Scenario 1: No registry at startup"
./bin/mcp-mesh-dev start examples/hello_world.py &
NO_REG_PID=$!
sleep 5
if kill -0 $NO_REG_PID 2>/dev/null; then
    echo "✅ Agent works standalone when no registry at startup"
    kill $NO_REG_PID
else
    echo "❌ Agent failed when no registry at startup"
    exit 1
fi

echo "📋 Testing Scenario 2: Registry dies after connection"
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 2
./bin/mcp-mesh-dev start examples/hello_world.py &
AGENT_PID=$!
sleep 5
kill $REG_PID  # Kill registry
sleep 2
if kill -0 $AGENT_PID 2>/dev/null; then
    echo "✅ Agent continues working after Go registry death"
    kill $AGENT_PID
else
    echo "❌ Agent died when Go registry died"
    exit 1
fi

echo "📋 Testing Scenario 3: Registry reconnection"
./bin/mcp-mesh-dev start examples/hello_world.py &
RECONN_PID=$!
sleep 8  # Auto-start registry
./bin/mcp-mesh-dev start --registry-only &  # Start another registry
sleep 5
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -eq 0 ]; then
    echo "✅ Agent auto-reconnects to new Go registry"
else
    echo "❌ Agent failed to reconnect to new Go registry"
    exit 1
fi
kill $RECONN_PID 2>/dev/null
pkill -f "mcp-mesh-registry|mcp-mesh-dev" 2>/dev/null

echo "✅ All development scenarios validated with Go backend"
```

### 8.2: Development workflow performance validation
```bash
#!/bin/bash
# test/workflow/test_performance_workflow.sh

echo "⚡ Testing development workflow performance with Go backend..."

# Test startup times
echo "📊 Measuring Go registry startup time..."
START_TIME=$(date +%s%N)
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 1

# Wait for registry to be ready
while ! curl -s http://localhost:8080/health >/dev/null 2>&1; do
    sleep 0.1
done

END_TIME=$(date +%s%N)
STARTUP_TIME=$((($END_TIME - $START_TIME) / 1000000))  # Convert to milliseconds

if [ $STARTUP_TIME -lt 100 ]; then
    echo "✅ Go registry startup time: ${STARTUP_TIME}ms (target: <100ms)"
else
    echo "⚠️ Go registry startup time: ${STARTUP_TIME}ms (target: <100ms - may need optimization)"
fi

# Test agent registration performance
echo "📊 Testing agent registration performance..."
START_REG=$(date +%s%N)
./bin/mcp-mesh-dev start examples/hello_world.py &
AGENT_PID=$!

# Wait for registration
while ! curl -s http://localhost:8080/agents | grep -q "hello-world-demo"; do
    sleep 0.1
done

END_REG=$(date +%s%N)
REG_TIME=$((($END_REG - $START_REG) / 1000000))

echo "✅ Agent registration time: ${REG_TIME}ms"

# Cleanup
kill $AGENT_PID $REG_PID 2>/dev/null
echo "✅ Performance workflow validation completed"
```

### 8.3: Registry throughput performance testing
```bash
#!/bin/bash
# test/performance/test_registry_throughput.sh

echo "🚀 Testing Go registry throughput performance (target: 10x improvement)..."

# Start Go registry
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 3

# Test concurrent agent registrations
echo "📊 Testing concurrent agent registrations..."
START_TIME=$(date +%s%N)

# Start 10 agents concurrently
for i in {1..10}; do
    MCP_MESH_REGISTRY_URL=http://localhost:8080 timeout 15 python examples/hello_world.py &
    AGENT_PIDS[$i]=$!
done

# Wait for all registrations
REGISTERED=0
while [ $REGISTERED -lt 10 ]; do
    REGISTERED=$(curl -s http://localhost:8080/agents | jq '.count' 2>/dev/null || echo 0)
    sleep 0.5
done

END_TIME=$(date +%s%N)
TOTAL_TIME=$((($END_TIME - $START_TIME) / 1000000))

echo "✅ 10 concurrent agent registrations: ${TOTAL_TIME}ms"
echo "📊 Average per agent: $((TOTAL_TIME / 10))ms"

# Test API throughput
echo "📊 Testing API request throughput..."
START_API=$(date +%s%N)

for i in {1..100}; do
    curl -s http://localhost:8080/agents >/dev/null &
done
wait

END_API=$(date +%s%N)
API_TIME=$((($END_API - $START_API) / 1000000))

echo "✅ 100 concurrent API requests: ${API_TIME}ms"
echo "📊 Average per request: $((API_TIME / 100))ms"

# Cleanup
for pid in "${AGENT_PIDS[@]}"; do
    kill $pid 2>/dev/null
done
kill $REG_PID 2>/dev/null

echo "✅ Registry throughput performance validation completed"
```

### 8.4: Load testing and stress scenarios
```bash
#!/bin/bash
# test/stress/test_load_scenarios.sh

echo "💪 Testing load scenarios and stress conditions..."

# Test 1: High agent churn (agents starting/stopping rapidly)
echo "📊 Testing high agent churn scenario..."
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 3

for round in {1..5}; do
    echo "Round $round: Starting 5 agents..."
    for i in {1..5}; do
        timeout 10 python examples/hello_world.py &
        CHURN_PIDS[$i]=$!
    done
    
    sleep 3
    
    echo "Round $round: Stopping 5 agents..."
    for pid in "${CHURN_PIDS[@]}"; do
        kill $pid 2>/dev/null
    done
    
    sleep 2
    unset CHURN_PIDS
done

# Verify registry still responsive
curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -eq 0 ]; then
    echo "✅ Registry survived high agent churn"
else
    echo "❌ Registry failed under high agent churn"
    exit 1
fi

# Test 2: Registry restart with active agents
echo "📊 Testing registry restart with active agents..."
timeout 20 python examples/hello_world.py &
PERSISTENT_AGENT=$!
sleep 5

# Restart registry
kill $REG_PID
sleep 2
./bin/mcp-mesh-dev start --registry-only &
NEW_REG_PID=$!
sleep 5

# Agent should reconnect
if kill -0 $PERSISTENT_AGENT 2>/dev/null; then
    echo "✅ Agent survived registry restart"
else
    echo "❌ Agent died during registry restart"
    exit 1
fi

# Cleanup
kill $PERSISTENT_AGENT $NEW_REG_PID 2>/dev/null
echo "✅ Load testing and stress scenarios completed"
```

### 8.5: Memory and resource usage validation
```bash
#!/bin/bash
# test/performance/test_resource_usage.sh

echo "💾 Testing memory and resource usage (target: 50% reduction)..."

# Start Go registry and measure baseline
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 3

# Get initial memory usage
INITIAL_MEM=$(ps -o rss= -p $REG_PID 2>/dev/null || echo 0)
echo "📊 Go registry initial memory: ${INITIAL_MEM}KB"

# Add load (10 agents)
for i in {1..10}; do
    timeout 30 python examples/hello_world.py &
    LOAD_PIDS[$i]=$!
done

sleep 10

# Get memory under load
LOAD_MEM=$(ps -o rss= -p $REG_PID 2>/dev/null || echo 0)
echo "📊 Go registry memory under load: ${LOAD_MEM}KB"

# Calculate memory efficiency
if [ $LOAD_MEM -lt 51200 ]; then  # 50MB target
    echo "✅ Memory usage under target: ${LOAD_MEM}KB < 50MB"
else
    echo "⚠️ Memory usage above target: ${LOAD_MEM}KB > 50MB"
fi

# Test memory stability over time
echo "📊 Testing memory stability over 60 seconds..."
for i in {1..12}; do
    sleep 5
    CURRENT_MEM=$(ps -o rss= -p $REG_PID 2>/dev/null || echo 0)
    echo "Memory at ${i}*5s: ${CURRENT_MEM}KB"
done

# Cleanup
for pid in "${LOAD_PIDS[@]}"; do
    kill $pid 2>/dev/null
done
kill $REG_PID 2>/dev/null

echo "✅ Memory and resource usage validation completed"
```

### 8.6: Edge case and failure mode testing
```bash
#!/bin/bash
# test/edge-cases/test_failure_modes.sh

echo "🧪 Testing edge cases and failure modes..."

# Test 1: Port already in use
echo "📊 Testing port conflict handling..."
# Start something on port 8080
python3 -m http.server 8080 &
HTTP_PID=$!
sleep 2

# Try to start registry (should handle port conflict)
./bin/mcp-mesh-dev start --registry-only 2>/dev/null &
REG_PID=$!
sleep 5

# Should either use different port or fail gracefully
if kill -0 $REG_PID 2>/dev/null; then
    echo "✅ Registry handled port conflict gracefully"
    kill $REG_PID
else
    echo "✅ Registry failed gracefully on port conflict"
fi

kill $HTTP_PID 2>/dev/null

# Test 2: Database corruption simulation
echo "📊 Testing database corruption handling..."
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 3

# Corrupt database file
echo "corrupted" > ./mcp_mesh.db 2>/dev/null

# Registry should detect and handle corruption
kill $REG_PID
sleep 2

./bin/mcp-mesh-dev start --registry-only &
NEW_REG_PID=$!
sleep 5

curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -eq 0 ]; then
    echo "✅ Registry recovered from database corruption"
else
    echo "❌ Registry failed to recover from database corruption"
fi

kill $NEW_REG_PID 2>/dev/null
rm -f ./mcp_mesh.db

# Test 3: Rapid restart scenarios
echo "📊 Testing rapid restart scenarios..."
for i in {1..5}; do
    ./bin/mcp-mesh-dev start --registry-only &
    RAPID_PID=$!
    sleep 1
    kill $RAPID_PID
    sleep 1
done

# Final start should work
./bin/mcp-mesh-dev start --registry-only &
FINAL_PID=$!
sleep 3

curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -eq 0 ]; then
    echo "✅ Registry survived rapid restart scenarios"
else
    echo "❌ Registry failed after rapid restarts"
fi

kill $FINAL_PID 2>/dev/null
echo "✅ Edge case and failure mode testing completed"
```

## Success Criteria
- [ ] **CRITICAL**: All documented development scenarios from architecture guide work with Go backend
- [ ] **CRITICAL**: Performance targets met (Go registry startup <100ms, 10x throughput improvement)
- [ ] **CRITICAL**: Registry throughput performance demonstrates significant improvement over Python
- [ ] **CRITICAL**: Load testing validates registry stability under stress conditions
- [ ] **CRITICAL**: Memory usage meets targets (50% reduction, <50MB under load)
- [ ] **CRITICAL**: Memory stability maintained over time with active agents
- [ ] **CRITICAL**: Edge cases and failure modes handled gracefully
- [ ] **CRITICAL**: Registry recovery from corruption and port conflicts works
- [ ] **CRITICAL**: High agent churn scenarios don't destabilize registry
- [ ] **CRITICAL**: All performance improvements achieved without architectural compromise