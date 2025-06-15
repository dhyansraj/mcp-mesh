# MCP Mesh Examples

This directory contains examples demonstrating different ways to use MCP Mesh.

## Auto-FastMCP Examples

### `hello_auto_fastmcp.py`

**The "magical" experience** - just define `@mesh.tool` functions and the processor automatically:

- Creates FastMCP server
- Registers all tools as MCP tools
- Sets up HTTP wrapper
- Handles server lifecycle

```bash
python example/hello_auto_fastmcp.py
```

### `comparison_manual_vs_auto.py`

**Side-by-side comparison** of manual FastMCP creation vs auto-creation:

- Change `DEMO_MODE = "manual"` or `DEMO_MODE = "auto"`
- See the difference in code complexity

```bash
python example/comparison_manual_vs_auto.py
```

## Key Requirements

### ⚠️ **Process Must Stay Alive**

All examples include infinite loops because:

- FastMCP server runs in the Python process
- If Python exits, FastMCP server dies
- HTTP endpoints become unavailable
- MCP tools stop working

### 🔧 **Registry Setup**

Examples assume MCP Mesh registry is running at `http://localhost:8000`:

```bash
# Start registry first (in separate terminal)
go run cmd/registry/main.go
```

### 📝 **What You'll See in Logs**

With auto-FastMCP, look for these log messages:

```
🔧 Auto-created FastMCP server 'service-name-XXXXXXXX' for N @mesh.tool functions
📝 Auto-registered 'function_name' as MCP tool
✅ Auto-registered N tools with FastMCP server
🌐 HTTP wrapper started on 0.0.0.0:PORT
```

## Usage Patterns

### Minimal Auto-FastMCP

```python
import mesh

@mesh.agent(name="my-service")
class MyAgent:
    pass

@mesh.tool(capability="greeting")
def hello():
    return "Hello!"

if __name__ == "__main__":
    # Keep process alive
    while True:
        time.sleep(10)
```

### With Manual FastMCP (Traditional)

```python
import mesh

@mesh.agent(name="my-service")
class MyAgent:
    pass

server = mesh.create_server()

@mesh.tool(capability="greeting")
@server.tool()
def hello():
    return "Hello!"

if __name__ == "__main__":
    # Keep process alive
    while True:
        time.sleep(10)
```

Both approaches work, but auto-FastMCP reduces boilerplate!

## 🎉 **NEW: Pure Simplicity (auto_run=True by default!)**

### The Ultimate Simplicity - Just 2 Decorators!

```python
import mesh

@mesh.agent(name="my-service")  # auto_run=True by default!
class MyAgent:
    pass

@mesh.tool(capability="greeting")
def hello():
    return "Hello!"

# 🎉 THAT'S IT! No manual calls needed!
```

### Pure Simplicity Examples

#### `pure_simplicity.py`

**The absolute simplest possible MCP service** - just 2 decorators:

```bash
python example/pure_simplicity.py
```

#### `auto_run_simple.py`

**Simple auto-run example** - shows explicit auto_run=True (optional):

```bash
python example/auto_run_simple.py
```

#### `auto_run_vs_manual.py`

**Side-by-side comparison** of manual vs auto-run approaches:

- Change `MODE = "manual"` or `MODE = "auto"`
- See the dramatic reduction in boilerplate

```bash
python example/auto_run_vs_manual.py
```

#### `auto_run_advanced.py`

**Full-featured auto-run service** with comprehensive configuration:

- Environment variable overrides
- Advanced error handling
- Detailed diagnostics

```bash
python example/auto_run_advanced.py
```

## Auto-Run Configuration

### Basic Usage

```python
@mesh.agent(
    name="my-service",
    auto_run=True,                    # Enable auto-run
    auto_run_interval=10              # Heartbeat every 10 seconds
)
class MyAgent:
    pass
```

### Environment Variable Overrides

```bash
export MCP_MESH_AUTO_RUN=true
export MCP_MESH_AUTO_RUN_INTERVAL=15
export MCP_MESH_ENABLE_HTTP=true
export MCP_MESH_NAMESPACE=production

python my_service.py
```

### Manual vs Pure Simplicity Comparison

| **Feature**           | **Manual**                                   | **Pure Simplicity**   |
| --------------------- | -------------------------------------------- | --------------------- |
| **FastMCP Creation**  | Manual `FastMCP()` or `mesh.create_server()` | ✅ Automatic          |
| **Tool Registration** | Manual `@server.tool()`                      | ✅ Automatic          |
| **Keep-Alive Loop**   | Manual `while True:`                         | ✅ Automatic          |
| **Signal Handling**   | Manual signal handlers                       | ✅ Automatic          |
| **Auto-Run Config**   | Manual `auto_run=True`                       | ✅ **Default True**   |
| **Code Lines**        | ~20+ lines                                   | **2 decorators only** |

**Manual Approach (Old):**

```python
import mesh
import signal
import time

@mesh.agent(name="service")
class Agent:
    pass

server = mesh.create_server()

@mesh.tool(capability="greeting")
@server.tool()
def hello():
    return "Hello!"

# Manual keep-alive
running = True
def handler(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handler)

try:
    while running:
        time.sleep(10)
except KeyboardInterrupt:
    pass
```

**Pure Simplicity Approach (New):**

```python
import mesh

@mesh.agent(name="service")  # auto_run=True by default!
class Agent:
    pass

@mesh.tool(capability="greeting")
def hello():
    return "Hello!"

# 🎉 That's it! Nothing else needed!
```

The pure simplicity approach eliminates ~95% of the boilerplate code!
