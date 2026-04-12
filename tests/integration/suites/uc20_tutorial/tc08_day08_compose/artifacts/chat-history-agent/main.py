# --8<-- [start:full_file]
# --8<-- [start:imports]
import json
import os

import mesh
import redis
from fastmcp import FastMCP

app = FastMCP("Chat History Agent")
# --8<-- [end:imports]

# --8<-- [start:redis_client]
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
)
# --8<-- [end:redis_client]


# --8<-- [start:save_turn]
@app.tool()
@mesh.tool(
    capability="chat_history",
    description="Save a conversation turn to Redis",
    tags=["chat", "history", "state"],
)
async def save_turn(session_id: str, role: str, content: str) -> dict:
    """Save a single conversation turn (user or assistant message)."""
    turn = json.dumps({"role": role, "content": content})
    redis_client.rpush(f"chat:{session_id}", turn)
    length = redis_client.llen(f"chat:{session_id}")
    return {"session_id": session_id, "role": role, "saved": True, "total_turns": length}
# --8<-- [end:save_turn]


# --8<-- [start:get_history]
@app.tool()
@mesh.tool(
    capability="chat_history",
    description="Retrieve recent conversation turns from Redis",
    tags=["chat", "history", "state"],
)
async def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Retrieve the most recent turns for a session."""
    raw = redis_client.lrange(f"chat:{session_id}", -limit, -1)
    return [json.loads(entry) for entry in raw]
# --8<-- [end:get_history]


@mesh.agent(
    name="chat-history-agent",
    version="1.0.0",
    description="TripPlanner Redis-backed chat history -- Day 8",
    http_port=9109,
    enable_http=True,
    auto_run=True,
)
class ChatHistoryAgent:
    pass
# --8<-- [end:full_file]
