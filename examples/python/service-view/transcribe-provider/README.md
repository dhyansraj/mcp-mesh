# transcribe-provider

Provider C (optional edge) in the [`@mesh.service` service-view example](../README.md).

## Overview

A Python MCP Mesh agent. Publishes the `media.transcribe` capability with an
explicit `@mesh.tool(capability="media.transcribe")` — the dotted wire capability
is declared deliberately, never derived from the Python method name.

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

The agent will start on port 8122 by default. Override with the
`MCP_MESH_HTTP_PORT` environment variable or the `http_port` parameter in the
`@mesh.agent` decorator.

## Project Structure

```text
transcribe-provider/
├── main.py            # agent bootstrap + @mesh.tool(capability="media.transcribe")
├── requirements.txt
├── Dockerfile
├── helm-values.yaml
├── __init__.py
└── __main__.py
```

## Docker

```bash
docker build -t transcribe-provider:latest .
docker run -p 8122:8122 transcribe-provider:latest
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
