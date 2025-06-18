# Local Development Troubleshooting Guide

> Quick solutions to common local development issues with MCP Mesh

## Overview

This guide provides solutions to frequently encountered issues during local development with MCP Mesh. Each issue includes symptoms, root causes, and step-by-step solutions.

## Quick Diagnostics

Run this diagnostic script to check your environment:

```bash
#!/bin/bash
echo "MCP Mesh Development Diagnostics"
echo "================================"

# Check Python version
echo -n "Python version: "
python --version 2>&1 || echo "NOT FOUND"

# Check MCP Mesh installation
echo -n "MCP Mesh build: "
ls bin/meshctl 2>&1 && echo "FOUND" || echo "NOT BUILT"

# Check CLI tool
echo -n "CLI tool: "
./bin/meshctl --version 2>&1 || echo "NOT WORKING"

# Check registry
echo -n "Registry status: "
curl -s http://localhost:8000/health | jq -r '.status' 2>&1 || echo "NOT RUNNING"

# Check environment
echo -e "\nEnvironment variables:"
env | grep MCP_MESH || echo "No MCP_MESH variables set"

# Check ports
echo -e "\nPort availability:"
for port in 8000 8081 8082; do
    nc -zv localhost $port 2>&1 | grep -q succeeded && echo "Port $port: IN USE" || echo "Port $port: AVAILABLE"
done
```

## Common Issues and Solutions

### Issue 1: MCP Mesh Import Error

**Symptoms:**

```python
ImportError: cannot import name 'agent' from 'mesh'
```

**Cause:** MCP Mesh not built or wrong Python path

**Solution:**

```bash
# Build MCP Mesh from source
cd /path/to/mcp-mesh
make install-dev

# Verify installation
python -c "from mesh import agent, tool; print('MCP Mesh imported successfully')"

# Check PYTHONPATH includes project
export PYTHONPATH=$PYTHONPATH:$(pwd)/src/runtime/python/src
```

### Issue 2: Registry Connection Failed

**Symptoms:**

```
Error: Failed to connect to registry at http://localhost:8000
Connection refused
```

**Cause:** Registry not running or using wrong port

**Solution:**

```bash
# Check if registry is running
ps aux | grep meshctl

# Check what's using port 8000
lsof -i :8000

# Start registry manually
./bin/meshctl start-registry

# Or kill existing process
kill $(lsof -t -i:8000)
```

### Issue 3: Database Connection Error

**Symptoms:**

```
Error: Registry connection failed or agent registration timeout
```

**Cause:** Registry not running or network connectivity issues

**Solution:**

```bash
# Start registry first
./bin/meshctl start-registry

# Wait for registry to be ready
until curl -s http://localhost:8000/health; do sleep 1; done

# Then start agents
./bin/meshctl start examples/simple/my_agent.py

# For Docker environment
cd examples/docker-examples
docker-compose up --build
```

### Issue 4: Agent Auto-Restart

**Symptoms:**

- Need to manually restart agents after code changes
- No automatic reload functionality

**Cause:** Built-in hot reload not implemented

**Solution:**

```bash
# Use external file watchers
# Install entr: brew install entr (macOS) or apt install entr (Linux)
ls examples/simple/*.py | entr -r ./bin/meshctl start examples/simple/my_agent.py

# Alternative with watchexec
watchexec -e py -r "./bin/meshctl start examples/simple/my_agent.py"

# Use Docker Compose for development with auto-rebuild
cd examples/docker-examples
docker-compose up --build
```

### Issue 5: Port Already in Use

**Symptoms:**

```
Error: address already in use :::8081
```

**Cause:** Previous agent still running or port conflict

**Solution:**

```bash
# Find process using port
lsof -i :8081
# or on Windows
netstat -ano | findstr :8081

# Kill the process
kill -9 $(lsof -t -i:8081)

# Agent ports are auto-assigned by default
# Check actual ports with:
./bin/meshctl list agents
```

### Issue 6: Virtual Environment Issues

**Symptoms:**

- Package conflicts
- "No module named 'venv'"
- Permission errors

**Solution:**

```bash
# Create fresh virtual environment
python -m venv .venv --clear

# Activate it
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### Issue 7: Memory/Resource Issues

**Symptoms:**

- Agent crashes with no error
- System becomes slow
- "Cannot allocate memory"

**Solution:**

```bash
# Check memory usage
free -h  # Linux
# or use Activity Monitor on macOS

