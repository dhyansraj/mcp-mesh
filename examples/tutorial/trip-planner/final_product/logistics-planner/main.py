# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("Logistics Planner")
# --8<-- [end:imports]


# --8<-- [start:output_model]
class DaySchedule(BaseModel):
    day: int = Field(..., description="Day number (1, 2, 3, etc.)")
    activities: list[str] = Field(..., description="Activities for this day with times")


class LogisticsPlan(BaseModel):
    """Structured logistics plan returned by the specialist."""

    daily_schedule: list[DaySchedule] = Field(
        ..., description="Day-by-day schedule"
    )
    transit_tips: list[str] = Field(
        ..., description="Local transport tips and passes to buy"
    )
    time_optimization: str = Field(
        ..., description="Advice on minimizing travel time between locations"
    )
# --8<-- [end:output_model]


# --8<-- [start:llm_function]
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/logistics_plan.j2",
    context_param="ctx",
    provider={"capability": "llm"},
    max_iterations=1,
)
@mesh.tool(
    capability="logistics_planning",
    description="Plan daily logistics, transit routes, and time optimization",
    tags=["specialist", "logistics", "llm"],
)
def logistics_planning(
    destination: str,
    plan_summary: str,
    dates: str,
    ctx: dict = None,
    llm: mesh.MeshLlmAgent = None,
) -> LogisticsPlan:
    """Produce a logistics plan with daily schedules and transit advice."""
    return llm(
        f"Create a logistics plan for {destination} from {dates}. "
        f"Plan summary:\n{plan_summary}"
    )
# --8<-- [end:llm_function]


@mesh.agent(
    name="logistics-planner",
    version="1.0.0",
    description="TripPlanner logistics planning specialist (Day 7)",
    http_port=9112,
    enable_http=True,
    auto_run=True,
)
class LogisticsPlannerAgent:
    pass
# --8<-- [end:full_file]
