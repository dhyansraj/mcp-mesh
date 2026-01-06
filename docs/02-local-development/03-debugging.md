# Debugging Agents

> Master debugging techniques for MCP Mesh agents using IDE tools, logging, and distributed tracing

## Overview

Debugging distributed systems can be challenging, but MCP Mesh provides powerful tools to make it manageable. This guide covers IDE debugging setup, logging strategies, distributed tracing, and techniques specific to debugging dependency injection and remote function calls.

Whether you're tracking down a bug in a single agent or debugging interactions between multiple services, these techniques will help you quickly identify and resolve issues.

## Key Concepts

- **IDE Debugging**: Step through agent code with breakpoints
- **Structured Logging**: Consistent, searchable log output
- **Distributed Tracing**: Track requests across multiple agents
- **Dependency Injection Debugging**: Understand how dependencies are resolved
- **Remote Debugging**: Debug agents running in containers or remote hosts

## Step-by-Step Guide

### Step 1: Enable Debug Logging

Set up comprehensive logging for development:

```bash
# Environment variable
export MCP_MESH_LOG_LEVEL=DEBUG

# Or in your agent code
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

Create a logging configuration file `logging_config.py`:

```python
import logging.config

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        },
        'simple': {
            'format': '%(levelname)s - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'detailed',
            'stream': 'ext://sys.stdout'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'DEBUG',
            'formatter': 'detailed',
            'filename': 'agent_debug.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5
        }
    },
    'loggers': {
        'mcp_mesh': {
            'level': 'DEBUG',
            'handlers': ['console', 'file']
        },
        'your_agent': {
            'level': 'DEBUG',
            'handlers': ['console', 'file']
        }
    }
}

logging.config.dictConfig(LOGGING_CONFIG)
```

### Step 2: IDE Debugging Setup

#### VS Code Configuration

Create `.vscode/launch.json`:

```json
{
  "version": "0.7.20",
  "configurations": [
    {
      "name": "Debug Current Agent",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/bin/meshctl",
      "args": ["start", "${file}"],
      "console": "integratedTerminal",
      "justMyCode": false,
      "env": {
        "MCP_MESH_LOG_LEVEL": "DEBUG",
        "PYTHONPATH": "${workspaceFolder}"
      }
    },
    {
      "name": "Debug with Remote Attach",
      "type": "python",
      "request": "attach",
      "connect": {
        "host": "localhost",
        "port": 5678
      },
      "pathMappings": [
        {
          "localRoot": "${workspaceFolder}",
          "remoteRoot": "."
        }
      ]
    }
  ]
}
```

#### PyCharm Configuration

1. Run → Edit Configurations → Add New Configuration → Python
2. Script path: `/path/to/mcp-mesh/bin/meshctl`
3. Parameters: `start examples/simple/your_agent.py`
4. Environment variables: `MCP_MESH_LOG_LEVEL=DEBUG`
5. Working directory: Your project root

### Step 3: Add Strategic Debug Points

Add debug helpers to your agents:

```python
from mesh import agent, tool
import logging

logger = logging.getLogger(__name__)

@agent(name="data-processor")
class DataProcessor:
    pass

@tool(
    capability="data_processor",
    dependencies=["database_query"]
)
def process_data(
    data_id: str,
    database_query=None
):
    # Debug: Log input parameters
    logger.debug(f"process_data called with data_id={data_id}")
    logger.debug(f"DatabaseAgent_query available: {DatabaseAgent_query is not None}")

    # Debug: Breakpoint for IDE debugging
    import pdb; pdb.set_trace()  # Remove in production!

    try:
        # Debug: Log before remote call
        logger.debug(f"Calling database_query with id={data_id}")
        result = database_query(f"SELECT * FROM data WHERE id='{data_id}'")
        logger.debug(f"Query result: {result}")

        # Process the data
        processed = transform_data(result)

        # Debug: Log success
        logger.info(f"Successfully processed data_id={data_id}")
        return processed

    except Exception as e:
        # Debug: Log full exception with stack trace
        logger.exception(f"Error processing data_id={data_id}")
        raise
```

### Step 4: Debug Dependency Injection

Understand how dependencies are resolved:

```python
# Enable dependency injection debugging
import os
os.environ['MCP_MESH_DEBUG_INJECTION'] = 'true'

@tool(
    capability="analyzer",
    dependencies=["data_processor", "cache_get"]
)
def analyze(
    item_id: str,
    data_processor=None,
    cache_get=None
):
    # Debug: Check which dependencies were injected
    logger.debug("Dependency injection status:")
    logger.debug(f"  data_processor: {'✓' if data_processor else '✗'}")
    logger.debug(f"  cache_get: {'✓' if cache_get else '✗'}")

    # Debug: Log dependency metadata
    if hasattr(data_processor, '_mesh_metadata'):
        logger.debug(f"  data_processor metadata: {data_processor._mesh_metadata}")
```

## Configuration Options

| Option                     | Description                  | Default       | Example               |
| -------------------------- | ---------------------------- | ------------- | --------------------- |
| `MCP_MESH_LOG_LEVEL`       | Global log level             | INFO          | DEBUG, WARNING, ERROR |
| `MCP_MESH_DEBUG_INJECTION` | Show DI resolution details   | false         | true                  |
| `MCP_MESH_TRACE_ENABLED`   | Enable distributed tracing   | false         | true                  |
| `MCP_MESH_PROFILE_ENABLED` | Enable performance profiling | false         | true                  |
| `PYTHONBREAKPOINT`         | Debugger to use              | pdb.set_trace | ipdb.set_trace        |

## Examples

### Example 1: Debugging Remote Function Calls

```python
import time
from functools import wraps

