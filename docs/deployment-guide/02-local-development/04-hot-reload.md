# Hot Reload and Development Workflow

> Accelerate development with automatic code reloading and efficient workflows

## Overview

Hot reload automatically restarts your agents when you change code, eliminating the tedious cycle of stopping and restarting services manually. This guide covers enabling hot reload, optimizing your development workflow, and best practices for rapid iteration.

Combined with proper tooling, hot reload can reduce your development cycle from minutes to seconds, allowing you to test changes instantly and maintain flow state.

## Key Concepts

- **File Watching**: Monitor Python files for changes
- **Graceful Restart**: Agents restart without losing registry connection
- **Selective Reload**: Only restart changed agents, not the entire mesh
- **State Preservation**: Maintain debugging context across reloads
- **Workflow Optimization**: Tools and practices for maximum productivity

## Step-by-Step Guide

### Step 1: Enable Hot Reload

Hot reload is built into mcp-mesh-dev:

```bash
# Hot reload is enabled by default when using mcp-mesh-dev
mcp-mesh-dev start agents/my_agent.py

# You'll see:
# File watching enabled. Agents will auto-restart on file changes.

# To disable hot reload
mcp-mesh-dev start agents/my_agent.py --no-reload
```

Environment variable control:

```bash
# Enable hot reload (default)
export MCP_MESH_ENABLE_HOT_RELOAD=true

# Disable for production-like testing
export MCP_MESH_ENABLE_HOT_RELOAD=false
```

### Step 2: Configure Watch Patterns

Create `.meshwatch` file to control what triggers reloads:

```yaml
# .meshwatch
include:
  - "agents/**/*.py"
  - "lib/**/*.py"
  - "config/**/*.yaml"

exclude:
  - "**/__pycache__/**"
  - "**/*.pyc"
  - "**/test_*.py"
  - "**/.pytest_cache/**"

# Don't reload on these files (just log)
log_only:
  - "**/*.md"
  - "**/*.txt"

# Delay before reload (milliseconds)
reload_delay: 500
```

### Step 3: Optimize Your Editor for Hot Reload

#### VS Code Settings

```json
{
  "files.autoSave": "afterDelay",
  "files.autoSaveDelay": 1000,
  "python.linting.lintOnSave": true,
  "editor.formatOnSave": true,
  "[python]": {
    "editor.formatOnSaveMode": "file"
  }
}
```

#### PyCharm Settings

1. Settings → Appearance & Behavior → System Settings
2. Enable "Save files automatically"
3. Set delay to 1 second
4. Enable "Save files on frame deactivation"

### Step 4: Set Up Development Scripts

Create `dev.sh` for quick development:

```bash
#!/bin/bash
# dev.sh - Development helper script

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to start development environment
start_dev() {
    echo -e "${GREEN}Starting MCP Mesh development environment...${NC}"

    # Clean logs for fresh start
    rm -f agent_debug.log

    # Set development environment
    export MCP_MESH_LOG_LEVEL=DEBUG
    export MCP_MESH_ENABLE_HOT_RELOAD=true
    export MCP_MESH_DB_TYPE=sqlite
    export MCP_MESH_DB_PATH=./dev-registry.db

    # Start agents with hot reload
    mcp-mesh-dev start agents/ &
    DEV_PID=$!

    echo -e "${GREEN}Development environment started!${NC}"
    echo -e "${YELLOW}Watching for file changes...${NC}"
    echo "Process ID: $DEV_PID"

    # Monitor logs in another terminal
    if command -v gnome-terminal &> /dev/null; then
        gnome-terminal -- bash -c "tail -f agent_debug.log | grep -E 'ERROR|WARNING|Reloading'"
    fi

    wait $DEV_PID
}

# Function to run quick tests
quick_test() {
    echo -e "${GREEN}Running quick tests...${NC}"
    pytest tests/ -v --tb=short -x
}

# Main menu
case "$1" in
    start)
        start_dev
        ;;
    test)
        quick_test
        ;;
    *)
        echo "Usage: ./dev.sh {start|test}"
        exit 1
        ;;
esac
```

## Configuration Options

