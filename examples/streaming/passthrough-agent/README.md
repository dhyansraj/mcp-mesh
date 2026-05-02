# passthrough-agent

Multi-hop streaming intermediary — middle node of the issue #645 streaming demo.

## Overview

Exposes a `chat_passthrough` capability declared as `mesh.Stream[str]`
that depends on the upstream `chat` capability (provided by `chatbot-agent`).
The body is a pure passthrough:

```python
async for chunk in chat.stream(prompt=prompt):
    yield chunk
```

This proves chunks flow correctly across multiple mesh hops without
buffering — A → B → C all advertise `mesh.Stream[str]`.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- A running upstream `chat` capability (e.g. `chatbot-agent` from the same directory)

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

```bash
meshctl start main.py
```

Default port: 9171.

## Available Tools

| Tool | Capability | Return type | Dependencies | Description |
|------|------------|-------------|--------------|-------------|
| `chat_passthrough` | `chat_passthrough` | `mesh.Stream[str]` | `chat` | Re-emit the upstream chat stream |

## Project Structure

```
passthrough-agent/
├── __init__.py       # Package init
├── __main__.py       # Module entry point
├── Dockerfile        # Container build
├── helm-values.yaml  # Helm values for K8s deployment
├── main.py           # Agent implementation
├── README.md         # This file
└── requirements.txt  # Python dependencies
```

## Docker

```bash
docker build -t passthrough-agent:latest .
docker run -p 9171:9171 passthrough-agent:latest
```

## Kubernetes

```bash
helm install passthrough-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/passthrough-agent \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
