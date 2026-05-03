# --8<-- [start:full_file]
# --8<-- [start:imports]
import asyncio
import os

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
    committee_insights: str = Field(
        default="",
        description="Pre-computed committee specialist insights injected at runtime",
    )
# --8<-- [end:context_model]


_DRY_RUN_CHUNKS = [
    "Planning ",
    "your trip to ",
    "{destination}",
    "...\n\n",
    "Day 1: ",
    "Arrival and check-in. ",
    "Day 2: ",
    "Local exploration.\n\n",
    "Total budget: {budget}.",
]


def _dry_run_enabled() -> bool:
    return os.environ.get("MESH_LLM_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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
    description="Stream a trip itinerary live from an LLM with real travel data",
    tags=["planner", "travel", "llm", "streaming"],
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
    user_prefs: mesh.McpMeshTool = None,
    chat_history: mesh.McpMeshTool = None,
    budget_analyst: mesh.McpMeshTool = None,
    adventure_advisor: mesh.McpMeshTool = None,
    logistics_planner: mesh.McpMeshTool = None,
    ctx: TripRequest = None,
    llm: mesh.MeshLlmAgent = None,
) -> mesh.Stream[str]:
    """Stream a trip itinerary one chunk at a time as the LLM generates it."""
    prefs = {}
    if user_prefs:
        prefs = await user_prefs(user_id="demo-user")

    prefs_summary = (
        f"Preferred airlines: {', '.join(prefs.get('preferred_airlines', []))}. "
        f"Budget limit: ${prefs.get('budget_usd', 'flexible')}. "
        f"Interests: {', '.join(prefs.get('interests', []))}. "
        f"Minimum hotel stars: {prefs.get('hotel_min_stars', 'any')}."
        if prefs
        else "No user preferences available."
    )

    # --8<-- [start:chat_history_fetch]
    history = []
    if session_id and chat_history:
        history = await chat_history.call_tool("get_history", {
            "session_id": session_id,
            "limit": 20,
        })
        if isinstance(history, dict):
            history = history.get("result", [])
    # --8<-- [end:chat_history_fetch]

    base_request = (
        f"Plan a trip to {destination} from {dates} with a budget of {budget}."
    )
    user_text = (
        f"{base_request} Additional preferences from user: {message}"
        if message
        else base_request
    )

    # --8<-- [start:dry_run]
    # Dry-run gate fires BEFORE the committee fan-out so unit/integration
    # tests don't burn LLM tokens on specialist calls. When MESH_LLM_DRY_RUN
    # is set on the planner, neither the committee nor Claude is invoked.
    if _dry_run_enabled():
        accumulated_chunks = []
        for chunk in _DRY_RUN_CHUNKS:
            rendered = chunk.replace("{destination}", destination).replace(
                "{budget}", budget
            )
            accumulated_chunks.append(rendered)
            yield rendered

        if session_id and chat_history:
            await chat_history.call_tool("save_turn", {
                "session_id": session_id,
                "role": "user",
                "content": user_text,
            })
            await chat_history.call_tool("save_turn", {
                "session_id": session_id,
                "role": "assistant",
                "content": "".join(accumulated_chunks),
            })
        return
    # --8<-- [end:dry_run]

    # --8<-- [start:committee_prefetch]
    # Run the committee in parallel BEFORE the streaming LLM call so their
    # insights can be injected into the LLM context. The committee remains
    # buffered (each specialist runs its own non-streaming LLM internally);
    # only the planner's final user-visible call streams.
    request_summary = (
        f"Trip request: destination={destination}, dates={dates}, budget={budget}. "
        f"User message: {user_text}"
    )

    specialist_tasks = []
    specialist_labels = []
    if budget_analyst:
        specialist_tasks.append(
            budget_analyst(
                destination=destination,
                plan_summary=request_summary,
                budget=budget,
            )
        )
        specialist_labels.append("Budget Analysis")
    if adventure_advisor:
        specialist_tasks.append(
            adventure_advisor(destination=destination, plan_summary=request_summary)
        )
        specialist_labels.append("Adventure Recommendations")
    if logistics_planner:
        specialist_tasks.append(
            logistics_planner(
                destination=destination,
                plan_summary=request_summary,
                dates=dates,
            )
        )
        specialist_labels.append("Logistics Plan")

    committee_insights = ""
    if specialist_tasks:
        specialist_results = await asyncio.gather(*specialist_tasks)
        sections = []
        for label, result in zip(specialist_labels, specialist_results):
            sections.append(f"### {label}\n{result}")
        committee_insights = "\n\n".join(sections)
    # --8<-- [end:committee_prefetch]

    if llm is None:
        raise RuntimeError(
            "plan_trip: LLM dependency not injected and MESH_LLM_DRY_RUN is not set"
        )

    # --8<-- [start:streaming_llm]
    if history:
        messages = list(history)
        messages.append({"role": "user", "content": user_text})
        prompt = messages
    else:
        prompt = user_text

    accumulated = []
    async for chunk in llm.stream(
        prompt,
        context={
            "user_preferences": prefs_summary,
            "committee_insights": committee_insights,
        },
    ):
        accumulated.append(chunk)
        yield chunk
    # --8<-- [end:streaming_llm]

    # --8<-- [start:chat_history_save]
    if session_id and chat_history:
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "user",
            "content": user_text,
        })
        await chat_history.call_tool("save_turn", {
            "session_id": session_id,
            "role": "assistant",
            "content": "".join(accumulated),
        })
    # --8<-- [end:chat_history_save]
# --8<-- [end:llm_function]


@mesh.agent(
    name="planner-agent",
    version="1.0.0",
    description="TripPlanner streaming planner with committee of specialists -- Day 10 bonus",
    http_port=9107,
    enable_http=True,
    auto_run=True,
)
class PlannerAgent:
    pass
# --8<-- [end:full_file]
