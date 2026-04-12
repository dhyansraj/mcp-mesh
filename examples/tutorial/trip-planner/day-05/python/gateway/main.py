# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(title="Trip Planner Gateway", version="1.0.0")
# --8<-- [end:imports]


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# --8<-- [start:plan_endpoint]
@app.post("/plan")
@mesh.route(dependencies=["trip_planning"])
async def plan_trip(request: Request, plan_trip: McpMeshTool = None):
    """Bridge HTTP to the mesh planner."""
    body = await request.json()
    if not plan_trip:
        return {"error": "trip_planning capability unavailable"}
    result = await plan_trip(
        destination=body["destination"],
        dates=body["dates"],
        budget=body["budget"],
    )
    return {"result": result}
# --8<-- [end:plan_endpoint]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
# --8<-- [end:full_file]
