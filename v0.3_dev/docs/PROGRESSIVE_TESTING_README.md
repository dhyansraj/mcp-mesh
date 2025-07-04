# Progressive Implementation Testing with Docker Compose

This testing setup allows for fast iteration and realistic multi-agent testing of the MCP Mesh enhanced HTTP wrapper implementation.

## 🚀 **Why Docker Compose for Testing?**

### **Fast Iteration**

- ✅ **Volume mounts** - No image rebuilding needed
- ✅ **Live code reload** - Edit Python code and test immediately
- ✅ **One command** - Start entire distributed environment
- ✅ **Realistic networking** - Actual container-to-container communication

### **Real Multi-Agent Testing**

- ✅ **Session affinity** - Test actual pod-to-pod forwarding
- ✅ **Registry coordination** - Test real service discovery
- ✅ **Network isolation** - Realistic container networking
- ✅ **Parallel development** - Multiple agents with different capabilities

## 📋 **Prerequisites**

```bash
# Required tools
docker-compose --version  # >= 1.29
jq --version              # for JSON parsing in tests

# Build registry image (one time)
cd src/registry
docker build -t mcpmesh/registry:latest .
```

## 🔄 **Quick Start**

### **1. Start Testing Environment**

```bash
# Start all services (registry + 3 agents + redis)
./test-progressive-phases.sh setup

# Verify environment is healthy
curl http://localhost:8000/health  # Registry
curl http://localhost:8080/health  # Agent A (session agent)
curl http://localhost:8081/health  # Agent B (session agent)
curl http://localhost:8082/health  # Agent C (introspection agent)
```

### **2. Test Individual Phases**

```bash
# Test specific phase
./test-progressive-phases.sh 1    # Phase 1: Metadata endpoint
./test-progressive-phases.sh 2    # Phase 2: Full MCP protocol
./test-progressive-phases.sh 4    # Phase 4: Session affinity

# Run all tests
./test-progressive-phases.sh all
```

### **3. Iterate on Code**

```bash
# Edit code in src/runtime/python/
vim src/runtime/python/_mcp_mesh/engine/http_wrapper.py

# Test immediately (no rebuild needed!)
./test-progressive-phases.sh 3
```

### **4. Cleanup**

```bash
./test-progressive-phases.sh cleanup
```

## 🏗️ **Environment Architecture**

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Network                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Registry   │  │   Redis     │  │             │        │
│  │ :8000       │  │ :6379       │  │             │        │
│  └─────────────┘  └─────────────┘  │             │        │
│         │                 │        │             │        │
│         └─────────┬───────┘        │             │        │
│                   │                │             │        │
│  ┌─────────────┐  │  ┌─────────────┐│ ┌─────────────┐      │
│  │  Agent A    │  │  │  Agent B    ││ │  Agent C    │      │
│  │(Session)    │  │  │(Session)    ││ │(Introspect) │      │
│  │:8080        │  │  │:8081        ││ │:8082        │      │
│  │             │  │  │             ││ │             │      │
│  │POD_IP=      │  │  │POD_IP=      ││ │POD_IP=      │      │
│  │agent-a      │  │  │agent-b      ││ │agent-c      │      │
│  └─────────────┘  │  └─────────────┘│ └─────────────┘      │
│         │          │         │      │         │            │
│         └──────────┼─────────┘      │         │            │
│                    │                │         │            │
│                Volume Mounts        │         │            │
│              ./src/runtime/python   │         │            │
│                    │                │         │            │
└─────────────────────────────────────────────────────────────┘
```

## 🧪 **Testing Scenarios**

### **Phase 1: Metadata Endpoint**

```bash
# Test metadata exposure
curl http://localhost:8080/metadata | jq '.capabilities'

# Should show session_required flags
curl http://localhost:8080/metadata | jq '.capabilities.stateful_counter.session_required'
```

### **Phase 4: Session Affinity**

```bash
# Create session on Agent A
curl -H "X-Session-ID: user-123" -H "X-Capability: stateful_counter" \
     -X POST http://localhost:8080/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"user-123"}}}'

# Same session to Agent B - should forward to Agent A
curl -H "X-Session-ID: user-123" -H "X-Capability: stateful_counter" \
     -X POST http://localhost:8081/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"user-123"}}}'

# Counter should increment (same pod handling both calls)
```

### **Phase 6: Full MCP Protocol**

```bash
# Test tools/list on introspection agent
curl -H "X-Capability: agent_introspector" -H "X-MCP-Method: tools/list" \
     -X POST http://localhost:8082/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Should return list of available tools
```

## 📊 **Agent Capabilities**

### **Agent A & B (Session Agents)**

- `stateful_counter` - Counter with session affinity (session_required=True)
- `user_preferences` - User preferences with session affinity
- `conversation_memory` - Conversation history with session affinity

### **Agent C (Introspection Agent)**

- `agent_introspector` - Agent introspection (full_mcp_access=True)
- `network_mapper` - Network mapping (full_mcp_access=True)
- `capability_discoverer` - Capability discovery (full_mcp_access=True)
- `simple_info` - Basic info (standard capability)

## 🔧 **Development Workflow**

### **1. Implement Phase**

```bash
# Edit implementation
vim src/runtime/python/_mcp_mesh/engine/http_wrapper.py

# Add metadata endpoint
vim src/runtime/python/_mcp_mesh/pipeline/startup/fastapiserver_setup.py
```

### **2. Test Implementation**

```bash
# Test specific phase
./test-progressive-phases.sh 1

# Check logs for debugging
docker-compose -f docker-compose.progressive-testing.yml logs agent-a
```

### **3. Iterate Quickly**

```bash
# No rebuild needed - just test again
./test-progressive-phases.sh 1

# Or test interactively
curl http://localhost:8080/metadata | jq '.capabilities'
```

### **4. Test Cross-Agent Communication**

```bash
# Check registry shows all agents
curl http://localhost:8000/agents | jq '.agents | length'

# Test agent-to-agent calls
curl -X POST http://localhost:8080/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"introspect_agent","arguments":{"target_agent":"session_agent"}}}'
```

## 🐛 **Debugging**

### **View Logs**

```bash
# All services
docker-compose -f docker-compose.progressive-testing.yml logs

# Specific service
docker-compose -f docker-compose.progressive-testing.yml logs agent-a

# Follow logs
docker-compose -f docker-compose.progressive-testing.yml logs -f agent-a
```

### **Check Service Health**

```bash
# Registry health
curl http://localhost:8000/health

# Agent health
curl http://localhost:8080/health
curl http://localhost:8081/health
curl http://localhost:8082/health

# Redis health
docker-compose -f docker-compose.progressive-testing.yml exec redis redis-cli ping
```

### **Inspect Network**

```bash
# Check agent registration
curl http://localhost:8000/agents | jq '.agents[] | {id: .id, status: .status}'

# Check capabilities
curl http://localhost:8000/agents | jq '.agents[0].capabilities[] | {name: .name, session_required: .session_required}'
```

## ⚡ **Fast Iteration Benefits**

1. **No Image Rebuilds**: Edit code and test immediately
2. **Realistic Testing**: Actual multi-agent environment
3. **Session Affinity**: Test real pod-to-pod forwarding
4. **Network Isolation**: Proper container networking
5. **Parallel Development**: Multiple agents with different capabilities
6. **Easy Debugging**: Comprehensive logging and health checks

This setup makes implementing and testing the progressive phases much faster and more realistic than managing multiple background processes locally!
