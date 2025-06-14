# MCP vs MCP Mesh Demonstration Samples

This directory contains perfect demonstration examples showcasing the revolutionary difference between plain MCP and MCP Mesh with automatic dependency injection.

## 🎯 **Demonstration Overview**

These samples demonstrate MCP Mesh's **interface-optional dependency injection** - the ability to automatically inject services without requiring Protocol definitions or complex interface contracts.

### **Key Features Demonstrated:**

- ✅ **Plain MCP behavior** (no dependency injection)
- ✅ **MCP Mesh automatic dependency injection** (real-time service discovery)
- ✅ **Interface-optional pattern** (no Protocol inheritance required)
- ✅ **Real-time updates** (dependencies added/removed dynamically)
- ✅ **Graceful fallback** (works with or without dependencies)

## 📁 **Sample Files**

### **hello_world.py**

Demonstration server with two functions:

- `greet_from_mcp()` - Plain MCP function (decorated with `@server.tool()` only)
- `greet_from_mcp_mesh()` - MCP Mesh function (decorated with `@server.tool()` + `@mesh_agent()`)
- Both have `SystemAgent` parameter for dependency injection testing

### **system_agent.py**

System information agent providing:

- `SystemAgent` class with `getDate()` method
- Decorated with `@mesh_agent` for automatic mesh registry registration
- Real-time dependency injection target for hello_world.py

## 🚀 **Perfect Demonstration Workflow**

### **Step 1: Start Hello World Server**

```bash
mcp_mesh_dev start examples/hello_world.py
```

**Expected Output:**

```
🚀 Starting MCP vs MCP Mesh Demonstration Server...
📡 Server name: hello-world-demo
Server ready on stdio transport...
```

### **Step 2: Test Both Functions (No Dependencies)**

Use MCP client to call tools:

```bash
# Test plain MCP function
call_tool greet_from_mcp
# Returns: "Hello from MCP"

# Test MCP Mesh function (no dependencies available yet)
call_tool greet_from_mcp_mesh
# Returns: "Hello from MCP Mesh"
```

**Key Observation:** Both functions return basic greetings since no dependencies are available.

### **Step 3: Start System Agent (Dependency Provider)**

```bash
mcp_mesh_dev start examples/system_agent.py
```

**Expected Output:**

```
🤖 Starting SystemAgent for MCP Mesh Dependency Injection Demo...
🤖 SystemAgent initialized at 2025-06-08 10:30:00
Server ready on stdio transport...
```

### **Step 4: Test Functions Again (With Dependencies)**

```bash
# Test plain MCP function (unchanged)
call_tool greet_from_mcp
# Returns: "Hello from MCP"

# Test MCP Mesh function (now with automatic dependency injection!)
call_tool greet_from_mcp_mesh
# Returns: "Hello, its June 8, 2025 at 10:30 AM here, what about you?"
```

**🎉 Magic Happened:** The MCP Mesh function automatically received the `SystemAgent` dependency without any code changes!

### **Step 5: Stop System Agent (Remove Dependencies)**

```bash
mcp_mesh_dev stop system_agent.py
```

### **Step 6: Test Again (Dependencies Removed)**

```bash
# Test MCP Mesh function (back to no dependencies)
call_tool greet_from_mcp_mesh
# Returns: "Hello from MCP Mesh"
```

**Key Observation:** Dependencies are removed in real-time when services stop.

## 🔍 **What This Demonstrates**

### **Plain MCP Function (`greet_from_mcp`):**

- ✅ Standard MCP protocol behavior
- ✅ No dependency injection capability
- ✅ Always returns the same result
- ✅ Works with any MCP client
- ✅ Decorated with `@server.tool()` only

### **MCP Mesh Function (`greet_from_mcp_mesh`):**

