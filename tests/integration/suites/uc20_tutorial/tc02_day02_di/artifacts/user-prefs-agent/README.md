# user-prefs-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner user preferences tool (Day 2). Returns user travel preferences.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- FastMCP

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

```bash
meshctl start main.py
```

The agent will start on port 9105 by default.

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `get_user_prefs` | `user_preferences` | Get user travel preferences |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
