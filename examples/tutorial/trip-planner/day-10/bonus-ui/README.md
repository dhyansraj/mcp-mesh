# TripPlanner Streaming UI (Bonus Chapter)

Mobile-first React UI that streams trip plans live as Claude generates them
through the multi-agent committee pipeline. See
`docs/tutorial/day-10-bonus-streaming-ui.md` for the full walkthrough.

## Quick start

Requires the full Day 9 mesh running (all 13 agents) plus `ANTHROPIC_API_KEY`.

Replace the existing planner-agent and gateway with the streaming variants:

```bash
meshctl stop planner gateway
meshctl start day-10/bonus-ui/python/planner-agent/main.py -d
meshctl start day-10/bonus-ui/python/gateway/main.py -d
```

Open <http://localhost:8080/> in a browser and watch tokens stream as Claude
plans your trip across the committee + tool dependencies.

## What's in here

- `python/planner-agent/` — streaming variant: returns `mesh.Stream[str]`,
  pre-fetches committee insights, then streams the final LLM call.
- `python/gateway/` — streaming variant: `/plan` returns `mesh.Stream[str]`
  (auto SSE), `GET /` serves the React UI from `static/index.html`.

## Testing without an API key

Set `MESH_LLM_DRY_RUN=1` on the planner. It exercises every dependency
(committee + chat history + user prefs) and yields a deterministic chunk
sequence — used by the streaming integration test
(`uc20/tc11_day10_bonus_streaming`).

```bash
MESH_LLM_DRY_RUN=1 meshctl start day-10/bonus-ui/python/planner-agent/main.py -d
```
