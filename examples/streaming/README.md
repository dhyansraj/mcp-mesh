# Streaming Examples

Two subdirectories:

## fixtures/

Test fixtures used by the tsuite `uc18_streaming` integration tests. All
agents support `MESH_LLM_DRY_RUN=1` mode (yields hardcoded chunks instead
of calling a real LLM) so they're fast and free to run in CI.

- [`chatbot-agent/`](./fixtures/chatbot-agent) — `chat` capability returning `mesh.Stream[str]`.
- [`passthrough-agent/`](./fixtures/passthrough-agent) — multi-hop intermediary that re-emits chunks upstream.
- [`gateway-agent/`](./fixtures/gateway-agent) — `mesh.route` SSE adapter for browser-direct consumption.

Run locally (no LLM key needed):

```bash
MESH_LLM_DRY_RUN=1 meshctl start examples/streaming/fixtures/chatbot-agent -d
meshctl start examples/streaming/fixtures/passthrough-agent -d
meshctl start examples/streaming/fixtures/gateway-agent -d
```

## chatbot-demo/

End-to-end demo with real Claude + a real weather tool (Open-Meteo, no
API key) + a single-page React UI. Run locally to see token-by-token
streaming with tool calls. Requires `ANTHROPIC_API_KEY`.

See [`chatbot-demo/README.md`](./chatbot-demo/README.md) for run instructions.

## See also

- [Streaming concept doc](../../docs/concepts/streaming.md) — design and protocol details
- `meshctl man streaming` — CLI quick reference
- Issue [#645](https://github.com/dhyansraj/mcp-mesh/issues/645) — original proposal
