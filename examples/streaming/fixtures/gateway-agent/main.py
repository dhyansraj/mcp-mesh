#!/usr/bin/env python3
"""
gateway-agent - MCP Mesh streaming SSE HTTP gateway (issue #645)

Exposes two streaming endpoints that bridge browser/curl clients to the
mesh ``chat`` and ``chat_passthrough`` capabilities. Both endpoints declare
``-> mesh.Stream[str]`` so the P3 SSE adapter wraps them as
``text/event-stream`` responses with ``data: <chunk>\\n\\n`` framing and a
``data: [DONE]\\n\\n`` terminator.

A non-streaming ``/api/health`` endpoint exists alongside the SSE routes to
verify that the route.app/route.dependant rebuild does not regress
plain-JSON responses.
"""

from pathlib import Path

import mesh
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mesh.types import McpMeshTool
from pydantic import BaseModel

app = FastAPI(
    title="Streaming Gateway",
    description="HTTP/SSE gateway for the streaming chatbot demo (issue #645)",
    version="1.0.0",
)

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    prompt: str


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Plain-JSON health check (intentionally NOT streaming)."""
    return {"status": "ok"}


@app.get("/")
async def index():
    """Serve the demo HTML page if present, else fall back to a route listing."""
    index_path = _STATIC_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path))
    return {
        "service": "gateway-agent",
        "endpoints": [
            "GET  /api/health         - plain JSON",
            "POST /api/chat           - SSE stream (single hop)",
            "POST /api/chat-multihop  - SSE stream (via passthrough)",
        ],
    }


@app.post("/api/chat")
@mesh.route(dependencies=["chat"])
async def chat_endpoint(
    body: ChatRequest,
    chat: McpMeshTool = None,
) -> mesh.Stream[str]:
    """Single-hop streaming chat: gateway -> chatbot.

    Pre-stream errors are raised here (before returning the generator) so they
    propagate as proper HTTP status codes; errors raised inside the generator
    surface as ``event: error`` SSE frames after the 200 OK is committed.
    """
    if chat is None:
        raise HTTPException(status_code=503, detail="chat capability unavailable")
    return _stream_chat(body, chat)


async def _stream_chat(body: ChatRequest, chat: McpMeshTool):
    async for chunk in chat.stream(prompt=body.prompt):
        yield chunk


@app.post("/api/chat-multihop")
@mesh.route(dependencies=["chat_passthrough"])
async def chat_multihop_endpoint(
    body: ChatRequest,
    chat_passthrough: McpMeshTool = None,
) -> mesh.Stream[str]:
    """Multi-hop streaming chat: gateway -> passthrough -> chatbot.

    Pre-stream errors are raised here (before returning the generator) so they
    propagate as proper HTTP status codes; errors raised inside the generator
    surface as ``event: error`` SSE frames after the 200 OK is committed.
    """
    if chat_passthrough is None:
        raise HTTPException(
            status_code=503, detail="chat_passthrough capability unavailable"
        )
    return _stream_chat_multihop(body, chat_passthrough)


async def _stream_chat_multihop(body: ChatRequest, chat_passthrough: McpMeshTool):
    async for chunk in chat_passthrough.stream(prompt=body.prompt):
        yield chunk


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9172, log_level="info")
