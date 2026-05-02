# Streaming Examples (issue #645)

End-to-end demo of MCP Mesh's auto-streaming pipeline. Three agents
exercise the three integration points landed for issue #645:

| Path | Demonstrates |
|------|--------------|
| Tool author opt-in | `mesh.Stream[str]` return → framework auto-forwards each chunk via FastMCP `Context.report_progress(message=chunk)` (P1) |
| Consumer side | `proxy.stream(...)` bridges incoming progress notifications into an `AsyncIterator[str]` (P2) |
| HTTP edge | `@mesh.route` handlers returning `mesh.Stream[str]` are auto-wrapped as Server-Sent Events (P3) |

## Topology

```
HTTP client ──▶ gateway-agent (SSE) ──▶ chatbot-agent (LLM stream)
                       │
                       └─▶ passthrough-agent ──▶ chatbot-agent  (multi-hop)
```

## Agents

- [`chatbot-agent/`](./chatbot-agent) — backend LLM streamer. Tool: `chat`.
  Set `MESH_LLM_DRY_RUN=1` to skip Anthropic and emit a deterministic chunk
  sequence; useful for tsuite tests.
- [`passthrough-agent/`](./passthrough-agent) — middle node that depends on
  `chat` and re-emits chunks via `chat_passthrough`. Verifies multi-hop
  streaming works without buffering.
- [`gateway-agent/`](./gateway-agent) — FastAPI app with two SSE endpoints
  (`POST /api/chat`, `POST /api/chat-multihop`) plus a non-streaming
  `GET /api/health` to verify P3's route rebuild does not regress
  plain-JSON routes.

## Run locally (dry-run, no LLM key needed)

```bash
MESH_LLM_DRY_RUN=1 meshctl start examples/streaming/chatbot-agent -d
meshctl start examples/streaming/passthrough-agent -d
meshctl start examples/streaming/gateway-agent -d
```

Find the gateway's HTTP port with `meshctl status`, then:

```bash
# Single-hop SSE
curl -N -X POST http://localhost:<gateway-port>/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hi"}'

# Multi-hop SSE (proves passthrough works)
curl -N -X POST http://localhost:<gateway-port>/api/chat-multihop \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hi"}'

# Non-streaming JSON (proves P3 didn't regress plain routes)
curl http://localhost:<gateway-port>/api/health
```

A minimal browser demo is served at `/` (uses `fetch` + `ReadableStream`
to consume the POST-based SSE stream — `EventSource` is GET-only so we
can't use it for these endpoints).

## Run with a real LLM

Drop the `MESH_LLM_DRY_RUN` flag and ensure a Claude provider is registered
in the mesh (see `examples/python/llm-provider/` for a minimal example or
`examples/llm-mesh-delegation/` for fuller patterns):

```bash
meshctl start examples/python/llm-provider -d
meshctl start examples/streaming/chatbot-agent -d
meshctl start examples/streaming/passthrough-agent -d
meshctl start examples/streaming/gateway-agent -d
```
