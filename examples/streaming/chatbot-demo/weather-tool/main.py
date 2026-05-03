#!/usr/bin/env python3
"""weather-tool - Open-Meteo current-weather lookup for the streaming chatbot spike."""

import httpx
import mesh
from fastmcp import FastMCP

app = FastMCP("WeatherTool Service")


_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


# WMO Weather interpretation codes — https://open-meteo.com/en/docs
_WMO_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow fall",
    73: "moderate snow fall",
    75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


@app.tool()
@mesh.tool(
    capability="get_weather",
    description="Fetch current weather for a city via Open-Meteo (no API key required)",
    version="1.0.0",
    tags=["tools", "weather"],
)
async def get_weather(city: str) -> dict:
    """Return current temperature and conditions for ``city``."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            geo_resp = await client.get(
                _GEOCODE_URL, params={"name": city, "count": 1}
            )
            geo_resp.raise_for_status()
        except httpx.HTTPError as exc:
            return {"error": f"geocoding failed for {city!r}: {exc}"}

        try:
            geo = geo_resp.json()
        except ValueError as exc:
            return {"error": f"geocoding returned malformed JSON for {city!r}: {exc}"}

        if not isinstance(geo, dict):
            return {"error": f"geocoding returned unexpected payload for {city!r}"}

        results = geo.get("results") or []
        if not results:
            return {"error": f"city not found: {city!r}"}

        place = results[0]
        if not isinstance(place, dict):
            return {"error": f"geocoding returned unexpected result entry for {city!r}"}

        try:
            lat = place["latitude"]
            lon = place["longitude"]
        except (KeyError, TypeError) as exc:
            return {"error": f"geocoding result missing coordinates for {city!r}: {exc}"}

        resolved_name = ", ".join(
            part for part in (place.get("name"), place.get("country")) if part
        )

        try:
            forecast_resp = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                },
            )
            forecast_resp.raise_for_status()
        except httpx.HTTPError as exc:
            return {"error": f"forecast failed for {city!r}: {exc}"}

        try:
            forecast = forecast_resp.json()
        except ValueError as exc:
            return {"error": f"forecast returned malformed JSON for {city!r}: {exc}"}

        if not isinstance(forecast, dict):
            return {"error": f"forecast returned unexpected payload for {city!r}"}

        current = forecast.get("current") or {}
        if not isinstance(current, dict):
            current = {}
        temp_c = current.get("temperature_2m")
        code = current.get("weather_code")
        conditions = _WMO_CODES.get(code, f"unknown (code {code})")

        return {
            "city": resolved_name or city,
            "temp_c": temp_c,
            "conditions": conditions,
        }


@mesh.agent(
    name="weather-tool",
    version="1.0.0",
    description="Current-weather lookup via Open-Meteo for the streaming chatbot spike",
    http_port=9180,
    enable_http=True,
    auto_run=True,
)
class WeatherToolAgent:
    pass
