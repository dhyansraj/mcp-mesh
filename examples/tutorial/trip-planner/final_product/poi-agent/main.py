# --8<-- [start:full_file]
# --8<-- [start:imports]
import logging
import os
import re

import httpx
import mesh
from fastmcp import FastMCP

app = FastMCP("POI Agent")
# --8<-- [end:imports]

logger = logging.getLogger(__name__)

INDOOR_KEYWORDS = [
    "museum", "gallery", "theater", "theatre", "cinema", "mall", "shopping",
    "aquarium", "arcade", "spa", "indoor", "exhibit", "planetarium", "library",
]
OUTDOOR_KEYWORDS = [
    "park", "garden", "beach", "trail", "hike", "mountain", "temple", "shrine",
    "outdoor", "zoo", "lake", "river", "waterfall", "market", "square", "plaza",
]


def _classify_type(text: str) -> str:
    lower = text.lower()
    indoor_score = sum(1 for kw in INDOOR_KEYWORDS if kw in lower)
    outdoor_score = sum(1 for kw in OUTDOOR_KEYWORDS if kw in lower)
    if indoor_score > outdoor_score:
        return "indoor"
    if outdoor_score > indoor_score:
        return "outdoor"
    return "outdoor"


def _extract_category(text: str) -> str:
    categories = {
        "cultural": ["temple", "shrine", "heritage", "historic", "monument", "palace", "castle"],
        "nature": ["park", "garden", "beach", "trail", "mountain", "lake", "waterfall", "nature"],
        "art": ["museum", "gallery", "art", "exhibit"],
        "entertainment": ["arcade", "amusement", "theme park", "cinema", "theater", "show"],
        "food": ["restaurant", "food", "market", "street food", "cuisine", "dining"],
        "shopping": ["mall", "shopping", "market", "bazaar", "store"],
    }
    lower = text.lower()
    for cat, keywords in categories.items():
        if any(kw in lower for kw in keywords):
            return cat
    return "attraction"


def _stub_pois(location: str, prefer_indoor: bool) -> list[dict]:
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
    else:
        pois = outdoor_pois + indoor_pois[:1]
    for poi in pois:
        poi["location"] = location
    return pois


async def _brave_search_pois(location: str, api_key: str) -> list[dict]:
    query = f"top attractions and things to do in {location}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query},
            headers={"X-Subscription-Token": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("web", {}).get("results", [])
    pois = []
    seen_names = set()

    for r in results:
        title = r.get("title", "")
        description = r.get("description", "")
        combined = f"{title} {description}"

        name = re.sub(r"\s*[-|:].*$", "", title).strip()
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        pois.append({
            "name": name,
            "type": _classify_type(combined),
            "category": _extract_category(combined),
            "location": location,
            "source_url": r.get("url", ""),
        })

        if len(pois) >= 6:
            break

    return pois


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
) -> dict:
    """Find points of interest, adjusted for weather conditions."""
    # Fetch weather via dependency injection
    forecast = await weather(location=location, date="today") if weather else {}

    rain_chance = forecast.get("rain_chance_pct", 0)
    prefer_indoor = rain_chance > 50

    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    note = None

    if api_key:
        try:
            pois = await _brave_search_pois(location, api_key)
            if not pois:
                pois = _stub_pois(location, prefer_indoor)
                note = "Search returned no results; showing simulated data."
        except Exception as exc:
            logger.exception("Brave Search API failed for POIs in %s", location)
            pois = _stub_pois(location, prefer_indoor)
            note = f"Live search unavailable ({exc}); showing simulated data."
    else:
        pois = _stub_pois(location, prefer_indoor)
        note = "BRAVE_SEARCH_API_KEY not set; showing simulated data."

    if prefer_indoor and api_key and not note:
        indoor = [p for p in pois if p["type"] == "indoor"]
        outdoor = [p for p in pois if p["type"] == "outdoor"]
        pois = indoor + outdoor
        recommendation = "Rain likely — indoor activities listed first."
    elif not prefer_indoor and api_key and not note:
        outdoor = [p for p in pois if p["type"] == "outdoor"]
        indoor = [p for p in pois if p["type"] == "indoor"]
        pois = outdoor + indoor
        recommendation = "Weather looks good — outdoor activities listed first."
    elif prefer_indoor:
        recommendation = "Rain likely — mostly indoor activities recommended."
    else:
        recommendation = "Weather looks good — outdoor activities recommended."

    result = {
        "location": location,
        "weather_summary": forecast.get("summary", "unknown"),
        "recommendation": recommendation,
        "pois": pois,
    }
    if note:
        result["note"] = note

    return result
# --8<-- [end:di_function]
# --8<-- [end:tool_function]


@mesh.agent(
    name="poi-agent",
    version="1.0.0",
    description="TripPlanner points-of-interest tool (Day 7)",
    http_port=9104,
    enable_http=True,
    auto_run=True,
)
class PoiAgent:
    pass
# --8<-- [end:full_file]