- ✅ **Revolutionary automatic dependency injection**
- ✅ **Interface-optional pattern** (no Protocol definitions required)
- ✅ **Real-time service discovery** (parameters appear/disappear dynamically)
- ✅ **Graceful fallback** (works without dependencies)
- ✅ **Zero configuration** (no manual wiring required)
- ✅ **Dual-decorator pattern** (`@server.tool()` + `@mesh_agent()`)

## 🛠️ **Technical Details**

### **How Dependency Injection Works:**

1. **Service Registration:**

   ```python
   @mesh_agent(capabilities=["system_info"])
   class SystemAgent:
       def getDate(self) -> str:
           return datetime.now().strftime("%B %d, %Y at %I:%M %p")
   ```

2. **Automatic Discovery:**

   ```python
   @server.tool()
   @mesh_agent(dependencies=["SystemAgent"])
   def greet_from_mcp_mesh(SystemAgent: Optional[Any] = None) -> str:
       if SystemAgent is None:
           return "Hello from MCP Mesh"
       else:
           return f"Hello, its {SystemAgent.getDate()} here, what about you?"
   ```

3. **Real-time Injection:**
   - MCP Mesh registry tracks all running agents
   - Functions with dependency parameters get automatic injection
   - Heartbeat system manages service availability
   - Parameters are added/removed in real-time

### **Key Architectural Benefits:**

- **Zero Boilerplate:** No interface definitions required
- **Type Safety:** Full type hint support without Protocol inheritance
- **Real-time Updates:** Dependencies updated automatically
- **Graceful Degradation:** Functions work with or without dependencies
- **Service Discovery:** Automatic registry-based discovery
- **Performance:** <200ms fallback transitions

## 🔧 **Running the Demonstration**

### **Prerequisites:**

1. MCP Mesh CLI tools installed (`mcp_mesh_dev`)
2. MCP client for testing tool calls
3. Both sample files in `examples/` directory

### **Complete Test Sequence:**

```bash
# Terminal 1: Start hello_world server
mcp_mesh_dev start examples/hello_world.py

# Terminal 2: Test initial behavior
mcp_client_test greet_from_mcp
mcp_client_test greet_from_mcp_mesh

# Terminal 3: Start system agent
mcp_mesh_dev start examples/system_agent.py

# Terminal 2: Test with dependencies
mcp_client_test greet_from_mcp      # Same result
mcp_client_test greet_from_mcp_mesh # NEW behavior with date!

# Terminal 3: Stop system agent
mcp_mesh_dev stop system_agent.py

# Terminal 2: Test after dependency removal
mcp_client_test greet_from_mcp_mesh # Back to original behavior
```

## 🎭 **Use Cases Demonstrated**

### **Development Scenarios:**

1. **Microservices Communication:** Services can discover and use each other automatically
2. **Plugin Architecture:** Plugins can provide functionality to core systems dynamically
3. **Feature Toggles:** Services can be started/stopped to enable/disable features
4. **Testing:** Mock services can be swapped in without code changes
5. **Deployment Flexibility:** Services can be deployed independently

### **Real-world Applications:**

- **Authentication Services:** Auth can be injected into any function needing it
- **Logging Services:** Audit logging can be added without modifying existing code
- **Configuration Services:** Settings can be injected dynamically
- **Database Services:** Data access can be provided on-demand
- **External APIs:** Third-party services can be abstracted and injected

## 🏆 **Perfect Demonstration Results**

This demonstration perfectly showcases:

✅ **Interface-Optional Dependency Injection**: No Protocol definitions required
✅ **Real-time Service Discovery**: Services discovered automatically
✅ **Dynamic Parameter Injection**: Function parameters updated in real-time
✅ **Graceful Fallback**: Works with or without dependencies
✅ **Zero Configuration**: No manual wiring or configuration required
✅ **Type Safety**: Full type hint support
✅ **Performance**: <200ms response times
✅ **Reliability**: Automatic health monitoring and service eviction

## 📝 **Function Specifications**

### **hello_world.py Functions:**

#### **greet_from_mcp(SystemAgent: Optional[Any] = None) -> str**