| Option                       | Description                        | Default | Example          |
| ---------------------------- | ---------------------------------- | ------- | ---------------- |
| `MCP_MESH_ENABLE_HOT_RELOAD` | Enable auto-reload on file changes | true    | false            |
| `MCP_MESH_RELOAD_DELAY`      | Delay before reload (ms)           | 500     | 1000             |
| `MCP_MESH_WATCH_EXTENSIONS`  | File extensions to watch           | .py     | .py,.yaml,.json  |
| `MCP_MESH_RELOAD_STRATEGY`   | How to reload                      | restart | restart, refresh |
| `MCP_MESH_PRESERVE_STATE`    | Keep agent state across reloads    | false   | true             |

## Examples

### Example 1: Development Workflow Script

```python
# agents/dev_utils.py
import os
import time
from datetime import datetime
from functools import wraps

def development_mode(func):
    """Decorator for development-only features"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if os.getenv('MCP_DEV_MODE') == 'true':
            print(f"[DEV] {func.__name__} called at {datetime.now()}")
            start = time.time()
            result = func(*args, **kwargs)
            print(f"[DEV] {func.__name__} took {time.time() - start:.3f}s")
            return result
        return func(*args, **kwargs)
    return wrapper

# State that persists across reloads
_persistent_cache = {}

def get_persistent_cache():
    """Access cache that survives hot reloads"""
    return _persistent_cache

@server.tool()
@mesh_agent(capability="dev_agent")
@development_mode
def process_with_cache(key: str, value: str = None):
    """Example using persistent cache"""
    cache = get_persistent_cache()

    if value is not None:
        cache[key] = value
        return f"Stored {key}={value}"

    return cache.get(key, "Not found")
```

### Example 2: Watch Configuration for Complex Project

```python
# watch_config.py
import watchdog.events
import watchdog.observers

class CustomReloadHandler(watchdog.events.FileSystemEventHandler):
    """Custom handler for fine-grained reload control"""

    def __init__(self, reload_callback):
        self.reload_callback = reload_callback
        self.last_reload = 0
        self.reload_delay = 0.5  # seconds

    def should_reload(self, event):
        """Determine if file change should trigger reload"""
        # Skip temporary files
        if event.src_path.endswith('.tmp') or '~' in event.src_path:
            return False

        # Skip test files during normal development
        if 'test_' in event.src_path and not os.getenv('RELOAD_TESTS'):
            return False

        # Debounce rapid changes
        current_time = time.time()
        if current_time - self.last_reload < self.reload_delay:
            return False

        self.last_reload = current_time
        return True

    def on_modified(self, event):
        if not event.is_directory and self.should_reload(event):
            print(f"Detected change in {event.src_path}")
            self.reload_callback(event.src_path)
```

## Best Practices

1. **Save Frequently**: Configure auto-save in your editor
2. **Small Changes**: Make incremental changes for faster feedback
3. **Watch Logs**: Keep a terminal open with filtered logs
4. **State Management**: Design agents to handle restart gracefully
5. **Exclude Tests**: Don't reload on test file changes during development

## Common Pitfalls

### Pitfall 1: Reload Loops

**Problem**: Agent crashes on startup, causing infinite reload loop

**Solution**: Add startup validation and circuit breaker:

```python
# At the top of your agent file
import sys
import time

# Simple circuit breaker
startup_file = '.startup_attempts'
max_attempts = 3
window_seconds = 10

try:
    with open(startup_file, 'r') as f:
        attempts = [float(line.strip()) for line in f]

    recent_attempts = [t for t in attempts if time.time() - t < window_seconds]

    if len(recent_attempts) >= max_attempts:
        print(f"Too many startup attempts ({len(recent_attempts)}) in {window_seconds}s")
        sys.exit(1)
except FileNotFoundError:
    recent_attempts = []

# Record this startup attempt
with open(startup_file, 'a') as f:
    f.write(f"{time.time()}\n")
```

### Pitfall 2: State Loss on Reload

**Problem**: In-memory state lost when agent reloads

**Solution**: Use external state storage:

