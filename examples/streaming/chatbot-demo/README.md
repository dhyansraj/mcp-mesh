# Streaming Chatbot Demo

End-to-end demo: React UI → `mesh.route` SSE → Claude LLM (with tool calling) → weather tool.

Validates the streaming infrastructure from issue [#645](https://github.com/dhyansraj/mcp-mesh/issues/645)
with a real LLM and a real browser UI, end-to-end. The UI renders tokens
exactly as they arrive over the wire — no fake typing animation.

For the underlying mental model see the [streaming concept doc](../../../docs/concepts/streaming.md).

## Topology

```
Browser (React, fetch + ReadableStream)
   │  POST /api/chat  (SSE response)
   ▼
gateway        (FastAPI + @mesh.route, SSE adapter)
   │  proxy.stream(prompt=...)
   ▼
chatbot-agent  (@mesh.tool returning mesh.Stream[str], wraps llm.stream())
   │  Anthropic API
   ▼
Claude  ──── tool call ───▶ weather-tool  (Open-Meteo lookup)
```

The chatbot-agent depends on a Claude `llm` provider (registered with
`tags=["claude"]`). Use the bundled tutorial provider or any other Claude
provider already running in your mesh.

## Prerequisites

- mcp-mesh runtime installed (`pip install -e src/runtime/python`, or `make install`)
- A running mcp-mesh registry (`meshctl start --registry-only`, or any `meshctl start`
  command auto-starts one)
- `ANTHROPIC_API_KEY` exported in the shell that starts the Claude provider

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Claude provider (any one will do — example uses the tutorial provider)
meshctl start examples/tutorial/trip-planner/day-09/python/claude-provider/main.py -d

# Demo agents
meshctl start examples/streaming/chatbot-demo/weather-tool/main.py   -d
meshctl start examples/streaming/chatbot-demo/chatbot-agent/main.py  -d
meshctl start examples/streaming/chatbot-demo/gateway/main.py        -d

# Find the gateway's HTTP port
meshctl list

# Open the chat UI (default port 9182)
open http://localhost:9182/
```

## What you should see

1. Type "what's the weather in New York?" and click Send.
2. A brief "thinking..." spinner — request is in flight.
3. A pause while Claude calls the `get_weather` tool. The intermediate
   tool-calling iteration is buffered (final-iteration-only streaming is
   a documented v1 limitation) and is intentionally silent.
4. Tokens stream in live as Claude composes the final response.

### Verify it is real streaming

Open DevTools → Network → click the `/api/chat` request → Response /
EventStream tab. You should see `data: <chunk>` events arriving over time
(distinct timestamps), terminated by `data: [DONE]`. The response body grows
incrementally; it is not delivered as a single blob.

You can also confirm from the terminal:

```bash
curl -N -X POST http://localhost:9182/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "what is the weather in New York?"}'
```

`-N` disables curl's output buffering so you see chunks as they arrive.

## v1 limitations

The streaming pipeline is intentionally narrow in v1. See the
[concept doc](../../../docs/concepts/streaming.md#what-it-does-not-do-v1-limitations)
for the full list. Highlights:

- **Direct-mode LLM only** — the `chatbot-agent` here uses a `MeshLlmAgent`
  proxy whose injected provider does direct LiteLLM calls. Mesh-delegated
  providers (`@mesh.llm_provider` zero-code wrappers) raise
  `NotImplementedError` for `stream()`. Tracked separately as a follow-up.
- **`Stream[str]` only** — `Stream[T]` for `T != str` is rejected at
  decorator-time. Typed Pydantic streaming has no clean semantics
  (the consumer needs complete JSON for schema validation).
- **Final iteration only** — only the LAST agentic-loop iteration streams.
  All intermediate tool-calling iterations are fully buffered (the LLM needs
  their complete results in context for the next iteration).
- **No conversation history** — each request is independent. The demo is
  one-shot Q-and-A.
- **No auth, no persistence** — demo-quality only.
- **First chunk may appear instant for short responses** — Anthropic batches
  small responses, so a 1-token answer can land in a single SSE event.

## See also

- [Streaming concept doc](../../../docs/concepts/streaming.md) — design and wire protocol
- `meshctl man streaming` — CLI quick reference
- [Test fixtures](../fixtures/) — minimal dry-run agents used by `uc18_streaming` tsuite
- Issue [#645](https://github.com/dhyansraj/mcp-mesh/issues/645) — original proposal
