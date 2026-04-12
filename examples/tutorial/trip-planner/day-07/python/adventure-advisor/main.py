# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("Adventure Advisor")
# --8<-- [end:imports]


# --8<-- [start:output_model]
class AdventureAdvice(BaseModel):
    """Structured adventure recommendations returned by the specialist."""

    unique_experiences: list[dict] = Field(
        default_factory=list,
        description="Unique experiences with name, description, and why_special fields",
    )
    local_gems: list[str] = Field(
        default_factory=list, description="Hidden local spots most tourists miss"
    )
    off_beaten_path: str = Field(
        ..., description="A paragraph about unconventional things to do"
    )
# --8<-- [end:output_model]


# --8<-- [start:llm_function]
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/adventure_advice.j2",
    context_param="ctx",
    provider={"capability": "llm"},
    max_iterations=1,
)
@mesh.tool(
    capability="adventure_advice",
    description="Suggest unique experiences and hidden gems for a destination",
    tags=["specialist", "adventure", "llm"],
)
def adventure_advice(
    destination: str,
    plan_summary: str,
    ctx: dict = None,
    llm: mesh.MeshLlmAgent = None,
) -> AdventureAdvice:
    """Recommend unique experiences and hidden gems for a trip."""
    return llm(
        f"Suggest unique adventures and hidden gems in {destination}. "
        f"Plan summary:\n{plan_summary}"
    )
# --8<-- [end:llm_function]


@mesh.agent(
    name="adventure-advisor",
    version="1.0.0",
    description="TripPlanner adventure advice specialist (Day 7)",
    http_port=9111,
    enable_http=True,
    auto_run=True,
)
class AdventureAdvisorAgent:
    pass
# --8<-- [end:full_file]
