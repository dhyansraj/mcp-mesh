"""TripPlanner flight-agent — Day 1 (integration test copy)."""

import mesh
from fastmcp import FastMCP

app = FastMCP("Flight Agent")


@app.tool()
@mesh.tool(
    capability="flight_search",
    description="Search for flights between two cities on a given date",
    tags=["flights", "travel"],
)
def flight_search(origin: str, destination: str, date: str) -> list[dict]:
    """Return a list of matching flights. Stub data for Day 1."""
    return [
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
    ]


@mesh.agent(
    name="flight-agent",
    version="1.0.0",
    description="TripPlanner flight search tool (Day 1)",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class FlightAgent:
    pass
