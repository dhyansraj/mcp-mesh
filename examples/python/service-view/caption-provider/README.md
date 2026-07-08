# caption-provider

Provider A in the [`@mesh.service` service-view example](../README.md).

## Overview

A Python MCP Mesh agent. Publishes the `media.caption` capability with an
explicit `@mesh.tool(capability="media.caption")` — the dotted wire capability is
declared deliberately, never derived from the Python method name.

The `media.*` capability + its parameters match the Java and TypeScript
providers exactly, so gateways in ANY runtime are interchangeable.

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

The agent will start on port 8120 by default. Override with the
`MCP_MESH_HTTP_PORT` environment variable or the `http_port` parameter in the
`@mesh.agent` decorator.

## Project Structure

```text
caption-provider/
├── main.py            # agent bootstrap + @mesh.tool(capability="media.caption")
├── requirements.txt
├── Dockerfile
├── helm-values.yaml
├── __init__.py
└── __main__.py
```

## Docker

```bash
docker build -t caption-provider:latest .
docker run -p 8120:8120 caption-provider:latest
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
