# meshctl CLI Reference

> Command-line tool for MCP Mesh development and operations

## Overview

`meshctl` is the command-line interface for MCP Mesh. It provides commands for:

- Starting and managing agents
- Calling tools and capabilities
- Scaffolding new agents
- Viewing documentation

## Installation

meshctl is included with the Python package:

```bash
pip install mcp-mesh
meshctl --version
```

## Commands

| Command                   | Description            |
| ------------------------- | ---------------------- |
| [`start`](start.md)       | Start an agent         |
| [`call`](call.md)         | Call a tool            |
| [`list`](list.md)         | List registered agents |
| [`scaffold`](scaffold.md) | Generate agent code    |
| [`man`](man.md)           | View documentation     |
| `status`                  | Show agent status      |
| `registry`                | Manage registry        |

## Quick Reference

### Start an Agent

```bash
# Basic start
meshctl start my_agent.py

# With hot reload
meshctl start my_agent.py --watch

# TypeScript
meshctl start my_agent.ts

# Custom port
meshctl start my_agent.py --port 9090
```

### Call a Tool

```bash
# Simple call
meshctl call hello

# With arguments
meshctl call hello --name "World"

# With JSON arguments
meshctl call process --data '{"key": "value"}'
```

### List Agents

```bash
# List all agents
meshctl list

# Filter by capability
meshctl list --capability greeting

# JSON output
meshctl list --json
```

### Scaffold Agent

```bash
# Interactive
meshctl scaffold

# Non-interactive
meshctl scaffold --name my-agent --agent-type tool

# TypeScript
meshctl scaffold --name my-agent --lang typescript
```

### View Documentation

```bash
# List topics
meshctl man --list

# View topic
meshctl man decorators

# TypeScript version
meshctl man decorators --typescript
```

## Global Options

| Option           | Description                              |
| ---------------- | ---------------------------------------- |
| `--help`         | Show help                                |
| `--version`      | Show version                             |
| `--log-level`    | Set log level (debug, info, warn, error) |
| `--registry-url` | Override registry URL                    |

## Environment Variables

```bash
# Registry URL
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Log level
export MCP_MESH_LOG_LEVEL=debug

# Namespace
export MCP_MESH_NAMESPACE=development
```

## See Also

- [start](start.md) - Start agents
- [call](call.md) - Call tools
- [list](list.md) - List agents
- [scaffold](scaffold.md) - Generate code
- [man](man.md) - Documentation
