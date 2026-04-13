# --8<-- [start:full_file]
# --8<-- [start:imports]
import mesh
from fastmcp import FastMCP

app = FastMCP("Weather Agent")
# --8<-- [end:imports]


# --8<-- [start:tool_function]
@app.tool()
@mesh.tool(
    capability="weather_forecast",
    description="Get weather forecast for a location on a given date",
    tags=["weather", "travel"],
)
async def get_weather(location: str, date: str) -> dict:
    """Return weather forecast. Stub data for Day 2."""
    return {
        "location": location,
        "date": date,
        "condition": "partly_cloudy",
        "high_c": 28,
        "low_c": 19,
        "rain_chance_pct": 30,
        "summary": f"Partly cloudy in {location} on {date}, 28C high, 30% chance of rain.",
    }
# --8<-- [end:tool_function]


@mesh.agent(
    name="weather-agent",
    version="1.0.0",
    description="TripPlanner weather forecast tool (Day 2)",
    http_port=9103,
    enable_http=True,
    auto_run=True,
)
class WeatherAgent:
    pass
# --8<-- [end:full_file]
