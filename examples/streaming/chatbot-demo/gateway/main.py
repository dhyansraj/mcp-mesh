#!/usr/bin/env python3
"""gateway - HTTP/SSE edge for the streaming weather chatbot spike."""

from pathlib import Path

import mesh
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from mesh.types import McpMeshTool
from pydantic import BaseModel

app = FastAPI(
    title="Weather Chatbot Gateway",
    description="HTTP/SSE gateway for the streaming weather chatbot spike",
    version="1.0.0",
)

_STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    prompt: str


@app.get("/")
async def index():
    """Serve the single-page React chat UI."""
    index_path = _STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail="index.html missing")
    return FileResponse(str(index_path))


@app.post("/api/chat")
@mesh.route(dependencies=["chat"])
async def chat_endpoint(
    body: ChatRequest,
    chat: McpMeshTool = None,
) -> mesh.Stream[str]:
    """Stream chat response via SSE: gateway -> chatbot -> Claude (+ weather tool)."""
    if chat is None:
        raise HTTPException(status_code=503, detail="chat capability unavailable")
    async for chunk in chat.stream(prompt=body.prompt):
        yield chunk


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9182, log_level="info")
