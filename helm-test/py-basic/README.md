# py-basic

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

The agent will start on port 8080 by default.

To override the port, modify the `http_port` parameter in the `@mesh.agent` decorator.

## Available Tools

| Tool    | Capability | Description          |
| ------- | ---------- | -------------------- |
| `hello` | `hello`    | Say hello to someone |
| `echo`  | `echo`     | Echo a message back  |

## Project Structure

```
py-basic/
├── __init__.py       # Package init
├── __main__.py       # Module entry point
├── main.py           # Agent implementation
├── README.md         # This file
└── requirements.txt  # Python dependencies
```

## Docker

```bash
# Build the image
docker build -t py-basic:latest .

# Run the container
docker run -p 8080:8080 py-basic:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install py-basic oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/py-basic \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Python SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/python)
- Run `meshctl man decorators` for decorator reference

## License

MIT
