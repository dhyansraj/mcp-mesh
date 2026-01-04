# Troubleshooting Guide - Getting Started

> Solutions to common issues when starting with MCP Mesh

## Quick Diagnostics

Run this diagnostic script to check common issues:

```bash
#!/bin/bash
# save as diagnose.sh

echo "MCP Mesh Diagnostic Tool"
echo "======================="

# Check Python version
echo -n "Python version: "
python3 --version || echo "❌ Python not found"

# Check if MCP Mesh is installed
echo -n "MCP Mesh installed: "
python3 -c "import mcp_mesh; print('✅ Yes')" 2>/dev/null || echo "❌ No"

# Check ports
for port in 8000 8080 8081; do
    echo -n "Port $port: "
    if lsof -i :$port >/dev/null 2>&1; then
        echo "❌ In use"
    else
        echo "✅ Available"
    fi
done

# Check registry
echo -n "Registry health: "
curl -s http://localhost:8000/health >/dev/null 2>&1 && echo "✅ Healthy" || echo "❌ Not reachable"
```

## Common Issues and Solutions

### 1. Python Import Errors

#### Problem

```
ImportError: No module named 'mcp_mesh'
```

#### Solutions

**Check virtual environment is activated:**

```bash
# Should show your venv path
which python

# If not, activate it
source venv/bin/activate  # or .venv/bin/activate
```

**Reinstall MCP Mesh:**

```bash
pip uninstall mcp-mesh
pip install mcp-mesh
```

**Check installation:**

```bash
pip list | grep mcp-mesh
python -c "import mcp_mesh; print(mcp_mesh.__version__)"
```

### 2. Registry Connection Failed

#### Problem

```
ERROR: Failed to connect to registry at http://localhost:8000
Connection refused
```

#### Solutions

**Start the registry:**

```bash
# In a separate terminal
python -m mcp_mesh.registry.server

# Or with custom port
python -m mcp_mesh.registry.server --port 8001
```

**Check if registry is running:**

```bash
# Check process
ps aux | grep mcp_mesh.registry

# Check port
lsof -i :8000

# Test health endpoint
curl http://localhost:8000/health
```

**Use correct registry URL:**

```bash
# Set environment variable
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Or pass directly to agent
python my_agent.py --registry-url http://localhost:8000
```

### 3. Port Already in Use

#### Problem

```
OSError: [Errno 48] Address already in use
```

#### Solutions

**Find what's using the port:**

```bash
# On macOS/Linux
lsof -i :8080

# On Windows
netstat -ano | findstr :8080
```

**Kill the process:**

```bash
# Get PID from lsof output
kill -9 <PID>

# Or kill by port (macOS/Linux)
kill -9 $(lsof -t -i:8080)
```

**Use a different port:**

```python
# In your agent
@mesh_agent(
    capability="my_agent",
    enable_http=True,
    http_port=8090  # Different port
)
```

### 4. Dependency Not Resolved

#### Problem

```
ERROR: Failed to resolve dependency: SystemAgent_getDate
No agents found providing capability: SystemAgent
```

#### Solutions

**Ensure dependency agent is running:**

```bash
# Start the system agent
cd examples
python system_agent.py
```

**Check agent registration:**

```bash
# List all agents
curl http://localhost:8000/agents

# Check specific capability
curl http://localhost:8000/agents?capability=SystemAgent
```

**Verify dependency name:**

```python
# Dependency names must match exactly
dependencies=["SystemAgent_getDate"]  # Correct
dependencies=["systemagent_getdate"]  # Wrong - case sensitive
dependencies=["SystemAgent.getDate"]  # Wrong - use underscore
```

### 5. Agent Registration Failed

#### Problem

```
ERROR: Agent registration failed: 400 Bad Request
```

#### Solutions

**Check agent configuration:**

```python
@mesh_agent(
    capability="weather",  # Must be non-empty
    version="1.0.0",      # Must be valid semver
    enable_http=True,
    http_port=8080        # Must be valid port
)
```

**Enable debug logging:**

```bash
export MCP_MESH_LOG_LEVEL=DEBUG
python my_agent.py
```

**Verify network connectivity:**

```bash
# Can you reach the registry?
ping localhost
curl http://localhost:8000/health

# Check firewall
sudo iptables -L  # Linux
sudo pfctl -s rules  # macOS
```

### 6. Heartbeat Failures

#### Problem

```
WARNING: Heartbeat failed: Connection timeout
Agent marked as unhealthy
```

#### Solutions

**Increase heartbeat interval:**

