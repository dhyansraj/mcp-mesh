# weather-tool

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

This is a basic MCP Mesh agent that provides simple tools for demonstration.

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

The agent will start on port 9180 by default.

To override the port, modify the `http_port` parameter in the `@mesh.agent` decorator.

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `get_weather` | `get_weather` | Fetch current temperature and conditions for a city via Open-Meteo (no API key required) |

## Project Structure

```
weather-tool/
├── __init__.py       # Package init
├── __main__.py       # Module entry point
├── main.py           # Agent implementation
├── README.md         # This file
└── requirements.txt  # Python dependencies
```

## Docker

```bash
# Build the image
docker build -t weather-tool:latest .

# Run the container
docker run -p 9180:9180 weather-tool:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install weather-tool oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/weather-tool \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Python SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/python)
- Run `meshctl man decorators` for decorator reference

## License

MIT
