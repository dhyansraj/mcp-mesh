# gateway-agent

HTTP/SSE gateway for the issue #645 streaming demo.

## Overview

A FastAPI app whose streaming endpoints are auto-wrapped as Server-Sent
Events by the P3 SSE adapter. Endpoints whose handlers return
`mesh.Stream[str]` produce `text/event-stream` responses with
`data: <chunk>\n\n` framing terminated by `data: [DONE]\n\n`. Non-streaming
endpoints continue to return JSON as usual.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- FastAPI + Uvicorn
- Running `chatbot-agent` (provides `chat`) and optionally `passthrough-agent`
  (provides `chat_passthrough`).

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

```bash
meshctl start main.py
```

Default port: 9172.

## Available Endpoints

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| GET    | `/`                 | HTML / JSON      | Demo page (or route listing if static missing) |
| GET    | `/api/health`       | JSON             | Plain health check (NOT streaming — verifies P3 doesn't regress non-streaming routes) |
| POST   | `/api/chat`         | `text/event-stream` | Single-hop SSE: gateway → chat |
| POST   | `/api/chat-multihop`| `text/event-stream` | Multi-hop SSE: gateway → chat_passthrough → chat |
| GET    | `/static/*`         | static assets    | Mounted from `static/` |

### Example

```bash
# SSE single-hop
curl -N -X POST http://localhost:9172/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hi"}'

# SSE multi-hop (proves passthrough works)
curl -N -X POST http://localhost:9172/api/chat-multihop \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hi"}'

# Plain JSON health
curl http://localhost:9172/api/health
```

A minimal browser demo lives at `static/index.html` and is served at `/`.

## Project Structure

```
gateway-agent/
├── __init__.py            # Package init
├── __main__.py            # Module entry point
├── Dockerfile             # Container build
├── helm-values.yaml       # Helm values for K8s deployment
├── main.py                # API gateway implementation
├── README.md              # This file
├── requirements.txt       # Python dependencies
└── static/
    └── index.html         # Minimal browser-side SSE consumer
```

## Docker

```bash
docker build -t gateway-agent:latest .
docker run -p 9172:9172 gateway-agent:latest
```

## Kubernetes

```bash
helm install gateway-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/gateway-agent \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
