# --8<-- [start:full_file]
# --8<-- [start:imports]
import asyncio

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
# --8<-- [start:committee_deps]
@mesh.tool(
    capability="trip_planning",
    description="Generate a trip itinerary using an LLM with real travel data",
    tags=["planner", "travel", "llm"],
    dependencies=[
        "user_preferences",
        "chat_history",
        "budget_analysis",
        "adventure_advice",
        "logistics_planning",
    ],
)
# --8<-- [end:committee_deps]
async def plan_trip(
    destination: str,
    dates: str,
    budget: str,
    message: str = "",
    session_id: str = "",
    conversation_history: list[dict] = [],
    user_prefs: mesh.McpMeshTool = None,
    chat_history: mesh.McpMeshTool = None,
    budget_analyst: mesh.McpMeshTool = None,
    adventure_advisor: mesh.McpMeshTool = None,
    logistics_planner: mesh.McpMeshTool = None,
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

    # --8<-- [start:chat_history_fetch]
    # Tier-1: fetch chat history if a session is active
    history = []
    if session_id and chat_history:
        history = await chat_history.call_tool("get_history", {
            "session_id": session_id,
            "limit": 20,
        })
        if isinstance(history, dict):
            history = history.get("result", [])
    # --8<-- [end:chat_history_fetch]

    # --8<-- [start:multi_turn]
    # Build the message for the LLM. When history is present,
    # pass the full turn list so the LLM sees prior context.
    user_text = message or (
        f"Plan a trip to {destination} from {dates} with a budget of {budget}."
    )

    if history:
        messages = list(history)
        messages.append({"role": "user", "content": user_text})
        base_plan = await llm(
            messages,
            context={"user_preferences": prefs_summary},
        )
    else:
        base_plan = await llm(
            user_text,
            context={"user_preferences": prefs_summary},
        )
    # --8<-- [end:multi_turn]

    # --8<-- [start:committee_fanout]
    # Fan out to specialist agents in parallel
    specialist_tasks = []
    if budget_analyst:
        specialist_tasks.append(
            budget_analyst(
                destination=destination, plan_summary=str(base_plan), budget=budget
            )
        )
    if adventure_advisor:
        specialist_tasks.append(
            adventure_advisor(destination=destination, plan_summary=str(base_plan))
        )
    if logistics_planner:
        specialist_tasks.append(
            logistics_planner(
                destination=destination, plan_summary=str(base_plan), dates=dates
            )
        )

    if specialist_tasks:
        specialist_results = await asyncio.gather(*specialist_tasks)

        # Synthesize specialist insights into the final plan
        sections = [str(base_plan), "\n---\n## Specialist Insights\n"]
        labels = []
        if budget_analyst:
            labels.append("Budget Analysis")
        if adventure_advisor:
            labels.append("Adventure Recommendations")
        if logistics_planner:
            labels.append("Logistics Plan")

        for label, result in zip(labels, specialist_results):
            sections.append(f"\n### {label}\n{result}\n")

        final_result = "\n".join(sections)
    else:
        final_result = str(base_plan)
    # --8<-- [end:committee_fanout]

    # --8<-- [start:chat_history_save]
    # Save turns to chat history so the next request sees them
    if session_id and chat_history:
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "user",
            "content": user_text,
        })
        response_text = final_result if isinstance(final_result, str) else str(final_result)
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "assistant",
            "content": response_text,
        })
    # --8<-- [end:chat_history_save]

    return final_result
# --8<-- [end:llm_function]


@mesh.agent(
    name="planner-agent",
    version="1.0.0",
    description="TripPlanner LLM planner with committee of specialists (Day 7)",
    http_port=9107,
    enable_http=True,
    auto_run=True,
)
class PlannerAgent:
    pass
# --8<-- [end:full_file]
