# Shutdown Improvements for MCP Mesh

## Problem Statement

When running MCP Mesh agents with the CLI tool (`mcp-mesh-dev start`), pressing Ctrl+C would cause the Python process to hang indefinitely, showing threading errors:

```
^CException ignored in: <module 'threading' from '/home/dhyanraj/.pyenv/versions/3.12.8/lib/python3.12/threading.py'>
Traceback (most recent call last):
  File "/home/dhyanraj/.pyenv/versions/3.12.8/lib/python3.12/threading.py", line 1624, in _shutdown
    lock.acquire()
KeyboardInterrupt:
Fatal Python error: _enter_buffered_busy: could not acquire lock for <_io.BufferedReader name='<stdin>'> at interpreter shutdown
```

## Root Causes

1. **Non-daemon threads**: The mesh decorator was creating non-daemon background threads that prevented clean shutdown
2. **Async task cleanup**: Health monitoring tasks were not properly cancelled during shutdown
3. **Signal handling with stdio**: FastMCP's stdio transport blocks normal signal processing in Python
4. **Missing cleanup coordination**: No centralized shutdown mechanism to coordinate cleanup across components

## Solutions Implemented

### 1. Graceful Shutdown Manager (`graceful_shutdown.py`)

Created a centralized shutdown manager that:

- Handles signals (SIGINT, SIGTERM) properly
- Manages cleanup callbacks for all components
- Uses `os._exit()` for clean termination to avoid threading deadlocks
- Provides lazy initialization to avoid startup overhead

```python
class GracefulShutdownManager:
    """Manages graceful shutdown of MCP Mesh components."""

    def _signal_handler(self, signum: int, frame):
        """Handle shutdown signals."""
        if self._shutting_down:
            # Force exit on second signal
            os._exit(1)

        # Run cleanup in current thread to avoid threading issues
        self._cleanup_all()

        # Exit cleanly
        os._exit(0)
```

### 2. Task and Thread Managers

Created managers to track and clean up async tasks and threads:

```python
class AsyncTaskManager:
    """Manages async tasks with proper cleanup."""

    def cleanup_all(self):
        """Cancel all tracked tasks."""
        for task in active_tasks:
            if not task.done():
                task.cancel()

class ThreadManager:
    """Manages threads with proper cleanup."""

    def create_thread(self, target, name=None, daemon=True):
        """Create and track a thread."""
        # Use daemon=True so threads don't block shutdown
```

### 3. Mesh Decorator Updates

Updated the mesh agent decorator to:

- Use daemon threads instead of non-daemon threads
- Track all tasks and threads with managers
- Check for shutdown in health monitoring loop
- Properly clean up resources in the cleanup method

```python
# Before
init_thread = threading.Thread(
    target=run_async_init,
    name=f"MeshInit-{self.agent_name}",
    daemon=False  # This was blocking shutdown!
)

# After
self._init_thread = self._thread_manager.create_thread(
    target=run_async_init,
    name=f"MeshInit-{self.agent_name}",
    daemon=True  # Daemon thread doesn't block shutdown
)
```

### 4. Stdio Signal Handler (`stdio_signal_handler.py`)

Created a specialized signal handler for stdio transport:

- Detects when running with stdio transport
- Installs signal handlers that work with blocked I/O
- Forces exit after timeout if graceful shutdown fails
- Integrates with the graceful shutdown manager

```python
def setup_stdio_shutdown():
    """Set up proper shutdown handling for stdio transport."""
    if is_stdio_transport():
        handler = install_stdio_signal_handler()
        handler.register_callback(cleanup_mesh)
        return handler
```

### 5. Example Updates

Updated examples to handle shutdown gracefully:

- Added signal handlers to catch SIGINT/SIGTERM
- Handle closed stdout/stderr during shutdown
- Use the stdio signal handler when available

## Testing

The shutdown improvements have been tested with:

1. Direct Python execution (works perfectly)
2. CLI tool with stdio transport (improved but may still have slight delays due to stdio blocking)
3. Multiple concurrent agents
4. Registry + agent combinations

## Remaining Considerations

1. **Stdio transport limitations**: FastMCP's stdio transport inherently blocks some signal processing. The improvements mitigate this but cannot completely eliminate the issue.

2. **Process groups**: The Go CLI could be enhanced to use process groups for more reliable signal propagation to child processes.

3. **Timeout tuning**: The default 30-second shutdown timeout in the CLI may be too long for development. Consider reducing it or making it configurable.

## Usage

The shutdown improvements are automatically applied when using the mesh decorator. No code changes are required in existing agents. For best results with stdio transport, examples can import the stdio signal handler:

```python
try:
    from mcp_mesh_runtime.utils.stdio_signal_handler import setup_stdio_shutdown
    setup_stdio_shutdown()
except ImportError:
    # Fallback to basic signal handling
    pass
```