- **Decoration:** `@server.tool()` only
- **Behavior:** Always returns "Hello from MCP" (no dependency injection)
- **Purpose:** Demonstrates standard MCP protocol behavior

#### **greet_from_mcp_mesh(SystemAgent: Optional[Any] = None) -> str**

- **Decoration:** `@server.tool()` + `@mesh_agent(dependencies=["SystemAgent"])`
- **Behavior:**
  - If SystemAgent is None: "Hello from MCP Mesh"
  - If SystemAgent is injected: "Hello, its {date} here, what about you?"
- **Purpose:** Demonstrates automatic dependency injection

### **system_agent.py Functions:**

#### **SystemAgent.getDate() -> str**

- **Returns:** Current date formatted as "Month DD, YYYY at HH:MM AM/PM"
- **Purpose:** Provides date service for dependency injection
- **Example:** "June 8, 2025 at 10:30 AM"

## 📦 **Package Installation & Limitations**

### **Installation Options**

#### **Option 1: MCP SDK Only (Basic MCP Functions)**

```bash
pip install mcp-mesh
```

**What you get:**

- ✅ Full MCP SDK functionality
- ✅ `@server.tool()` decorators work perfectly
- ✅ Plain MCP functions run normally
- ❌ **NO MCP Mesh features** (dependency injection disabled)
- ❌ **NO @mesh_agent() decorator functionality**
- ❌ **NO automatic service discovery**

**Behavior with MCP SDK only:**

- `greet_from_mcp()` - ✅ Works perfectly (returns "Hello from MCP")
- `greet_from_mcp_mesh()` - ⚠️ Works but NO dependency injection (returns "Hello from MCP Mesh")
- SystemAgent parameter will ALWAYS be None

#### **Option 2: Full MCP Mesh Runtime (All Features)**

```bash
pip install mcp-mesh-runtime
```

**What you get:**

- ✅ Complete MCP SDK functionality
- ✅ **Full MCP Mesh dependency injection magic**
- ✅ `@mesh_agent()` decorator with automatic discovery
- ✅ Real-time service registration and injection
- ✅ CLI tools (`mcp-mesh-dev`)
- ✅ Registry services and monitoring

**Behavior with MCP Mesh Runtime:**

- `greet_from_mcp()` - ✅ Works perfectly (returns "Hello from MCP")
- `greet_from_mcp_mesh()` - 🎉 **AUTOMATIC DEPENDENCY INJECTION** (returns enhanced greeting with date)
- SystemAgent parameter automatically injected when system_agent.py runs

### **Critical Understanding**

🚨 **IMPORTANT**: The `@mesh_agent()` decorator is **interface-optional** but **runtime-dependent**:

- **With `mcp-mesh` only:** Functions decorated with `@mesh_agent()` work as plain MCP functions
- **With `mcp-mesh-runtime`:** Functions decorated with `@mesh_agent()` get full dependency injection

### **Demonstration Compatibility**

| Package            | greet_from_mcp      | greet_from_mcp_mesh       | SystemAgent Injection |
| ------------------ | ------------------- | ------------------------- | --------------------- |
| `mcp-mesh` only    | ✅ "Hello from MCP" | ⚠️ "Hello from MCP Mesh"  | ❌ Always None        |
| `mcp-mesh-runtime` | ✅ "Hello from MCP" | 🎉 "Hello, its June 8..." | ✅ Automatic          |

### **Quick Start Guide**

1. **For MCP SDK compatibility only:**

   ```bash
   pip install mcp-mesh
   python examples/hello_world.py  # Basic MCP functions only
   ```

2. **For full MCP Mesh experience:**
   ```bash
   pip install mcp-mesh-runtime
   mcp-mesh-dev start examples/hello_world.py
   mcp-mesh-dev start examples/system_agent.py  # Watch dependency injection!
   ```

**This is the future of service mesh architecture - zero-boilerplate, interface-optional, real-time dependency injection!** 🚀

## 🛠️ **CLI Usage and Compatibility**

