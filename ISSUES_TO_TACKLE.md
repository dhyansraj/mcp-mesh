# MCP Mesh Issues to Tackle

## Issue 1: Agent List Not Showing Both Agents
**Problem**: If second command connected to same registry, why didn't we get both agents in the list command?

**Details**:
- [ ] Registry detection is working (agents connect to same registry)
- [ ] But `mcp_mesh_dev list` shows agents as "Running (Unregistered)" 
- [ ] Auto-registration mechanism should register agents with shared registry
- [ ] Multiple CLI sessions should see all agents registered with shared registry

**Expected Behavior**:
```bash
# Session 1
mcp_mesh_dev start --registry-only

# Session 2  
mcp_mesh_dev start examples/hello_world.py

# Session 3
mcp_mesh_dev start examples/system_agent.py

# Any session should show both agents
mcp_mesh_dev list
# Should show: hello_world (Registered), system_agent (Registered)
```

## Issue 2: Original Design - Curl Support for Agent Testing
**Problem**: Original design said curl was possible and we put that in documentation. Not sure how it was going to be done.

**Details**:
- [ ] Documentation mentions curl support for testing agents
- [ ] Current agents use stdio transport (MCP protocol standard)
- [ ] Need to clarify how curl testing was supposed to work
- [ ] Possible solutions:
  1. Agent HTTP endpoints for testing (separate from MCP stdio)
  2. Registry proxy endpoints that forward to agents
  3. Registry API to invoke agent functions via HTTP
  4. MCP-over-HTTP transport option

**Clarification from Documentation**:
- [ ] curl is for **registry API testing**, not direct agent testing
- [ ] Registry provides REST endpoints: `/agents/list`, `/capabilities`, `/heartbeat`
- [ ] Agents use MCP protocol over stdio (no HTTP endpoints)
- [ ] CLI should output registry curl examples for testing registration/discovery

**Expected curl Examples**:
```bash
# List all registered agents
curl http://localhost:8080/agents/list

# Search for capabilities
curl http://localhost:8080/capabilities?category=greeting

# Check specific agent
curl http://localhost:8080/agents/{agent_id}
```

## Issue 3: Registry Shutdown When Agent Stops
**Problem**: Registry gets terminated when individual agent processes stop.

**Details**:
- [ ] Started registry with `--registry-only`
- [ ] Started hello_world agent connecting to existing registry  
- [ ] When hello_world agent stopped (Ctrl+C), it also terminated the registry
- [ ] This breaks the shared registry model - registry should persist independently

**Expected Behavior**:
- [ ] Registry should run independently of agents
- [ ] Stopping individual agents should not affect registry
- [ ] Registry should only stop when explicitly requested or system shutdown

## Issue 4: Registry Independence - Graceful Degradation
**Problem**: Ensure agents work independently of registry availability (like Kubernetes pods without API server).

**Architecture Principles**:
- [ ] **Registry is optional**: Agents must function standalone if registry unavailable at startup
- [ ] **Graceful degradation**: If registry goes down after agents are connected, agents continue working
- [ ] **Self-healing**: Agents keep trying to reconnect to registry but never die due to registry failure
- [ ] **Local capability**: If agent can process request locally, it works without registry
- [ ] **Mesh connectivity**: Agents that found each other via registry remain connected even if registry dies

**Current Issues to Verify**:
- [ ] Do agents start successfully when no registry is available?
- [ ] Do agents survive registry crashes/restarts?
- [ ] Is auto-registration non-blocking and failure-tolerant?
- [ ] Can agents maintain discovered connections after registry failure?

**Expected Behavior**:
```bash
# Scenario 1: No registry at startup
mcp_mesh_dev start examples/hello_world.py  # Should work standalone

# Scenario 2: Registry dies after connection
mcp_mesh_dev start --registry-only &
mcp_mesh_dev start examples/hello_world.py  # Connects to registry
# Kill registry process
# hello_world should continue working

# Scenario 3: Registry reconnection
# Start new registry
# hello_world should auto-reconnect and re-register
```

## Issue 5: CLI Always Starts Registry Instead of Connect-Only Mode
**Problem**: CLI doesn't have "connect-only" mode to connect agents to external registry.

**Current Behavior**:
- [ ] `mcp_mesh_dev start agent.py` always tries to start its own registry
- [ ] Environment variable `MCP_MESH_REGISTRY_URL` is ignored by CLI  
- [ ] No way to connect agents to external registry (e.g., production K8s registry)

**Missing CLI Options**:
```bash
# Should be possible:
mcp_mesh_dev start agent.py --registry-url http://prod-registry:8080 --connect-only
mcp_mesh_dev start agent.py --no-registry  # Agent-only mode
```

**Use Cases**:
- [ ] Connect to production registry in K8s environment
- [ ] Connect to external shared registry instance
- [ ] Pure agent mode for testing without registry dependency

## Issue 6: CLI List Command Kills Registry and Agents
**Problem**: When running `mcp_mesh_dev list`, it terminates registry and agents after a few seconds instead of just listing services and exiting.

**Details**:
- [ ] `mcp_mesh_dev list` should be a read-only operation
- [ ] Should list all running services and exit immediately
- [ ] Currently kills registry and agent processes unintentionally
- [ ] This breaks the workflow of checking service status

**Expected Behavior**:
```bash
# Should just list and exit
mcp_mesh_dev list
# Expected output:
# Registry: Running on port 8080
# Agents:
#   - hello_world: Running (Registered)
#   - system_agent: Running (Registered)
# (command exits, services continue running)
```

## Additional Investigation Needed

### Registry State Persistence
- [ ] Check if registry state is properly shared between CLI sessions
- [ ] Verify process tracking works across multiple CLI invocations
- [ ] Ensure auto-registration actually reaches the registry

### Agent Registration Flow  
- [ ] Verify auto-enhancement triggers in subprocess agents
- [ ] Check if HTTP POST to `/agents/register_with_metadata` succeeds
- [ ] Debug why agents show as "Unregistered" despite registry connection

### Documentation Alignment
- [ ] Review original design documents for curl usage patterns
- [ ] Clarify transport layer architecture (stdio vs HTTP)
- [ ] Update documentation to match actual implementation