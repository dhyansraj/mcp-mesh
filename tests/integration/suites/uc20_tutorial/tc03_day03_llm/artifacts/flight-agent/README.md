# flight-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner flight search tool (Day 2). Searches for flights personalized with user preferences via dependency injection.

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

Or with debug logging:

```bash
meshctl start main.py --debug
```

The agent will start on port 9101 by default.

## Available Tools

| Tool | Capability | Description | Dependencies |
|------|------------|-------------|--------------|
| `flight_search` | `flight_search` | Search for flights between two cities | `user_preferences` |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
