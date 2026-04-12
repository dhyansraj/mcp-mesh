# TripPlanner — Day 1

Scaffold and run your first tool agent: `flight-agent`. It exposes a single
`flight_search` function that returns stub flight data.

This is the runnable snapshot that the Day 1 tutorial page produces. The website
walks through building it step by step at
[mcp-mesh.ai/tutorial/day-01-scaffold](https://mcp-mesh.ai/tutorial/day-01-scaffold/).

## What you need

- Python 3.11 or later
- `meshctl` on your `PATH` — see the website [Prerequisites](https://mcp-mesh.ai/tutorial/prerequisites/)

## Run it

From this directory:

```bash
# 1. Create a venv and install mcp-mesh (one-time setup)
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install mcp-mesh
deactivate

# 2. Start registry and flight-agent (detached)
meshctl start python/flight-agent/main.py -d

# 3. Inspect what's running
meshctl list
meshctl list --tools

# 4. Call the flight_search tool
meshctl call flight_search '{"origin":"SFO","destination":"NRT","date":"2026-06-01"}'

# 5. Stop everything
meshctl stop
```

`meshctl start` walks upward from the agent file looking for a `.venv` directory, so
you don't need to activate the venv to run the agent — only to run `pip install`.

## Expected output

### `meshctl list`

```
Registry: healthy (http://localhost:8000) - 1 healthy, uptime 12s

NAME          RUNTIME  TYPE        STATUS   DEPS  ENDPOINT
flight-agent  python   mesh_tool   healthy  0/0   http://localhost:9101
```

### `meshctl list --tools`

```
TOOL           CAPABILITY      AGENT         TAGS
flight_search  flight_search   flight-agent  flights, travel
```

### `meshctl call flight_search ...`

```json
[
  {
    "carrier": "MH",
    "flight": "MH007",
    "origin": "SFO",
    "destination": "NRT",
    "date": "2026-06-01",
    "depart": "09:15",
    "arrive": "14:40",
    "price_usd": 842
  },
  {
    "carrier": "SQ",
    "flight": "SQ017",
    "origin": "SFO",
    "destination": "NRT",
    "date": "2026-06-01",
    "depart": "11:50",
    "arrive": "17:05",
    "price_usd": 901
  }
]
```

## Files

```
day-01/
├── README.md              # this file
└── python/
    └── flight-agent/
        ├── main.py        # the flight_search tool
        └── requirements.txt
```

## Next

Day 2 adds hotel and weather agents and introduces dependency injection between them.