# Limit agent memory
export MCP_MESH_MAX_MEMORY=512M

# Check for memory leaks
python -m tracemalloc agents/my_agent.py

# Use memory profiler
pip install memory_profiler
python -m memory_profiler agents/my_agent.py
```

### Issue 8: Debugging Not Working

**Symptoms:**

- Breakpoints ignored
- Can't attach debugger
- No debug output

**Solution:**

```python
# Enable debug mode explicitly
import os
os.environ['MCP_MESH_DEBUG_MODE'] = 'true'
os.environ['MCP_MESH_LOG_LEVEL'] = 'DEBUG'
os.environ['PYTHONBREAKPOINT'] = 'ipdb.set_trace'

# For VS Code debugging
{
  "justMyCode": false,  // Debug into libraries
  "subProcess": true    // Debug child processes
}

# Force sync logging
import sys
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
```

### Issue 9: Test Failures

**Symptoms:**

- Tests pass individually but fail together
- Import errors in tests
- Async test timeouts

**Solution:**

```bash
# Run tests in isolation
pytest -k test_name -s

# Clear test cache
pytest --cache-clear

# Fix import paths
export PYTHONPATH=$PYTHONPATH:.

# Increase async timeout
pytest --timeout=30

# Run with more debugging
pytest -vvs --tb=short --log-cli-level=DEBUG
```

### Issue 10: Agent Registration Issues

**Symptoms:**

- Agent starts but doesn't appear in registry
- "Failed to register with registry"

**Solution:**

```python
# Check agent registration status
./bin/meshctl list agents

# Check registry connectivity
curl http://localhost:8000/health
curl http://localhost:8000/agents

# Enable debug logging
export MCP_MESH_DEBUG_MODE=true
./bin/meshctl start examples/simple/my_agent.py

# Verify agent metadata
print(f"Registering as: {agent_name}")
print(f"Capabilities: {capabilities}")
print(f"Registry URL: {registry_url}")
```

## Performance Issues

### Slow Startup

**Solution:**

```python
# Profile imports
python -X importtime examples/simple/my_agent.py

# Lazy load heavy imports
def get_pandas():
    import pandas as pd
    return pd

# Precompile Python files
python -m compileall examples/simple/
```

### High CPU Usage

**Solution:**

```bash
# Profile CPU usage
python -m cProfile -o profile.stats examples/simple/my_agent.py
python -m pstats profile.stats

# Use process monitoring
htop  # Linux/macOS
# Filter by python processes
```

## Environment-Specific Issues

### macOS Issues

```bash
# Fix SSL certificate issues
pip install --upgrade certifi

# Fix fork() issues
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# Use homebrew Python
brew install python@3.11
```

### Windows Issues

```bash
# Use WSL2 for better compatibility
wsl --install

# Or use PowerShell with proper execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Fix path length issues
git config --global core.longpaths true
```

### Linux Issues

```bash
# Fix permissions
chmod +x .venv/bin/activate
chmod 755 mcp-mesh-dev

# Install system dependencies
sudo apt-get update
sudo apt-get install python3-dev build-essential
```

## Getting More Help

If these solutions don't resolve your issue:

1. **Check Logs:**

   ```bash
   tail -f ~/.mcp-mesh/logs/mcp-mesh.log
   tail -f agent_debug.log
   ```

2. **Enable Verbose Logging:**

   ```bash
   export MCP_MESH_LOG_LEVEL=DEBUG
   export MCP_MESH_DEBUG_INJECTION=true
   ```

3. **Community Resources:**

   - GitHub Issues: https://github.com/dhyansraj/mcp-mesh/issues
   - Discord: [MCP Community](https://discord.gg/mcp)
   - Stack Overflow: Tag with `mcp-mesh`

4. **Create Minimal Reproduction:**

   ```python
   # minimal_repro.py
   from mesh import agent, tool

   @agent(name="minimal-test")
   class MinimalAgent:
       pass

   @tool(capability="minimal")
   def test_function():
       return "If this fails, something is very wrong"

   if __name__ == "__main__":
       # Run with: ./bin/meshctl start minimal_repro.py
       pass
   ```

---

💡 **Tip**: Keep a `debug.log` file with solutions that worked for your specific setup

📚 **Reference**: [Python Debugging Guide](https://realpython.com/python-debugging-pdb/)

🔍 **Debug Mode**: Set `MCP_MESH_LOG_LEVEL=DEBUG` for maximum visibility into issues
