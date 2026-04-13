# TripPlanner — MCP Mesh Tutorial

TripPlanner is the application built across the 10-day MCP Mesh tutorial. It starts as
a single tool agent on Day 1 and ends as a multi-agent system running on Kubernetes
with an LLM planner, a committee of specialists, a chat API, and a full observability
stack.

The website tutorial that walks through building this step by step lives at
[mcp-mesh.ai/tutorial](https://mcp-mesh.ai/tutorial). The files in this directory are
the runnable code that each chapter produces.

## The 10-day arc

### Part 1 — Build and run

| Day   | Topic                                      | What you'll have built                             |
| ----- | ------------------------------------------ | -------------------------------------------------- |
| 1     | Scaffold and first tool agent              | One tool agent exposing `flight_search`            |
| 2     | More tools and dependency injection        | Hotel and weather agents, injected into flights    |
| 3     | Tags, versions, and smart routing          | Region-tagged agents, tag-based dependency resolve |
| 4     | LLM agent with Jinja prompt templates      | A planner LLM agent that uses all the tool agents  |
| 5     | FastAPI chat gateway                       | Stateless HTTP chat API backed by the planner      |

### Part 2 — Grow and scale

| Day   | Topic                                      | What you'll have built                             |
| ----- | ------------------------------------------ | -------------------------------------------------- |
| 6     | Committee of specialists                   | 3-specialist committee with a coordinator          |
| 7     | Chat history with Redis                    | Persistent, resumable conversations                |
| 8     | Observability — traces, metrics, dashboards| Grafana dashboards over OpenTelemetry traces       |
| 9     | Kubernetes deployment                      | Same code running on k8s via Helm                  |
| 10    | Production hardening                       | TLS, auth, rate limiting, autoscaling              |

Days 1-5 ship today. Days 6-10 are in active development and will be added in
subsequent PRs.

## Directory layout

```
trip-planner/
├── day-01/
│   ├── README.md
│   ├── python/
│   │   └── flight-agent/
│   │       ├── main.py
│   │       └── requirements.txt
│   ├── typescript/    # added in the TS wave
│   └── java/          # added in the Java wave
├── day-02/
│   └── ...
└── ...
```

Each `day-N/` is a complete, runnable snapshot of TripPlanner at the end of that day's
chapter. Jump to any day and follow its local `README.md` to run it.

## Running a specific day

```bash
# From the repo root
cd examples/tutorial/trip-planner/day-01
# Follow the instructions in day-01/README.md
```

## Following the tutorial

The prose explanations, diagrams, and rationale live on the website:
[mcp-mesh.ai/tutorial](https://mcp-mesh.ai/tutorial).

The website pulls code from these files via `pymdownx.snippets`, so the code you read
on the site is always the same code you run locally.
