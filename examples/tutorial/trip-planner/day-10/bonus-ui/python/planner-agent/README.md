# planner-agent (streaming, Day 10 bonus)

Streaming variant of the Day 9 planner. Returns `mesh.Stream[str]` so the
final user-visible response is yielded chunk-by-chunk while the agentic loop
runs (real flight/hotel/weather/poi tool calls included).

## What's different from Day 9

- Return type: `mesh.Stream[str]` instead of `str`
- The committee specialists (budget, adventure, logistics) run BEFORE the
  streaming LLM call so their insights can be injected into the LLM context.
  Each specialist is still a buffered, non-streaming call.
- A `MESH_LLM_DRY_RUN=1` mode emits a deterministic chunk sequence without
  hitting Claude — used by the streaming integration test (uc20 tc06).

## Running

```bash
meshctl start main.py
```

Or with the dry-run mode for tests without an Anthropic API key:

```bash
MESH_LLM_DRY_RUN=1 meshctl start main.py
```

The agent listens on port 9107 (same as the Day 9 planner).
