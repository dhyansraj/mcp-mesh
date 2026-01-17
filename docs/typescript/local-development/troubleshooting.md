# Troubleshooting (TypeScript)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/local-development/troubleshooting/">Python Troubleshooting</a></span>
</div>

> Common issues and solutions for MCP Mesh TypeScript development

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
meshctl start src/index.ts
```

### Port 8000 Already in Use

```bash
# Find what's using the port
lsof -i :8000

# Kill it
kill $(lsof -t -i:8000)

# Or use a different port
meshctl start --registry-port 9000 src/index.ts
```

## Agent Issues

### Agent Not Appearing in Registry

```bash
# Check agent is running
meshctl list --all

# Enable debug logging
meshctl start --debug src/index.ts

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
meshctl start provider-agent/src/index.ts
```

### Port Conflict Between Agents

**Symptom:** `EADDRINUSE: address already in use`

Agents auto-assign ports by default. If you've hardcoded ports:

```typescript
// Don't do this for local dev
const agent = mesh(server, { name: "my-agent", port: 8080 }); // Conflicts!

// Do this instead - let mesh assign ports
const agent = mesh(server, { name: "my-agent", port: 0 }); // Auto-assign
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

## TypeScript Issues

### Module Import Errors

```bash
# Verify SDK is installed
npm list @mcpmesh/sdk

# Reinstall if needed
npm install @mcpmesh/sdk zod

# Check package.json has "type": "module"
```

### tsx Not Found

```bash
# Install tsx
npm install -D tsx

# Verify it works
npx tsx --version
```

## Logging & Debugging

### Enable Debug Logging

```bash
# Via CLI flag
meshctl start --debug src/index.ts

# Or via log level
meshctl start --log-level DEBUG src/index.ts

# TRACE level for SQL queries
meshctl start --log-level TRACE src/index.ts
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
