# thumbnail-provider

Provider B (optional edge — stop it to see graceful degradation) in the [`@mesh.service` service-view example](../README.md).

## Overview

A Python MCP Mesh agent. Publishes the `media.thumbnail` capability via **producer sugar**:
the `@mesh.service("media")` class exposes one public async method, so the mesh
publishes it as the dotted capability `media.thumbnail` — no per-method `@mesh.tool`.

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

The agent will start on port 8121 by default. Override with the
`MCP_MESH_HTTP_PORT` environment variable or the `http_port` parameter in the
`@mesh.agent` decorator.

## Project Structure

```text
thumbnail-provider/
├── main.py            # agent bootstrap + @mesh.service("media") producer
├── requirements.txt
├── Dockerfile
├── helm-values.yaml
├── __init__.py
└── __main__.py
```

## Docker

```bash
docker build -t thumbnail-provider:latest .
docker run -p 8121:8121 thumbnail-provider:latest
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