```python
import pickle
import atexit

STATE_FILE = '.agent_state.pkl'

def save_state():
    """Save state before reload"""
    with open(STATE_FILE, 'wb') as f:
        pickle.dump({
            'cache': cache_data,
            'counters': counters,
            'timestamp': time.time()
        }, f)

def load_state():
    """Restore state after reload"""
    try:
        with open(STATE_FILE, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return {'cache': {}, 'counters': {}}

# Register save on exit
atexit.register(save_state)

# Load on startup
state = load_state()
```

## Testing

### Unit Test Example

```python
# tests/test_hot_reload.py
import os
import time
import tempfile
import shutil

def test_file_change_triggers_reload():
    """Test that modifying a file triggers reload"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test agent
        agent_file = os.path.join(tmpdir, 'test_agent.py')
        with open(agent_file, 'w') as f:
            f.write('# version 1\n')

        # Start monitoring (mock)
        changes_detected = []

        # Modify file
        time.sleep(1)
        with open(agent_file, 'a') as f:
            f.write('# version 2\n')

        # Verify reload triggered
        assert len(changes_detected) == 1
```

### Integration Test Example

```python
# tests/test_reload_integration.py
import subprocess
import requests
import time

def test_agent_survives_reload():
    """Test agent remains accessible after reload"""
    # Start agent with hot reload
    proc = subprocess.Popen([
        'mcp-mesh-dev', 'start', 'test_agent.py'
    ])

    time.sleep(3)

    # Verify agent is running
    response = requests.get('http://localhost:8888/health')
    assert response.status_code == 200

    # Modify agent file
    with open('test_agent.py', 'a') as f:
        f.write('\n# trigger reload\n')

    time.sleep(2)  # Wait for reload

    # Verify agent still accessible
    response = requests.get('http://localhost:8888/health')
    assert response.status_code == 200

    proc.terminate()
```

## Monitoring and Debugging

### Logs to Check

```bash
# Watch reload events
tail -f ~/.mcp-mesh/logs/mcp-mesh.log | grep -i reload

# Monitor file system events
inotifywait -m -r agents/ -e modify

# Track reload performance
grep "Reload completed" ~/.mcp-mesh/logs/mcp-mesh.log | tail -20
```

### Metrics to Monitor

- **Reload Time**: Should be < 2 seconds for most agents
- **Reload Frequency**: Too many reloads may indicate editor issues
- **Memory Growth**: Check for leaks across reloads

## 🔧 Troubleshooting

### Issue 1: Changes Not Triggering Reload

**Symptoms**: File saved but agent doesn't restart

**Cause**: File not in watch pattern or save not detected

**Solution**:

```bash
# Check if file is being watched
mcp-mesh-dev debug watches

# Force reload manually
touch agents/my_agent.py

# Check file system events
inotifywait -m agents/my_agent.py
```

### Issue 2: Slow Reload Performance

**Symptoms**: Reload takes > 5 seconds

**Cause**: Large imports or initialization code

**Solution**:

```python
# Move slow imports inside functions
def process_data():
    import pandas as pd  # Import only when needed
    return pd.DataFrame()

# Cache expensive initialization
_model = None

def get_model():
    global _model
    if _model is None:
        _model = load_expensive_model()
    return _model
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Import Caching**: Some Python imports may not reload properly
- **Global State**: Module-level state may persist incorrectly
- **File System Delays**: Network file systems may have delayed notifications

## 📝 TODO

- [ ] Add support for configuration file reload
- [ ] Implement smart reload (only affected agents)
- [ ] Add reload performance metrics
- [ ] Support for notebook-based development

## Summary

Hot reload dramatically improves your development workflow with MCP Mesh:

Key takeaways:

- 🔑 Automatic agent restart on code changes
- 🔑 Configurable watch patterns for your project structure
- 🔑 State preservation strategies for complex agents
- 🔑 Integration with development tools and editors

## Next Steps

Now let's learn how to write comprehensive tests for your agents.

Continue to [Testing Your Agents](./05-testing.md) →

---

💡 **Tip**: Use `entr` or `watchexec` for custom reload scripts: `ls agents/*.py | entr -r mcp-mesh-dev start agents/`

📚 **Reference**: [Python Import System](https://docs.python.org/3/reference/import.html)

🧪 **Try It**: Create an agent with a counter that increments on each request - make it persist across reloads
