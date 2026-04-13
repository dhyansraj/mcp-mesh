# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("Budget Analyst")
# --8<-- [end:imports]


# --8<-- [start:output_model]
class BudgetAnalysis(BaseModel):
    """Structured budget analysis returned by the specialist."""

    total_estimated: int = Field(..., description="Total estimated cost in USD")
    savings_tips: list[str] = Field(
        default_factory=list, description="Actionable tips to save money"
    )
    budget_breakdown: list[dict] = Field(
        default_factory=list,
        description="Cost breakdown by category (flights, hotels, food, activities)",
    )
# --8<-- [end:output_model]


# --8<-- [start:llm_function]
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/budget_analysis.j2",
    context_param="ctx",
    provider={"capability": "llm"},
    max_iterations=1,
)
@mesh.tool(
    capability="budget_analysis",
    description="Analyze trip costs and provide budget optimization advice",
    tags=["specialist", "budget", "llm"],
)
def budget_analysis(
    destination: str,
    plan_summary: str,
    budget: str,
    ctx: dict = None,
    llm: mesh.MeshLlmAgent = None,
) -> BudgetAnalysis:
    """Analyze a trip plan and produce a structured budget breakdown."""
    return llm(
        f"Analyze the budget for a trip to {destination} with budget {budget}. "
        f"Plan summary:\n{plan_summary}"
    )
# --8<-- [end:llm_function]


@mesh.agent(
    name="budget-analyst",
    version="1.0.0",
    description="TripPlanner budget analysis specialist (Day 7)",
    http_port=9110,
    enable_http=True,
    auto_run=True,
)
class BudgetAnalystAgent:
    pass
# --8<-- [end:full_file]
