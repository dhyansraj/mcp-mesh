# --8<-- [start:full_file]
# --8<-- [start:imports]
import uuid
from pathlib import Path

import mesh
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mesh.types import McpMeshTool

app = FastAPI(title="Trip Planner Streaming Gateway", version="2.1.0")

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
# --8<-- [end:imports]


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# --8<-- [start:ui_route]
@app.get("/")
async def index():
    """Serve the single-page React trip-planner UI."""
    index_path = _STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail="index.html missing")
    return FileResponse(str(index_path))
# --8<-- [end:ui_route]


# --8<-- [start:plan_endpoint]
@app.post("/plan")
@mesh.route(dependencies=["trip_planning"])
async def plan_trip(
    request: Request,
    plan_trip: McpMeshTool = None,
) -> mesh.Stream[str]:
    """Stream the trip plan via SSE: gateway -> planner -> committee + tools + Claude.

    Pre-stream errors (missing dependency, bad request body) are raised here
    BEFORE returning the generator so they propagate as proper HTTP status
    codes. Errors raised inside the generator body fire after StreamingResponse
    has committed to HTTP 200 and surface as ``event: error`` SSE frames.
    """
    if plan_trip is None:
        raise HTTPException(
            status_code=503, detail="trip_planning capability unavailable"
        )

    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="request body must be a JSON object"
        )
    if "destination" not in body or "dates" not in body or "budget" not in body:
        raise HTTPException(
            status_code=400,
            detail="missing required fields: destination, dates, budget",
        )

    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    return _stream_plan(plan_trip, body, session_id)


async def _stream_plan(plan_trip: McpMeshTool, body: dict, session_id: str):
    async for chunk in plan_trip.stream(
        destination=body["destination"],
        dates=body["dates"],
        budget=body["budget"],
        message=body.get("message", ""),
        session_id=session_id,
    ):
        yield chunk
# --8<-- [end:plan_endpoint]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
# --8<-- [end:full_file]
