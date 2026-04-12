# weather-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner weather forecast tool (Day 2). Returns weather forecasts for a location.

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

The agent will start on port 9103 by default.

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `get_weather` | `weather_forecast` | Get weather forecast for a location |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
