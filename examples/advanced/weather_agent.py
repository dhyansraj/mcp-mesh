#!/usr/bin/env python3
"""
MCP Mesh Weather Agent Example

This agent provides weather information capabilities with automatic location detection.
Demonstrates the tools vs capabilities architecture:

- Tools: Function names (MCP function names)
- Capabilities: What others can depend on
- Auto location detection: Uses IP geolocation to determine local weather
- Pure simplicity: Just decorators, no manual setup!

Function names can be different from capability names for maximum flexibility.
"""

import json
import urllib.error
import urllib.request
from typing import Any

import mesh


@mesh.agent(name="weather-agent", http_port=9092)
class WeatherAgent:
    """Weather information agent providing location-based weather capabilities."""

    pass


def get_location_from_ip():
    """Get location coordinates from IP address using a free geolocation service."""
    try:
        # Using ipapi.co (free, no API key required)
        with urllib.request.urlopen("https://ipapi.co/json/", timeout=5) as response:
            data = json.loads(response.read().decode())
            return {
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "city": data.get("city", "Unknown"),
                "region": data.get("region", "Unknown"),
                "country": data.get("country_name", "Unknown"),
                "timezone": data.get("timezone", "UTC"),
            }
    except Exception as e:
        # Fallback to Charlotte, NC if location detection fails
        return {
            "latitude": 35.2271,
            "longitude": -80.8431,
            "city": "Charlotte",
            "region": "North Carolina",
            "country": "United States",
            "timezone": "America/New_York",
            "error": f"Location detection failed: {str(e)}, using fallback",
        }


# ===== WEATHER SERVICE =====
# Tool: "get_local_weather" | Capability: "weather_service"


@mesh.tool(
    capability="weather_service",  # Capability name (what others depend on)
    description="Get current weather information for the local system location",
    version="1.0.0",
    tags=["weather", "temperature", "location", "local", "auto-detect"],
)
def get_local_weather() -> dict[str, Any]:  # Function name can be anything!
    """
    Get current weather information for the local system location using automatic IP geolocation.

    This function provides the "weather_service" capability.
    First detects location via IP, then fetches weather data for that location.

    Returns:
        Dictionary with comprehensive weather data including location, temp, conditions, etc.
    """
    # First, detect location
    location = get_location_from_ip()

    try:
        # Using Open-Meteo API (free, no API key required)
        latitude = location["latitude"]
        longitude = location["longitude"]
        timezone = location.get("timezone", "UTC")

        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&timezone={timezone}"

        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

            current = data.get("current", {})

            # Map weather codes to descriptions (simplified)
            weather_codes = {
                0: "Clear sky",
                1: "Mainly clear",
                2: "Partly cloudy",
                3: "Overcast",
                45: "Fog",
                48: "Depositing rime fog",
                51: "Light drizzle",
                53: "Moderate drizzle",
                55: "Dense drizzle",
                61: "Slight rain",
                63: "Moderate rain",
                65: "Heavy rain",
                71: "Slight snow",
                73: "Moderate snow",
                75: "Heavy snow",
                80: "Slight rain showers",
                81: "Moderate rain showers",
                82: "Violent rain showers",
                95: "Thunderstorm",
                96: "Thunderstorm with slight hail",
                99: "Thunderstorm with heavy hail",
            }

            weather_code = current.get("weather_code", 0)
            weather_desc = weather_codes.get(weather_code, "Unknown")

            # Format location string
            location_str = (
                f"{location['city']}, {location['region']}, {location['country']}"
            )

            return {
                "location": location_str,
                "coordinates": {"latitude": latitude, "longitude": longitude},
                "temperature_f": current.get("temperature_2m"),
                "feels_like_f": current.get("apparent_temperature"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "wind_speed_mph": current.get("wind_speed_10m"),
                "precipitation_inch": current.get("precipitation"),
                "weather_description": weather_desc,
                "is_day": current.get("is_day") == 1,
                "timestamp": current.get("time"),
                "timezone": timezone,
                "source": "Open-Meteo API + IP Geolocation",
                "location_method": (
                    "auto-detected" if "error" not in location else "fallback"
                ),
                "formatted": f"{current.get('temperature_2m', 'N/A')}°F in {location['city']}, {location['region']} - {weather_desc}",
            }

    except urllib.error.URLError as e:
        # Network error - return fallback with location info
        location_str = (
            f"{location['city']}, {location['region']}, {location['country']}"
        )
        return {
            "location": location_str,
            "temperature_f": "N/A",
            "error": f"Weather API network error: {str(e)}",
            "formatted": f"Weather unavailable for {location['city']} (network error)",
            "location_method": (
                "auto-detected" if "error" not in location else "fallback"
            ),
            "source": "Fallback",
        }
    except Exception as e:
        # Any other error - return fallback with location info
        location_str = (
            f"{location['city']}, {location['region']}, {location['country']}"
        )
        return {
            "location": location_str,
            "temperature_f": "N/A",
            "error": f"Weather API error: {str(e)}",
            "formatted": f"Weather unavailable for {location['city']} (service error)",
            "location_method": (
                "auto-detected" if "error" not in location else "fallback"
            ),
            "source": "Fallback",
        }
