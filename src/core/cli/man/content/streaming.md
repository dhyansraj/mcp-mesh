# Streaming

> Token-by-token text responses over standard MCP progress notifications (issue #645)

## Overview

When a tool returns long-form text (LLM responses in particular), buffering the whole answer until generation finishes makes the agent feel hung. MCP Mesh streams text responses token-by-token using the standard MCP `notifications/progress` mechanism — no protocol extensions, no global config knob. Streaming is opt-in per tool via the return-type annotation.

The complete accumulated text is also sent as the normal `CallToolResult`, so non-streaming consumers continue to work unchanged.

## Author API: `Stream[str]` return annotation

Annotate the tool's return type as `mesh.Stream[str]` and `yield` chunks. The framework picks the streaming code path automatically.

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("Chatbot")

@app.tool()
@mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
@mesh.tool(capability="chat")
async def chat(prompt: str, llm: mesh.MeshLlmAgent = None) -> mesh.Stream[str]:
    async for chunk in llm.stream(prompt):
        yield chunk
```

`Stream[T]` for any `T != str` is rejected at decorator time. Plain `-> str` tools continue to be buffered.

## Consumer API: `proxy.stream()` (Python)

When a mesh agent depends on a streaming tool, calling `proxy.stream(...)` returns an async iterator of chunks:

```python
@mesh.tool(capability="passthrough", dependencies=["chat"])
async def passthrough(prompt: str, chat: mesh.McpMeshTool = None) -> mesh.Stream[str]:
    async for chunk in chat.stream(prompt=prompt):
        yield chunk
```

This bridges incoming `notifications/progress` messages into an `AsyncIterator[str]`. Multi-hop streaming composes by re-yielding chunks at each layer.

> Note: TypeScript and Java SDKs do not yet expose `proxy.stream()`. Wire-level streaming still works (a TS or Java client receives the buffered final result), but per-chunk delivery requires Python on the consumer side. Cross-runtime parity is on the roadmap.

## Browser via `mesh.route` auto-SSE

A FastAPI route handler that returns `mesh.Stream[str]` is auto-wrapped as Server-Sent Events. Each chunk becomes a `data: <chunk>\n\n` line; the stream terminates with `data: [DONE]\n\n`.

```python
from fastapi import FastAPI
import mesh
from mesh.types import McpMeshTool
from pydantic import BaseModel

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str

@app.post("/api/chat")
@mesh.route(dependencies=["chat"])
async def chat_endpoint(body: ChatRequest, chat: McpMeshTool = None) -> mesh.Stream[str]:
    async for chunk in chat.stream(prompt=body.prompt):
        yield chunk
```

Browsers consume via `fetch` + `ReadableStream` (`EventSource` is GET-only and won't work for POST endpoints). Plain JSON `mesh.route` handlers on the same agent are unaffected — only routes that declare a `Stream[str]` return type get the SSE wrapper.

## Wire format

The protocol is unmodified MCP. Any vanilla MCP client (Cursor, Claude Desktop, Cline, `fastmcp.Client`) can subscribe to chunks by passing a `progressToken` in `_meta` and registering a `progress_handler`:

```
Client → POST /mcp tools/call {_meta: {progressToken: "abc"}}
Server ← notifications/progress {progressToken: "abc", message: "Hello"}
Server ← notifications/progress {progressToken: "abc", message: " world"}
Server ← {result: {content: [{type: "text", text: "Hello world"}]}}
```

## Limitations

- **Direct-mode LLM only** — `MeshLlmAgent.stream()` works when the injected provider does direct LiteLLM calls. Mesh-delegated providers (zero-code `@mesh.llm_provider` wrappers) raise `NotImplementedError` for `stream()`.
- **`Stream[str]` only** — typed Pydantic streaming is intentionally unsupported (consumer needs complete JSON for schema validation).
- **Final iteration only** — in agentic loops, only the LAST iteration (text-only, no tool calls) streams. Intermediate tool-calling iterations are buffered.
- **Python only for `proxy.stream()`** — TS/Java consumer parity pending.
- **Short responses may not appear streamed** — Anthropic batches small responses, so a 1-token answer can land in a single SSE event.

See `meshctl man llm` for `MeshLlmAgent` details. See the [streaming concept doc](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/streaming.md) for design rationale and the full wire-protocol walkthrough.

## See Also

- `meshctl man decorators` — `@mesh.tool`, `@mesh.route` decorator reference
- `meshctl man llm` — LLM integration and `MeshLlmAgent.stream()`
- `meshctl man api` — FastAPI integration with `@mesh.route`
- [examples/streaming/](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/streaming) — `fixtures/` (test fixtures) and `chatbot-demo/` (real-LLM end-to-end demo)
