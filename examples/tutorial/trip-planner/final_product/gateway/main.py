# --8<-- [start:full_file]
# --8<-- [start:imports]
import json
import os
import uuid

import mesh
import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from mesh.types import McpMeshTool

app = FastAPI(title="Trip Planner Gateway", version="2.0.0")
# --8<-- [end:imports]

# --8<-- [start:cors]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --8<-- [end:cors]

# --8<-- [start:redis_client]
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
)
# --8<-- [end:redis_client]


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# --8<-- [start:plan_endpoint]
@app.post("/plan")
@mesh.route(dependencies=["trip_planning"])
async def plan_trip(request: Request, plan_trip: McpMeshTool = None):
    """Bridge HTTP to the mesh planner with session tracking."""
    body = await request.json()
    if not plan_trip:
        return {"error": "trip_planning capability unavailable"}

    # --8<-- [start:session_id]
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    user_email = request.headers.get("X-User-Email", "anonymous")
    # --8<-- [end:session_id]

    # --8<-- [start:scoped_session]
    scoped_session = f"{user_email}:{session_id}"
    # --8<-- [end:scoped_session]

    result = await plan_trip(
        destination=body["destination"],
        dates=body["dates"],
        budget=body["budget"],
        from_city=body.get("from", ""),
        message=body.get("message", ""),
        session_id=scoped_session,
    )

    # --8<-- [start:track_session]
    try:
        session_meta = json.dumps({
            "session_id": session_id,
            "destination": body["destination"],
            "dates": body["dates"],
            "budget": body["budget"],
            "user_email": user_email,
        })
        redis_client.hset(f"trip_sessions:{user_email}", session_id, session_meta)
    except Exception:
        pass
    # --8<-- [end:track_session]

    return {"result": result, "session_id": session_id}
# --8<-- [end:plan_endpoint]


# --8<-- [start:sessions_endpoint]
@app.get("/sessions")
async def list_sessions(request: Request):
    """List trip sessions for the authenticated user."""
    user_email = request.headers.get("X-User-Email", "anonymous")
    try:
        raw = redis_client.hgetall(f"trip_sessions:{user_email}")
        sessions = []
        for sid, meta_str in raw.items():
            meta = json.loads(meta_str)
            scoped = f"{user_email}:{sid}"
            turn_count = redis_client.llen(f"chat:{scoped}")
            sessions.append({
                "session_id": sid,
                "destination": meta.get("destination", "Unknown"),
                "created_at": meta.get("created_at", ""),
                "turn_count": turn_count,
            })
        return sessions
    except Exception:
        return []
# --8<-- [end:sessions_endpoint]


# --8<-- [start:session_history_endpoint]
@app.get("/sessions/{session_id}/history")
async def session_history(session_id: str, request: Request):
    """Get chat history for a specific session."""
    user_email = request.headers.get("X-User-Email", "anonymous")
    scoped = f"{user_email}:{session_id}"
    try:
        raw = redis_client.lrange(f"chat:{scoped}", 0, -1)
        return [json.loads(entry) for entry in raw]
    except Exception:
        return []
# --8<-- [end:session_history_endpoint]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
# --8<-- [end:full_file]
