# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("Hotel Agent")
# --8<-- [end:imports]


# --8<-- [start:tool_function]
@app.tool()
@mesh.tool(
    capability="hotel_search",
    description="Search for hotels at a destination",
    tags=["hotels", "travel"],
)
async def hotel_search(
    destination: str,
    checkin: str,
    checkout: str,
) -> list[dict]:
    """Return a list of matching hotels. Stub data for Day 2."""
    return [
        {
            "name": "Grand Hyatt",
            "destination": destination,
            "checkin": checkin,
            "checkout": checkout,
            "stars": 5,
            "price_per_night_usd": 320,
            "amenities": ["pool", "spa", "gym"],
        },
        {
            "name": "Sakura Inn",
            "destination": destination,
            "checkin": checkin,
            "checkout": checkout,
            "stars": 3,
            "price_per_night_usd": 95,
            "amenities": ["wifi", "breakfast"],
        },
        {
            "name": "Capsule Stay",
            "destination": destination,
            "checkin": checkin,
            "checkout": checkout,
            "stars": 2,
            "price_per_night_usd": 45,
            "amenities": ["wifi"],
        },
    ]
# --8<-- [end:tool_function]


@mesh.agent(
    name="hotel-agent",
    version="1.0.0",
    description="TripPlanner hotel search tool (Day 6)",
    http_port=9102,
    enable_http=True,
    auto_run=True,
)
class HotelAgent:
    pass
# --8<-- [end:full_file]
