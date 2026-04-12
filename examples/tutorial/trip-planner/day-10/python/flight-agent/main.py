# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("Flight Agent")
# --8<-- [end:imports]


# --8<-- [start:tool_function]
# --8<-- [start:di_function]
@app.tool()
@mesh.tool(
    capability="flight_search",
    description="Search for flights between two cities on a given date",
    tags=["flights", "travel"],
    dependencies=["user_preferences"],
)
async def flight_search(
    origin: str,
    destination: str,
    date: str,
    user_prefs: mesh.McpMeshTool = None,
) -> list[dict]:
    """Search flights, personalized with user preferences when available."""
    # Fetch user preferences via dependency injection
    prefs = await user_prefs(user_id="demo-user") if user_prefs else {}

    preferred_airlines = prefs.get("preferred_airlines", [])
    budget = prefs.get("budget_usd", 10000)

    flights = [
        {
            "carrier": "MH",
            "flight": "MH007",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "09:15",
            "arrive": "14:40",
            "price_usd": 842,
        },
        {
            "carrier": "SQ",
            "flight": "SQ017",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "11:50",
            "arrive": "17:05",
            "price_usd": 901,
        },
        {
            "carrier": "AA",
            "flight": "AA100",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "14:30",
            "arrive": "20:15",
            "price_usd": 1150,
        },
    ]

    # Filter by budget
    flights = [f for f in flights if f["price_usd"] <= budget]

    # Sort preferred airlines first
    if preferred_airlines:
        flights.sort(key=lambda f: f["carrier"] not in preferred_airlines)

    return flights
# --8<-- [end:di_function]
# --8<-- [end:tool_function]


@mesh.agent(
    name="flight-agent",
    version="1.0.0",
    description="TripPlanner flight search tool -- Day 9",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class FlightAgent:
    pass
# --8<-- [end:full_file]