```python
@mesh_agent(
    capability="slow_agent",
    heartbeat_interval=60,  # Increase from default 30s
    heartbeat_timeout=10    # Increase timeout
)
```

**Check network stability:**

```bash
# Monitor network
ping -c 100 localhost

# Check for packet loss
mtr localhost
```

### 7. Performance Issues

#### Problem

- Slow agent startup
- High latency between agents
- Memory usage growing

#### Solutions

**Profile your code:**

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your agent code

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(10)
```

**Enable connection pooling:**

```python
# In your agent initialization
import aiohttp

connector = aiohttp.TCPConnector(
    limit=100,
    limit_per_host=30,
    ttl_dns_cache=300
)
```

**Monitor memory:**

```python
import tracemalloc
tracemalloc.start()

# Your code

current, peak = tracemalloc.get_traced_memory()
print(f"Current memory: {current / 10**6:.1f} MB")
print(f"Peak memory: {peak / 10**6:.1f} MB")
```

### 8. Docker/Container Issues

#### Problem

- Container can't connect to registry
- Agents can't find each other in containers

#### Solutions

**Use correct network:**

```yaml
# docker-compose.yml
services:
  agent:
    networks:
      - mcp-mesh
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000

networks:
  mcp-mesh:
    driver: bridge
```

**Use container names:**

```bash
# Not localhost when in containers
export MCP_MESH_REGISTRY_URL=http://mcp-core-mcp-mesh-registry:8000
```

### 9. Windows-Specific Issues

#### Problem

- Path separator issues
- Encoding problems
- Process management

#### Solutions

**Use pathlib for paths:**

```python
from pathlib import Path

config_path = Path("configs") / "agent.yaml"
```

**Set encoding:**

```python
# At top of file
# -*- coding: utf-8 -*-

# When opening files
with open(file, 'r', encoding='utf-8') as f:
    content = f.read()
```

**Use cross-platform commands:**

```python
import sys
import subprocess

if sys.platform == "win32":
    subprocess.run(["cmd", "/c", "dir"])
else:
    subprocess.run(["ls", "-la"])
```

## Debug Techniques

### 1. Enable Verbose Logging

```python
import logging
import sys

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('debug.log')
    ]
)

# Enable HTTP request logging
logging.getLogger('aiohttp').setLevel(logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.DEBUG)
```

### 2. Use Registry API

```bash
# Get all agents
curl http://localhost:8000/agents | jq

# Get agent details
curl http://localhost:8000/agents/<agent-id> | jq

# Check dependencies
curl http://localhost:8000/dependencies | jq

# View logs
curl http://localhost:8000/logs?level=error | jq
```

### 3. Test Individual Components

```python
# test_components.py
import asyncio
from mcp_mesh.registry import RegistryClient

async def test_registry():
    client = RegistryClient("http://localhost:8000")

    # Test connection
    health = await client.health_check()
    print(f"Registry health: {health}")

    # Test registration
    agent_id = await client.register_agent({
        "name": "test-agent",
        "capabilities": ["test"],
        "endpoint": "http://localhost:9999"
    })
    print(f"Registered with ID: {agent_id}")

    # Test discovery
    agents = await client.find_agents("test")
    print(f"Found agents: {agents}")

asyncio.run(test_registry())
```

## Getting Help

### 1. Gather Information

Before asking for help, collect:

```bash
# System info
python --version
pip list | grep mcp
uname -a  # or system info on Windows

# Error logs
python my_agent.py 2>&1 | tee error.log

# Registry state
curl http://localhost:8000/agents > agents.json
curl http://localhost:8000/health > health.json
```

### 2. Check Resources

1. [GitHub Issues](https://github.com/dhyansraj/mcp-mesh/issues)
2. [GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)
3. [Discord Community](https://discord.gg/KDFDREphWn)

### 3. Report Issues

Include in your report:

- MCP Mesh version
- Python version
- Operating system
- Full error message
- Minimal code to reproduce
- What you've already tried

## Prevention Tips

1. **Always use virtual environments**
2. **Keep dependencies updated**
3. **Use consistent Python versions**
4. **Test in Docker before production**
5. **Monitor logs continuously**
6. **Set up health checks**
7. **Use connection pooling**
8. **Handle errors gracefully**

---

💡 **Quick Fix**: Most issues are resolved by: 1) Checking the registry is running, 2) Verifying ports are available, 3) Ensuring virtual environment is activated.

📚 **Next Steps**: If you're still having issues, ask in the [community Discord](https://discord.gg/KDFDREphWn) or open an issue on [GitHub](https://github.com/dhyansraj/mcp-mesh/issues).