def debug_timing(func):
    """Decorator to debug function execution time"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            logger.debug(f"{func.__name__} completed in {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"{func.__name__} failed after {elapsed:.3f}s: {e}")
            raise
    return wrapper

@tool(capability="timed_service")
@debug_timing
def slow_operation(size: int):
    """Example of debugging performance issues"""
    logger.debug(f"Starting slow_operation with size={size}")
    # Simulate work
    time.sleep(size * 0.1)
    return f"Processed {size} items"
```

### Example 2: Interactive Debugging Session

```python
# debug_utils.py
import IPython
from rich.console import Console
from rich.table import Table

console = Console()

def debug_registry_state():
    """Interactive function to inspect registry state"""
    import requests

    # Fetch registry data
    agents = requests.get("http://localhost:8000/agents").json()

    # Create rich table
    table = Table(title="Registered Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Capabilities")
    table.add_column("Dependencies")

    for agent in agents:
        table.add_row(
            agent['name'],
            agent['status'],
            ', '.join(agent.get('capabilities', [])),
            ', '.join(agent.get('dependencies', []))
        )

    console.print(table)

    # Drop into IPython for exploration
    IPython.embed()

# Use in your agent:
if __name__ == "__main__":
    debug_registry_state()
```

## Best Practices

1. **Use Structured Logging**: Include context like request IDs and agent names
2. **Avoid Print Statements**: Use proper logging levels instead
3. **Remove Debug Code**: Don't commit pdb.set_trace() or excessive logging
4. **Log at Boundaries**: Focus on function entry/exit and external calls
5. **Correlate Logs**: Use request IDs to track across services

## Common Pitfalls

### Pitfall 1: Debugging in Production Mode

**Problem**: Breakpoints and debug logs don't work in production mode

**Solution**: Ensure development mode is enabled:

```bash
export MCP_DEV_MODE=true
export MCP_MESH_LOG_LEVEL=DEBUG

# Or check mode in code
import os
if os.getenv('MCP_DEV_MODE') == 'true':
    import pdb; pdb.set_trace()
```

### Pitfall 2: Lost Logs in Async Code

**Problem**: Logs from async functions don't appear or are out of order

**Solution**: Use proper async logging:

```python
import asyncio
import logging

# Configure async-friendly logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - [%(thread)d] - %(message)s'
)

async def async_operation():
    logger.debug(f"Starting async operation in task {asyncio.current_task().get_name()}")
```

## Testing

### Unit Test Example

```python
# tests/test_debugging.py
import logging
import pytest
from unittest.mock import patch

def test_debug_logging(caplog):
    """Test that debug logs are captured"""
    with caplog.at_level(logging.DEBUG):
        from your_agent import process_data
        process_data(data_id="test123")

    assert "process_data called with data_id=test123" in caplog.text
```

### Integration Test Example

```python
# tests/test_debug_tools.py
def test_dependency_injection_logging():
    """Test that DI debug mode shows injection details"""
    import os
    os.environ['MCP_MESH_DEBUG_INJECTION'] = 'true'

    # Start agent and check logs
    # Should see detailed injection information
```

## Monitoring and Debugging

### Logs to Check

```bash
# Agent-specific logs
tail -f agent_debug.log | grep ERROR

# Use meshctl for debugging
./bin/meshctl status --verbose
./bin/meshctl dependencies

# Performance issues
grep "slow_query\|timeout" agent_debug.log

# Memory debugging
grep "memory_usage\|gc.collect" agent_debug.log
```

### Metrics to Monitor

- **Function Execution Time**: Log slow operations > 1 second
- **Memory Usage**: Track before/after large operations
- **Dependency Resolution Time**: Should be < 100ms

## 🔧 Troubleshooting

### Issue 1: Debugger Won't Attach

**Symptoms**: IDE can't connect to debugging session

**Cause**: Firewall or process isolation

**Solution**:

```python
# Enable remote debugging
import debugpy
debugpy.listen(5678)
debugpy.wait_for_client()  # Blocks until debugger attaches
```

### Issue 2: Logs Not Appearing

**Symptoms**: Debug statements don't show in console

**Cause**: Logger configuration overridden

**Solution**:

```python
# Force logging configuration
import logging
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger('mcp_mesh').setLevel(logging.DEBUG)

# Add console handler if missing
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console.setFormatter(formatter)
logging.getLogger().addHandler(console)
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Async Debugging**: Some debuggers struggle with async code - use logging instead
- **Multi-Process Debugging**: Each agent runs in its own process - attach individually
- **Production Debugging**: Limited to logging - no breakpoints in production

## 📝 TODO

- [ ] Add distributed tracing with OpenTelemetry
- [ ] Create debug toolbar for web UI
- [ ] Add memory profiling tools
- [ ] Support for remote debugging in Kubernetes

## Summary

You now have powerful debugging tools for developing MCP Mesh agents:

Key takeaways:

- 🔑 IDE debugging with breakpoints for step-through debugging
- 🔑 Comprehensive logging for production-like debugging
- 🔑 Dependency injection debugging to understand service resolution
- 🔑 Performance debugging tools for optimization

## Next Steps

Let's explore hot reload functionality to speed up your development workflow.

Continue to [Hot Reload and Development Workflow](./04-hot-reload.md) →

---

💡 **Tip**: Use `logger.exception()` in except blocks - it automatically includes the full stack trace

📚 **Reference**: [Python Debugging Best Practices](https://docs.python.org/3/library/debug.html)

🧪 **Try It**: Add a deliberate bug to your agent and practice debugging it with both IDE breakpoints and logging
