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
    provider={"capability": "llm", "tags": ["+claude"]},
    filter=[
        {"capability": "flight_search"},
        {"capability": "hotel_search"},
        {"capability": "weather_forecast"},
        {"capability": "poi_search"},
    ],
    filter_mode="all",
    max_iterations=10,
)
@mesh.tool(
    capability="trip_planning",
    description="Generate a trip itinerary using an LLM with real travel data",
    tags=["planner", "travel", "llm"],
    dependencies=["user_preferences", "chat_history"],
)
async def plan_trip(
    destination: str,
    dates: str,
    budget: str,
    message: str = "",
    session_id: str = "",
    conversation_history: list[dict] = [],
    user_prefs: mesh.McpMeshTool = None,
    chat_history: mesh.McpMeshTool = None,
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

    # Tier-1: fetch chat history if a session is active
    history = []
    if session_id and chat_history:
        history = await chat_history.call_tool("get_history", {
            "session_id": session_id,
            "limit": 20,
        })
        if isinstance(history, dict):
            history = history.get("result", [])

    # --8<-- [start:multi_turn]
    # Build the message for the LLM. When history is present,
    # pass the full turn list so the LLM sees prior context.
    user_text = message or (
        f"Plan a trip to {destination} from {dates} with a budget of {budget}."
    )

    if history:
        messages = list(history)
        messages.append({"role": "user", "content": user_text})
        result = await llm(
            messages,
            context={"user_preferences": prefs_summary},
        )
    else:
        result = await llm(
            user_text,
            context={"user_preferences": prefs_summary},
        )
    # --8<-- [end:multi_turn]

    # Save turns to chat history so the next request sees them
    if session_id and chat_history:
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "user",
            "content": user_text,
        })
        response_text = result if isinstance(result, str) else str(result)
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "assistant",
            "content": response_text,
        })

    return result
# --8<-- [end:llm_function]


@mesh.agent(
    name="planner-agent",
    version="1.0.0",
    description="TripPlanner LLM planner with tool access (Day 6)",
    http_port=9107,
    enable_http=True,
    auto_run=True,
)
class PlannerAgent:
    pass
# --8<-- [end:full_file]
