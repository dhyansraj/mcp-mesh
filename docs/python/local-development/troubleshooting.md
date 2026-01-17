# Troubleshooting (Python)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/troubleshooting/">TypeScript Troubleshooting</a></span>
</div>

> Common issues and solutions for MCP Mesh Python development

## Quick Diagnostics

```bash
# Check CLI is installed
meshctl --version

# Check registry is running
curl http://localhost:8000/health

# List agents and their status
meshctl list --all

# Check agent logs
meshctl logs <agent-name> --since 5m
```

## Registry Issues

### Registry Not Running

**Symptom:** `Connection refused` when starting agents

```bash
# Start registry manually
meshctl start --registry-only

# Or start an agent (registry auto-starts)
meshctl start main.py
```

### Port 8000 Already in Use

```bash
# Find what's using the port
lsof -i :8000

# Kill it
kill $(lsof -t -i:8000)

# Or use a different port
meshctl start --registry-port 9000 main.py
```

## Agent Issues

### Agent Not Appearing in Registry

```bash
# Check agent is running
meshctl list --all

# Enable debug logging
meshctl start --debug main.py

# Check for registration errors in logs
meshctl logs my-agent --since 5m | grep -i error
```

### Dependencies Not Resolved

**Symptom:** Agent shows `1/2` in DEPS column

```bash
# See which dependencies are missing
meshctl status my-agent

# Check if the providing agent is running
meshctl list

# Start the missing agent
meshctl start provider-agent.py
```

### Port Conflict Between Agents

**Symptom:** `address already in use`

Agents auto-assign ports by default. If you've hardcoded ports:

```python
# Don't do this for local dev
@mesh.agent(name="my-agent", http_port=8080)  # Conflicts!

# Do this instead - let mesh assign ports
@mesh.agent(name="my-agent", http_port=0)  # Auto-assign
```

## Tool Call Issues

### Tool Not Found

```bash
# List all available tools
meshctl list --tools

# Check tool details
meshctl list --tools=my_tool_name
```

### Call Timeout

```bash
# Increase timeout (default 30s)
meshctl call --timeout 60 slow_operation

# Check if agent is healthy
meshctl list
```

### Wrong Arguments

```bash
# Check tool's expected schema
meshctl list --tools=my_tool_name

# Shows parameter types and required fields
```

## Import Issues

### `ImportError: cannot import name 'agent' from 'mesh'`

```bash
# Verify SDK is installed
pip show mcp-mesh

# Reinstall if needed
pip install --force-reinstall "mcp-mesh>=0.8,<0.9"

# Check Python path
python -c "import mesh; print(mesh.__file__)"
```

## Logging & Debugging

### Enable Debug Logging

```bash
# Via CLI flag
meshctl start --debug main.py

# Or via log level
meshctl start --log-level DEBUG main.py

# TRACE level for SQL queries
meshctl start --log-level TRACE main.py
```

### View Distributed Trace

```bash
# Call with tracing
meshctl call --trace my_tool

# View the trace tree
meshctl trace <trace-id>
```

## Getting Help

```bash
# Built-in documentation
meshctl man --list
meshctl man <topic>

# Command help
meshctl <command> --help
```

## Still Stuck?

1. Check [GitHub Issues](https://github.com/dhyansraj/mcp-mesh/issues)
2. Enable `--debug` and share the logs
3. Create a minimal reproduction case
