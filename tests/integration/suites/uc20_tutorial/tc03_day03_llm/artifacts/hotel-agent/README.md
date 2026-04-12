# hotel-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner hotel search tool (Day 2). Searches for hotels at a destination.

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

The agent will start on port 9102 by default.

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `hotel_search` | `hotel_search` | Search for hotels at a destination |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
