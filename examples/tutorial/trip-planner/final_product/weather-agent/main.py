# --8<-- [start:full_file]
# --8<-- [start:imports]
import logging

import httpx
import mesh
from fastmcp import FastMCP

app = FastMCP("Weather Agent")
# --8<-- [end:imports]

logger = logging.getLogger(__name__)

_geocode_cache: dict[str, tuple[float, float]] = {}

WEATHER_CODE_MAP = {
    0: "clear",
    1: "partly_cloudy",
    2: "partly_cloudy",
    3: "partly_cloudy",
    45: "foggy",
    48: "foggy",
    51: "rainy",
    53: "rainy",
    55: "rainy",
    56: "rainy",
    57: "rainy",
    61: "rainy",
    63: "rainy",
    65: "rainy",
    67: "rainy",
    71: "snowy",
    73: "snowy",
    75: "snowy",
    77: "snowy",
    80: "showers",
    81: "showers",
    82: "showers",
    85: "snowy",
    86: "snowy",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}


async def _geocode(location: str) -> tuple[float, float]:
    """Geocode a location name to (lat, lon) using Nominatim. Results are cached."""
    cache_key = location.lower().strip()
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "TripPlanner/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data:
        raise ValueError(f"Could not geocode location: {location}")

    lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
    _geocode_cache[cache_key] = (lat, lon)
    return lat, lon


def _code_to_condition(code: int) -> str:
    return WEATHER_CODE_MAP.get(code, "partly_cloudy")


# --8<-- [start:tool_function]
@app.tool()
@mesh.tool(
    capability="weather_forecast",
    description="Get weather forecast for a location on a given date",
    tags=["weather", "travel"],
)
async def get_weather(location: str, date: str) -> dict:
    """Return weather forecast from Open-Meteo (free, no API key required)."""
    try:
        lat, lon = await _geocode(location)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                    "timezone": "auto",
                },
            )
            resp.raise_for_status()
            forecast = resp.json()

        daily = forecast.get("daily", {})
        dates = daily.get("time", [])

        if date in dates:
            idx = dates.index(date)
        else:
            idx = 0
            logger.warning(
                "Date %s not in forecast range (%s); using first available day",
                date,
                dates[0] if dates else "none",
            )

        high_c = daily["temperature_2m_max"][idx]
        low_c = daily["temperature_2m_min"][idx]
        rain_chance = daily["precipitation_probability_max"][idx]
        weather_code = daily["weathercode"][idx]
        condition = _code_to_condition(weather_code)
        actual_date = dates[idx]

        note = "" if date in dates else f" (forecast unavailable for {date}; showing {actual_date})"
        summary = (
            f"{condition.replace('_', ' ').title()} in {location} on {actual_date}, "
            f"{high_c}C high / {low_c}C low, {rain_chance}% chance of rain.{note}"
        )

        return {
            "location": location,
            "date": actual_date,
            "condition": condition,
            "high_c": high_c,
            "low_c": low_c,
            "rain_chance_pct": rain_chance,
            "summary": summary,
        }

    except Exception as exc:
        logger.exception("Weather API call failed for %s on %s", location, date)
        return {
            "location": location,
            "date": date,
            "condition": "partly_cloudy",
            "high_c": 25,
            "low_c": 17,
            "rain_chance_pct": 30,
            "summary": (
                f"Partly cloudy in {location} on {date}, 25C high, 30% chance of rain. "
                f"(Note: live forecast unavailable — {exc})"
            ),
        }
# --8<-- [end:tool_function]


@mesh.agent(
    name="weather-agent",
    version="1.0.0",
    description="TripPlanner weather forecast tool (Day 7)",
    http_port=9103,
    enable_http=True,
    auto_run=True,
)
class WeatherAgent:
    pass
# --8<-- [end:full_file]
