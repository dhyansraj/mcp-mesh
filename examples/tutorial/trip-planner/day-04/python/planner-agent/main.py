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
    user_preferences: str = Field(
        default="", description="User travel preferences (injected at runtime)"
    )
# --8<-- [end:context_model]


# --8<-- [start:llm_function]
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/plan_trip.j2",
    context_param="ctx",
    # --8<-- [start:provider_selection]
    provider={"capability": "llm", "tags": ["+claude"]},
    # --8<-- [end:provider_selection]
    # --8<-- [start:tier2_tools]
    filter=[
        {"capability": "flight_search"},
        {"capability": "hotel_search"},
        {"capability": "weather_forecast"},
        {"capability": "poi_search"},
    ],
    filter_mode="all",
    max_iterations=10,
    # --8<-- [end:tier2_tools]
)
@mesh.tool(
    capability="trip_planning",
    description="Generate a trip itinerary using an LLM with real travel data",
    tags=["planner", "travel", "llm"],
    # --8<-- [start:tier1_prefetch]
    dependencies=["user_preferences"],
    # --8<-- [end:tier1_prefetch]
)
async def plan_trip(
    destination: str,
    dates: str,
    budget: str,
    user_prefs: mesh.McpMeshTool = None,
    ctx: TripRequest = None,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Plan a trip given a destination, dates, and budget."""
    # Tier-1: prefetch user preferences before the LLM call
    prefs = {}
    if user_prefs:
        prefs = await user_prefs(user_id="demo-user")

    # Inject preferences into the context so the Jinja template can use them
    prefs_summary = (
        f"Preferred airlines: {', '.join(prefs.get('preferred_airlines', []))}. "
        f"Budget limit: ${prefs.get('budget_usd', 'flexible')}. "
        f"Interests: {', '.join(prefs.get('interests', []))}. "
        f"Minimum hotel stars: {prefs.get('hotel_min_stars', 'any')}."
        if prefs
        else "No user preferences available."
    )

    # Tier-2: the LLM will discover and call flight_search, hotel_search,
    # get_weather, and search_pois during its reasoning loop
    result = await llm(
        f"Plan a trip to {destination} from {dates} with a budget of {budget}.",
        context={"user_preferences": prefs_summary},
    )
    return result
# --8<-- [end:llm_function]


@mesh.agent(
    name="planner-agent",
    version="1.0.0",
    description="TripPlanner LLM planner with tool access (Day 4)",
    http_port=9107,
    enable_http=True,
    auto_run=True,
)
class PlannerAgent:
    pass
# --8<-- [end:full_file]
