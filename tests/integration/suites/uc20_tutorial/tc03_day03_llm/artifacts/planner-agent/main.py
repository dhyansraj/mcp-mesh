# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import Field

app = FastMCP("Planner Agent")
# --8<-- [end:imports]


# --8<-- [start:context_model]
class TripRequest(MeshContextModel):
    """Context model for the trip planning prompt template."""

    destination: str = Field(..., description="Travel destination city")
    dates: str = Field(..., description="Travel dates (e.g. June 1-5, 2026)")
    budget: str = Field(..., description="Total trip budget (e.g. $2000)")
# --8<-- [end:context_model]


# --8<-- [start:llm_function]
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/plan_trip.j2",
    context_param="ctx",
    provider={"capability": "llm"},
)
@mesh.tool(
    capability="trip_planning",
    description="Generate a trip itinerary using an LLM",
    tags=["planner", "travel", "llm"],
)
async def plan_trip(
    destination: str,
    dates: str,
    budget: str,
    ctx: TripRequest = None,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Plan a trip given a destination, dates, and budget."""
    result = await llm(
        f"Plan a trip to {destination} from {dates} with a budget of {budget}."
    )
    return result
# --8<-- [end:llm_function]


@mesh.agent(
    name="planner-agent",
    version="1.0.0",
    description="TripPlanner LLM planner (Day 3)",
    http_port=9107,
    enable_http=True,
    auto_run=True,
)
class PlannerAgent:
    pass
# --8<-- [end:full_file]
