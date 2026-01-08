# FAQ

> Frequently asked questions about MCP Mesh

---

## Dependency Injection

### How do I use mesh dependencies in background tasks (Redis consumers, cron jobs)?

Use `@mesh.tool` without `@app.tool`. The decorator provides full dependency injection even when the function is not exposed as an MCP tool.

```python
# Declare dependency - NOT an MCP tool (no @app.tool)
@mesh.tool(dependencies=["notification_service"])
async def send_notification(msg: str, notifier: mesh.McpMeshAgent = None):
    """Internal function with DI - not exposed via MCP."""
    await notifier({"message": msg})

# Use from anywhere - dependencies auto-injected!
async def redis_consumer(message):
    await send_notification(message)  # notifier is injected automatically

async def cron_job():
    await send_notification("Daily report")  # works here too!
```

**How it works:**

1. `@mesh.tool` registers the function's dependencies with the mesh registry
2. During agent startup/heartbeat, dependencies are resolved and proxies are created
3. The decorator creates a wrapper that intercepts all calls
4. When you call the function, the wrapper injects the resolved proxies automatically

**Key points:**

- The `capability` parameter is optional for internal functions
- Dependencies are resolved during agent heartbeat
- Proxies are injected automatically on every call
- Works from any context: MCP calls, background tasks, direct calls

---

## Project Organization

### How do I organize @mesh.tool functions across multiple files?

MCP Mesh follows FastAPI's pattern - **explicit imports are required**. Tools are only registered when Python executes their decorators.

**Directory structure:**

```
my-agent/
├── main.py           # Entry point with @mesh.agent
├── tools/
│   ├── __init__.py   # Re-exports tools
│   ├── greeter.py    # @mesh.tool functions
│   └── calculator.py # @mesh.tool functions
```

**Option 1: Import in main.py**

```python
# main.py
from tools import greeter, calculator  # Executes decorators

@mesh.agent(name="my-agent")
class MyAgent: pass
```

**Option 2: Re-export from \_\_init\_\_.py**

```python
# tools/__init__.py
from .greeter import *
from .calculator import *

# main.py
from tools import *  # Or specific functions

@mesh.agent(name="my-agent")
class MyAgent: pass
```

**Option 3: Auto-import helper**

```python
# tools/__init__.py
import importlib
import pkgutil

# Auto-import all modules in this package
for loader, name, is_pkg in pkgutil.walk_packages(__path__):
    importlib.import_module(f"{__name__}.{name}")

# main.py
import tools  # All submodules auto-imported

@mesh.agent(name="my-agent")
class MyAgent: pass
```

!!! tip "Why explicit imports?"
    This matches FastAPI's router pattern - no magic auto-discovery. Explicit imports keep code clear and predictable.

---

## Logging

### Why are my heartbeat logs so verbose?

MCP Mesh uses a tiered logging system:

| Level | What you see |
|-------|--------------|
| **INFO** | Every 10th heartbeat, topology changes, errors |
| **DEBUG** | One summary line per heartbeat |
| **TRACE** | Full pipeline execution details |

To reduce verbosity, use `--log-level INFO` (default) or set `MCP_MESH_LOG_LEVEL=INFO`.

```bash
# Quiet mode - only important events
meshctl start main.py

# Debug mode - one line per heartbeat
meshctl start main.py --debug

# Trace mode - full details (for troubleshooting)
meshctl start main.py --log-level TRACE
```

---

## Deployment

### How do I name log files for agents using main.py?

MCP Mesh automatically determines log file names:

1. **First:** Looks for `@mesh.agent(name="...")` decorator
2. **Then:** Uses filename (without `.py`)
3. **Finally:** If filename is `main`, uses parent directory name

| Script Path | Log File |
|-------------|----------|
| `my-api/main.py` | `my-api.log` |
| `calculator/main.py` | `calculator.log` |
| `greeter.py` | `greeter.log` |

This ensures that scaffolded agents (which use `main.py`) don't all write to `main.log`.

---

## See Also

- [Getting Started](01-getting-started.md) - Quick introduction to MCP Mesh
- [Mesh Decorators](mesh-decorators.md) - Full decorator reference
- [Troubleshooting](01-getting-started/troubleshooting.md) - Common issues and solutions
