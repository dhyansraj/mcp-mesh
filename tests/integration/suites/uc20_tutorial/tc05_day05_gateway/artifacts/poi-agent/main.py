# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("POI Agent")
# --8<-- [end:imports]


# --8<-- [start:tool_function]
# --8<-- [start:di_function]
@app.tool()
@mesh.tool(
    capability="poi_search",
    description="Search for points of interest at a location",
    tags=["poi", "travel"],
    dependencies=["weather_forecast"],
)
async def search_pois(
    location: str,
    weather: mesh.McpMeshTool = None,
) -> list[dict]:
    """Find points of interest, adjusted for weather conditions."""
    # Fetch weather via dependency injection
    forecast = await weather(location=location, date="today") if weather else {}

    rain_chance = forecast.get("rain_chance_pct", 0)
    prefer_indoor = rain_chance > 50

    outdoor_pois = [
        {"name": "Senso-ji Temple", "type": "outdoor", "category": "cultural"},
        {"name": "Ueno Park", "type": "outdoor", "category": "nature"},
        {"name": "Meiji Shrine", "type": "outdoor", "category": "cultural"},
    ]
    indoor_pois = [
        {"name": "TeamLab Borderless", "type": "indoor", "category": "art"},
        {"name": "Tokyo National Museum", "type": "indoor", "category": "museum"},
        {"name": "Akihabara Arcades", "type": "indoor", "category": "entertainment"},
    ]

    if prefer_indoor:
        pois = indoor_pois + outdoor_pois[:1]
        recommendation = "Rain likely — mostly indoor activities recommended."
    else:
        pois = outdoor_pois + indoor_pois[:1]
        recommendation = "Weather looks good — outdoor activities recommended."

    for poi in pois:
        poi["location"] = location

    return {
        "location": location,
        "weather_summary": forecast.get("summary", "unknown"),
        "recommendation": recommendation,
        "pois": pois,
    }
# --8<-- [end:di_function]
# --8<-- [end:tool_function]


@mesh.agent(
    name="poi-agent",
    version="1.0.0",
    description="TripPlanner points-of-interest tool (Day 4)",
    http_port=9104,
    enable_http=True,
    auto_run=True,
)
class PoiAgent:
    pass
# --8<-- [end:full_file]
