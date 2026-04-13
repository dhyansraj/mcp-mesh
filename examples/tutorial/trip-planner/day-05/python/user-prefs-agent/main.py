# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("User Preferences Agent")
# --8<-- [end:imports]


# --8<-- [start:tool_function]
@app.tool()
@mesh.tool(
    capability="user_preferences",
    description="Get user travel preferences",
    tags=["preferences", "travel"],
)
async def get_user_prefs(user_id: str) -> dict:
    """Return user preferences. Stub data for Day 2."""
    return {
        "user_id": user_id,
        "preferred_airlines": ["SQ", "MH"],
        "budget_usd": 1000,
        "interests": ["cultural", "food", "nature"],
        "hotel_min_stars": 3,
    }
# --8<-- [end:tool_function]


@mesh.agent(
    name="user-prefs-agent",
    version="1.0.0",
    description="TripPlanner user preferences tool (Day 5)",
    http_port=9105,
    enable_http=True,
    auto_run=True,
)
class UserPrefsAgent:
    pass
# --8<-- [end:full_file]
