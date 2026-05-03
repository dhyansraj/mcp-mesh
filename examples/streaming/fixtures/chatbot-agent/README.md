# chatbot-agent

Streaming chatbot agent — backend for the issue #645 streaming demo.

## Overview

Exposes a single `chat` capability declared as `mesh.Stream[str]`. The
mesh runtime detects the streaming return annotation and forwards each
yielded chunk to consumers via FastMCP `Context.report_progress(message=chunk)`.

The tool body either:

- streams real LLM tokens via `MeshLlmAgent.stream(prompt)` (the new P1 method), or
- when `MESH_LLM_DRY_RUN=1` is set, yields a deterministic chunk sequence so
  tsuite tests can run without an Anthropic API key.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- For real-LLM mode: an LLM provider agent registered with `capability=llm`
  and a `claude` tag (e.g. one of the agents in `examples/llm-mesh-delegation/`
  or `examples/python/llm-provider/`).

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

Real-LLM mode (requires a claude provider on the mesh):

```bash
meshctl start main.py
```

Dry-run mode (no LLM provider needed):

```bash
MESH_LLM_DRY_RUN=1 meshctl start main.py
```

Default port: 9170.

## Available Tools

| Tool | Capability | Return type | Description |
|------|------------|-------------|-------------|
| `chat` | `chat` | `mesh.Stream[str]` | Stream a chat response token-by-token |

## Project Structure

```text
chatbot-agent/
├── __init__.py            # Package init
├── __main__.py            # Module entry point
├── Dockerfile             # Container build
├── helm-values.yaml       # Helm values for K8s deployment
├── main.py                # Agent implementation
├── prompts/
│   └── chatbot-agent.jinja2  # Optional system prompt template (not currently wired)
├── README.md              # This file
└── requirements.txt       # Python dependencies
```

## Docker

```bash
docker build -t chatbot-agent:latest .
docker run -p 9170:9170 -e MESH_LLM_DRY_RUN=1 chatbot-agent:latest
```

## Kubernetes

```bash
helm install chatbot-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/chatbot-agent \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
