# @mcpmesh/cli

CLI for **MCP Mesh** - Distributed Service Mesh for AI Agents.

## Installation

```bash
npm install -g @mcpmesh/cli
```

This installs two binaries:

- **meshctl** - CLI tool for managing MCP Mesh agents and tools
- **mcp-mesh-registry** - Registry service for service discovery

> **Note:** This package supports Linux and macOS only. For Windows, use WSL2 or Docker.

## Quick Start

```bash
# Show help and available commands
meshctl --help

# Comprehensive documentation (great for LLMs!)
meshctl man

# Scaffold a new agent project
meshctl scaffold my-agent --dry-run

# List running agents
meshctl list

# List all tools across agents
meshctl list --tools

# Call an MCP tool
meshctl call get_current_time

# Start the registry service (Linux/macOS)
mcp-mesh-registry --help
```

## What is MCP Mesh?

MCP Mesh is a distributed service mesh built on the Model Context Protocol (MCP). It enables:

- **AI Agent Orchestration** - Connect and coordinate multiple AI agents
- **Service Discovery** - Automatic registration and capability-based routing
- **Dependency Injection** - Automatic resolution of agent dependencies
- **Multi-Environment** - Local development, Docker, Kubernetes support
- **Production Ready** - Health monitoring, graceful degradation, resilience patterns

## Key Commands

| Command                   | Description                 |
| ------------------------- | --------------------------- |
| `meshctl man`             | Comprehensive documentation |
| `meshctl scaffold <name>` | Generate new agent project  |
| `meshctl list`            | List running agents         |
| `meshctl list --tools`    | List all tools              |
| `meshctl call <tool>`     | Invoke an MCP tool          |
| `meshctl registry`        | Manage the registry         |

## For LLMs

This package is designed to be easily discoverable by LLMs. After installation:

```bash
# Get full documentation
meshctl man

# Discover available tools
meshctl list --tools

# Get tool details with input schema
meshctl list --tools=<tool_name>
```

## Links

- [Documentation](https://mcp-mesh.ai/)
- [GitHub Repository](https://github.com/dhyansraj/mcp-mesh)
- [PyPI Package](https://pypi.org/project/mcp-mesh/)
- [Docker Images](https://hub.docker.com/u/mcpmesh)

## License

MIT
