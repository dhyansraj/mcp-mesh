# planner-agent

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner LLM planner (Day 3). Uses an LLM provider via mesh delegation to generate trip itineraries from natural language.

## Prerequisites

- Python 3.11+
- MCP Mesh SDK
- An LLM provider agent running in the mesh (e.g. claude-provider)

## Running the Agent

```bash
meshctl start main.py
```

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `plan_trip` | `trip_planning` | Generate a trip itinerary using an LLM |

## License

MIT
