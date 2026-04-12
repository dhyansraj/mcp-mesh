# --8<-- [start:full_file]
# --8<-- [start:imports]
import uuid

import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(title="Trip Planner Gateway", version="2.0.0")
# --8<-- [end:imports]


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# --8<-- [start:plan_endpoint]
@app.post("/plan")
@mesh.route(dependencies=["chat_history", "trip_planning"])
async def plan_trip(
    request: Request,
    chat_history: McpMeshTool = None,
    plan_trip: McpMeshTool = None,
):
    """Bridge HTTP to the mesh planner with multi-turn chat history."""
    body = await request.json()
    if not plan_trip:
        return {"error": "trip_planning capability unavailable"}

    # --8<-- [start:session_id]
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    # --8<-- [end:session_id]

    # --8<-- [start:fetch_history]
    history = []
    if chat_history:
        history = await chat_history.call_tool("get_history", {
            "session_id": session_id,
            "limit": 20,
        })
        if isinstance(history, dict):
            history = history.get("result", [])
    # --8<-- [end:fetch_history]

    # --8<-- [start:call_planner]
    user_message = body.get("message", f"Plan a trip to {body['destination']}")
    result = await plan_trip(
        destination=body["destination"],
        dates=body["dates"],
        budget=body["budget"],
        message=user_message,
        conversation_history=history,
    )
    # --8<-- [end:call_planner]

    # --8<-- [start:save_turns]
    if chat_history:
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "user",
            "content": user_message,
        })
        response_text = result if isinstance(result, str) else str(result)
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "assistant",
            "content": response_text,
        })
    # --8<-- [end:save_turns]

    return {"result": result, "session_id": session_id}
# --8<-- [end:plan_endpoint]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
# --8<-- [end:full_file]
