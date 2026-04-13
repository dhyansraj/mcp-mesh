# poi-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner points-of-interest tool (Day 2). Finds POIs adjusted for weather conditions via dependency injection.

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

The agent will start on port 9104 by default.

## Available Tools

| Tool | Capability | Description | Dependencies |
|------|------------|-------------|--------------|
| `search_pois` | `poi_search` | Search for points of interest | `weather_forecast` |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
