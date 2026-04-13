# --8<-- [start:full_file]
# --8<-- [start:imports]
import logging
import os
import re

import httpx
import mesh
from fastmcp import FastMCP

app = FastMCP("Flight Agent")
# --8<-- [end:imports]

logger = logging.getLogger(__name__)


def _stub_flights(origin: str, destination: str, date: str) -> list[dict]:
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


def _extract_price(text: str) -> int | None:
    patterns = [
        r"\$\s*([\d,]+)",
        r"USD\s*([\d,]+)",
        r"([\d,]+)\s*(?:USD|dollars)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_time(text: str) -> str | None:
    m = re.search(r"\b(\d{1,2}:\d{2})\s*(?:AM|PM|am|pm)?\b", text)
    return m.group(0).strip() if m else None


async def _brave_search_flights(
    origin: str, destination: str, date: str, api_key: str,
) -> list[dict]:
    query = f"flights from {origin} to {destination} {date} price"
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

    flights: list[dict] = []
    for r in results[:6]:
        title = r.get("title", "")
        description = r.get("description", "")
        combined = f"{title} {description}"
        url = r.get("url", "")

        price = _extract_price(combined)

        flight_entry: dict = {
            "source": url,
            "title": title,
            "description": description,
            "origin": origin,
            "destination": destination,
            "date": date,
        }
        if price is not None:
            flight_entry["price_usd"] = price

        carrier_match = re.search(
            r"\b(United|Delta|American|Southwest|JetBlue|Spirit|Alaska|Frontier|"
            r"Singapore|Emirates|Qatar|Lufthansa|British Airways|Air France|ANA|JAL|"
            r"Korean Air|Cathay Pacific|Malaysia Airlines|Thai Airways)\b",
            combined, re.IGNORECASE,
        )
        if carrier_match:
            flight_entry["carrier"] = carrier_match.group(0)

        depart_time = _extract_time(combined)
        if depart_time:
            flight_entry["depart"] = depart_time

        flights.append(flight_entry)

    return flights


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

    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    note = None

    if api_key:
        try:
            flights = await _brave_search_flights(origin, destination, date, api_key)
            if not flights:
                flights = _stub_flights(origin, destination, date)
                note = "Search returned no results; showing simulated data."
        except Exception as exc:
            logger.exception("Brave Search API failed for flights %s -> %s", origin, destination)
            flights = _stub_flights(origin, destination, date)
            note = f"Live search unavailable ({exc}); showing simulated data."
    else:
        flights = _stub_flights(origin, destination, date)
        note = "BRAVE_SEARCH_API_KEY not set; showing simulated data."

    # Filter by budget (only for entries that have price_usd)
    flights = [f for f in flights if f.get("price_usd", 0) <= budget]

    # Sort preferred airlines first (only for entries that have carrier)
    if preferred_airlines:
        flights.sort(key=lambda f: f.get("carrier", "") not in preferred_airlines)

    if note:
        for f in flights:
            f["note"] = note

    return flights
# --8<-- [end:di_function]
# --8<-- [end:tool_function]


@mesh.agent(
    name="flight-agent",
    version="1.0.0",
    description="TripPlanner flight search tool (Day 7)",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class FlightAgent:
    pass
# --8<-- [end:full_file]
