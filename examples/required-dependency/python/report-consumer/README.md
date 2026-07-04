# report-consumer

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

The agent will start on port 8081 by default.

To override the port, modify the `http_port` parameter in the `@mesh.agent` decorator.

## Available Tools

| Tool | Description |
|------|-------------|
| `report` | Builds a report from the required data_service |

## Project Structure

```
report-consumer/
├── __init__.py        # Package init
├── __main__.py        # Module entry point
├── main.py            # Agent implementation
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container image definition for local docker compose / k8s
├── .dockerignore      # Files to exclude from docker build context
├── helm-values.yaml   # Values for the mcp-mesh-agent Helm chart deployment
└── README.md          # This file
```

## Docker

```bash
# Build the image
docker build -t report-consumer:latest .

# Run the container
docker run -p 8081:8081 report-consumer:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install report-consumer oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/report-consumer \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Python SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/python)
- Run `meshctl man decorators` for decorator reference

## License

MIT
