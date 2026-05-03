# gateway (streaming, Day 10 bonus)

Streaming variant of the Day 9 gateway. The `/plan` route returns
`mesh.Stream[str]` so chunks from the planner flow straight through to the
browser as SSE frames.

## What's different from Day 9

- `/plan` returns `mesh.Stream[str]` instead of buffered JSON.
- The route uses the **coroutine-returns-generator pattern** so pre-stream
  errors (missing dependency, malformed body) raise `HTTPException` and
  surface as proper HTTP status codes.
- A new `GET /` route serves the bundled mobile-first React UI from
  `static/index.html`.

## Running

```bash
meshctl start main.py
```

Open `http://localhost:8080/` in a browser to use the UI, or POST directly:

```bash
curl -N -X POST http://localhost:8080/plan \
  -H "Content-Type: application/json" \
  -d '{"destination": "Tokyo", "dates": "Jun 1-5, 2026", "budget": "$2000"}'
```
