# gateway

A MCP Mesh API gateway generated for the Day 6 tutorial.

## Overview

FastAPI gateway that exposes the trip planner as a REST API via `@mesh.route` dependency injection. Day 6 adds multi-turn chat history through the `chat_history` capability.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- FastAPI
- Uvicorn

### Installation

```bash
pip install -r requirements.txt
```

### Running the Gateway

```bash
meshctl start main.py
```

Or with debug logging:

```bash
meshctl start main.py --debug
```

The gateway will start on port 8080 by default.

## Endpoints

| Method | Path      | Description                        |
|--------|-----------|------------------------------------|
| POST   | `/plan`   | Generate a trip itinerary via mesh  |
| GET    | `/health` | Health check                       |

## Headers

| Header         | Description                       | Default        |
|----------------|-----------------------------------|----------------|
| X-Session-Id   | Chat session identifier           | Auto-generated |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man fastapi` for FastAPI integration reference

## License

MIT