### **Working Examples**

All examples in the `examples/` directory are **fully compatible** with the CLI:

✅ **examples/hello_world.py** - Perfect demonstration of CLI usage
✅ **examples/system_agent.py** - Dependency injection demo
✅ **examples/process_management_demo.py** - Process monitoring demo

### **Backup Examples Compatibility**

The `examples.bkp/` directory contains older examples with some compatibility issues:

⚠️ **Some backup examples** use older import syntax:

- Old: `from mcp_mesh_types import mesh_agent`
- New: `from mcp_mesh import mesh_agent`

⚠️ **Working backup examples:**

- `hello_world_server.py` - Works with CLI
- `vanilla_mcp_test.py` - Works with CLI
- `test_client.py` - Works with CLI

❌ **Backup examples needing updates:**

- `file_agent_example.py` - Import issues
- `fastmcp_integration_example.py` - Import issues
- Others with `mcp_mesh_types` imports

### **CLI Command Reference**

#### **Basic Usage**

```bash
# Start single agent
mcp_mesh_dev start examples/hello_world.py

# Start multiple agents
mcp_mesh_dev start examples/hello_world.py examples/system_agent.py

# Stop specific agent
mcp_mesh_dev stop system_agent

# Stop all services
mcp_mesh_dev stop
```

#### **Monitoring and Debug**

```bash
# Check service status
mcp_mesh_dev status

# List running services
mcp_mesh_dev list

# View logs
mcp_mesh_dev logs
mcp_mesh_dev logs --follow
mcp_mesh_dev logs --agent hello_world
```

#### **Advanced Configuration**

```bash
# Custom registry port
mcp_mesh_dev start --registry-port 8081 examples/hello_world.py

# Custom database path
mcp_mesh_dev start --database-path ./custom_registry.db examples/hello_world.py

# Verbose output
mcp_mesh_dev start --verbose examples/hello_world.py
```

### **Expected CLI Behavior**

When you run `mcp_mesh_dev start examples/hello_world.py`, you should see:

```
ℹ INFO: Starting MCP Mesh services with configuration:
  Registry: localhost:8080
  Database: ./dev_registry.db
  Log Level: INFO
  Mode: Registry + 1 agent(s)
ℹ INFO: Agent files: examples/hello_world.py
ℹ INFO: Starting registry service...
✓ SUCCESS: Registry service ready
  PID: 12345
  Host: localhost
  Port: 8080
  URL: http://localhost:8080
ℹ INFO: Starting 1 agent(s)...
✓ SUCCESS: Agent hello_world started
  PID: 12346
  File: /path/to/examples/hello_world.py
  Registry: http://localhost:8080
ℹ INFO: Waiting for agent registration...
```

### **Troubleshooting CLI Issues**

#### **Common Problems**

1. **Port already in use:**

   ```bash
   mcp_mesh_dev start --registry-port 8081 examples/hello_world.py
   ```

2. **Import errors in backup examples:**

   ```
   ModuleNotFoundError: No module named 'mcp_mesh_types'
   ```

   → Use examples from `examples/` directory instead of `examples.bkp/`

3. **Agent fails to start:**
   ```bash
   mcp_mesh_dev status  # Check what went wrong
   mcp_mesh_dev logs    # View error details
   ```

#### **CLI vs Direct Python Execution**

| Method                           | Use Case              | Benefits                                 |
| -------------------------------- | --------------------- | ---------------------------------------- |
| `mcp_mesh_dev start`             | Development & Testing | Registry, monitoring, process management |
| `python examples/hello_world.py` | Basic MCP Testing     | Simple, direct execution                 |

### **Production vs Development**

- **Development**: Use `mcp_mesh_dev` for full mesh features
- **Production**: Use `mcp-server` or direct Python execution for basic MCP
- **Hybrid**: Use `mcp_mesh` package for compatibility with both approaches

The CLI provides the complete MCP Mesh experience with automatic dependency injection, service discovery, and robust process management! 🚀
