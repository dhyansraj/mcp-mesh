# --8<-- [start:full_file]
# --8<-- [start:imports]
import logging
import os
import re

import httpx
import mesh
from fastmcp import FastMCP

app = FastMCP("Hotel Agent")
# --8<-- [end:imports]

logger = logging.getLogger(__name__)


def _stub_hotels(destination: str, checkin: str, checkout: str) -> list[dict]:
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


def _extract_price(text: str) -> int | None:
    patterns = [
        r"\$\s*([\d,]+)\s*(?:per night|/night|a night|nightly)?",
        r"([\d,]+)\s*(?:USD|dollars)\s*(?:per night|/night)?",
        r"from\s*\$\s*([\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_stars(text: str) -> int | None:
    m = re.search(r"(\d)\s*[-]?\s*star", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 5:
            return val
    return None


async def _brave_search_hotels(
    destination: str, checkin: str, checkout: str, api_key: str,
) -> list[dict]:
    query = f"hotels in {destination} {checkin} to {checkout} price"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query},
            headers={"X-Subscription-Token": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return []

    hotels: list[dict] = []
    for r in results[:6]:
        title = r.get("title", "")
        description = r.get("description", "")
        combined = f"{title} {description}"
        url = r.get("url", "")

        name = re.sub(r"\s*[-|:].*$", "", title).strip()
        if not name:
            name = title

        hotel_entry: dict = {
            "name": name,
            "destination": destination,
            "checkin": checkin,
            "checkout": checkout,
            "source": url,
            "title": title,
            "description": description,
        }

        price = _extract_price(combined)
        if price is not None:
            hotel_entry["price_per_night_usd"] = price

        stars = _extract_stars(combined)
        if stars is not None:
            hotel_entry["stars"] = stars

        hotels.append(hotel_entry)

    return hotels


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
    """Search for hotels at a destination with check-in/out dates."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    note = None

    if api_key:
        try:
            hotels = await _brave_search_hotels(destination, checkin, checkout, api_key)
            if not hotels:
                hotels = _stub_hotels(destination, checkin, checkout)
                note = "Search returned no results; showing simulated data."
        except Exception as exc:
            logger.exception("Brave Search API failed for hotels in %s", destination)
            hotels = _stub_hotels(destination, checkin, checkout)
            note = f"Live search unavailable ({exc}); showing simulated data."
    else:
        hotels = _stub_hotels(destination, checkin, checkout)
        note = "BRAVE_SEARCH_API_KEY not set; showing simulated data."

    if note:
        for h in hotels:
            h["note"] = note

    return hotels
# --8<-- [end:tool_function]


@mesh.agent(
    name="hotel-agent",
    version="1.0.0",
    description="TripPlanner hotel search tool (Day 7)",
    http_port=9102,
    enable_http=True,
    auto_run=True,
)
class HotelAgent:
    pass
# --8<-- [end:full_file]
