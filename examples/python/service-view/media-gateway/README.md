# media-gateway

The consumer in the [`@mesh.service` service-view example](../README.md).
Declares one typed `MediaService` view aggregating three `media.*` capabilities
and exposes a `process_media` tool that fans a request out across all three view
methods — each served by a different provider agent.

## Overview

A Python MCP Mesh agent. `MediaService` is a consumer service view; it is
injected as a `@mesh.tool` parameter (hidden from the MCP input schema):

```python
@mesh.service
class MediaService:
    @mesh.selector("media.caption", required=True)
    async def caption(self, args: dict) -> dict: ...
    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...
    @mesh.selector("media.transcribe")
    async def transcribe(self, args: dict) -> dict: ...

@mesh.tool(capability="process_media", tags=["media", "gateway"])
async def process_media(assetId: str, text: str, media: MediaService = None) -> dict:
    ...
```

`caption` is `required` (missing provider → structured `dependency_unavailable`
refusal before the handler runs); `thumbnail`/`transcribe` are optional and
raise `ToolError` when unresolved, which the handler catches for graceful
degradation.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- FastMCP
- The three providers running (`caption-provider`, `thumbnail-provider`,
  `transcribe-provider`)

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

```bash
meshctl start main.py
```

The agent will start on port 8123 by default. Then:

```bash
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

## Project Structure

```text
media-gateway/
├── main.py            # MediaService view + process_media tool
├── requirements.txt
├── Dockerfile
├── helm-values.yaml
├── __init__.py
└── __main__.py
```

## Docker

```bash
docker build -t media-gateway:latest .
docker run -p 8123:8123 media-gateway:latest
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
