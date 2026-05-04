# Streaming

> Token-by-token text responses over standard MCP progress notifications

When an LLM tool produces a long-form text response, buffering the entire answer until generation completes makes the user feel the agent is hung. Streaming lets the response appear character-by-character as the LLM writes it. The mesh wires this end-to-end — author, consumer, multi-hop intermediary, and browser-direct SSE — using the existing MCP protocol with no custom extensions.

## The problem

A `tools/call` request normally produces a single `CallToolResult` after the tool finishes. For a 2,000-word LLM response that takes 20 seconds to generate, the entire answer arrives at second 20 — there is nothing to render in the meantime. In multi-hop chains (gateway → passthrough → chatbot → LLM) the latency stacks: every hop waits for the previous one to fully complete.

Structured output (`output_type=PydanticModel`) genuinely cannot stream — the consumer needs complete valid JSON to validate against the schema. But plain-text responses have no such constraint and could safely arrive as they're generated.

## Solution: `Stream[str]` opt-in

Authors annotate their tool's return type as `mesh.Stream[str]` and `yield` chunks. The framework detects the streaming annotation, picks the streaming code path on both producer and consumer sides, and forwards each chunk over the open MCP connection.

```python
@app.tool()
@mesh.tool(capability="chat")
async def chat(prompt: str, llm: mesh.MeshLlmAgent = None) -> mesh.Stream[str]:
    async for chunk in llm.stream(prompt):
        yield chunk
```

There's no global config knob. Streaming is opt-in per tool by virtue of the return annotation. Plain `-> str` tools continue to be buffered exactly as before.

## How it works

The MCP protocol defines `notifications/progress` as an out-of-band message the server can push on the same SSE connection that's already open during a `tools/call` request. The mesh uses this as the wire-level transport for streamed chunks:

```
Client → POST /mcp tools/call {_meta: {progressToken: "abc"}}
Server ← event: message  data: {"method":"notifications/progress","params":{"progressToken":"abc","message":"Hello"}}
Server ← event: message  data: {"method":"notifications/progress","params":{"progressToken":"abc","message":" world"}}
Server ← event: message  data: {"method":"notifications/progress","params":{"progressToken":"abc","message":"!"}}
Server ← event: message  data: {"result":{"content":[{"type":"text","text":"Hello world!"}]}}
```

Each chunk is one progress notification. The complete accumulated text is also sent as the normal `CallToolResult` — consumers that don't subscribe to progress notifications still get the same final value, just all at once at the end.

## Two consumer surfaces

Once a producer streams, two consumer code paths are available — and both work in **all three runtimes** (Python, TypeScript, Java) as of #854.

**MCP-native (`proxy.stream(...)`)** — when a mesh agent depends on a streaming tool, calling `proxy.stream(...)` (or its language equivalent) returns an iterator of chunks. The framework subscribes to progress notifications on the open MCP connection and yields each one to the consumer.

=== "Python"

    ```python
    @mesh.tool(capability="passthrough", dependencies=["chat"])
    async def passthrough(prompt: str, chat: mesh.McpMeshTool = None) -> mesh.Stream[str]:
        async for chunk in chat.stream(prompt=prompt):
            yield chunk
    ```

=== "TypeScript"

    ```typescript
    // Inside a mesh.route handler:
    for await (const chunk of chat.stream({ prompt: req.body.prompt })) {
      // ...
    }
    ```

=== "Java"

    ```java
    // chat is an injected McpMeshTool<String>
    Flow.Publisher<String> publisher = chat.stream(Map.of("prompt", prompt));
    publisher.subscribe(/* ... */);
    ```

**Browser-direct (route handler + SSE)** — every runtime exposes a route layer that auto-wraps the stream as a Server-Sent Events response. Each chunk becomes a `data: <chunk>\n\n` line; the stream terminates with `data: [DONE]\n\n`. Browsers consume it via `fetch` + `ReadableStream` (`EventSource` is GET-only).

=== "Python (FastAPI)"

    ```python
    @app.post("/api/chat")
    @mesh.route(dependencies=["chat"])
    async def chat_endpoint(body: ChatRequest, chat: McpMeshTool = None) -> mesh.Stream[str]:
        async for chunk in chat.stream(prompt=body.prompt):
            yield chunk
    ```

=== "TypeScript (Express)"

    ```typescript
    import express from "express";
    import { mesh } from "@mcpmesh/sdk";

    app.post("/api/chat", mesh.route(
      [{ capability: "chat" }],
      async (req, res, { chat }) => {
        if (!chat) return res.status(503).json({ error: "chat unavailable" });
        await mesh.sseStream(res, chat.stream({ prompt: req.body.prompt }));
      }
    ));
    ```

=== "Java (Spring MVC)"

    ```java
    @PostMapping("/api/chat")
    @MeshRoute(dependencies = @MeshDependency(capability = "chat"))
    public SseEmitter chat(
        @RequestBody Map<String, Object> body,
        @MeshInject("chat") McpMeshTool<String> chat
    ) {
      SseEmitter emitter = new SseEmitter(0L);
      MeshSse.forward(emitter, chat.stream(body));
      return emitter;
    }
    ```

The Python helper is built into `@mesh.route` (auto-detects `Stream[str]` return type). TS uses the explicit `mesh.sseStream(res, asyncIterable)` Express helper. Java uses `MeshSse.forward(emitter, publisher)` to bridge a `Flow.Publisher<String>` into a Spring `SseEmitter`. All three emit identical wire bytes.

## Multi-hop streaming

Intermediate agents that re-emit chunks compose cleanly. Each hop is an `async for chunk in upstream.stream(...): yield chunk` loop, so chunks flow without buffering anywhere along the chain:

```
HTTP client ──▶ gateway (SSE) ──▶ passthrough ──▶ chatbot ──▶ Claude
                                       │              │
                                  proxy.stream()  llm.stream()
```

If any hop accidentally accumulates the chunks (e.g., `result = "".join([c async for c in upstream.stream(...)])`), the final user observes a single all-at-once block rather than a token-by-token stream — that's a regression to look for, not a hard error. The [chatbot-demo](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/streaming/chatbot-demo) shows the canonical multi-hop layout.

## Tool calls during streaming

LLM agentic loops can run multiple iterations: the LLM may call a tool, get a result, call another tool, get a result, and only then produce the final text. The mesh streams **only the final iteration**. Intermediate tool-calling iterations are fully buffered because the LLM needs each tool's complete result in its context for the next iteration.

In the chatbot-demo this means: a "what's the weather in New York?" prompt produces a brief silent pause (Claude calls `get_weather`, the tool runs, the result is added to context), then the answer streams token-by-token as Claude composes it.

## Pre-stream errors

Once the framework returns `StreamingResponse`, the HTTP status code is locked in as `200 OK`. Errors raised AFTER that point cannot change the status — they surface as `event: error\ndata: {"error": ..., "type": ...}` SSE frames in the body instead.

To raise pre-stream errors that should propagate as proper HTTP status codes (e.g., `503` when a dependency is unavailable, `400` for validation), structure the route as a coroutine that returns a generator instead of an async-generator function with `yield` directly:

```python
@app.post("/api/chat")
@mesh.route(dependencies=["chat"])
async def chat_endpoint(
    body: ChatRequest,
    chat: McpMeshTool = None,
) -> mesh.Stream[str]:
    if chat is None:
        raise HTTPException(status_code=503, detail="chat unavailable")
    return _stream_chat(body, chat)   # returns generator, no yield here

async def _stream_chat(body, chat):
    async for chunk in chat.stream(prompt=body.prompt):
        yield chunk
```

Pre-flight checks in `chat_endpoint` fire BEFORE `StreamingResponse` is built, so `HTTPException` propagates as a proper 503. Errors raised inside `_stream_chat` still surface as SSE error frames (mid-stream errors can't change status).

Both patterns are valid — pick the one that matches the error model. If only mid-stream errors matter, the simpler `async def ... yield` form is fine; if pre-flight failures must be visible to non-SSE clients via HTTP status, use the coroutine-returns-generator pattern.

## Direct vs mesh-delegate streaming

`MeshLlmAgent.stream()` works in both modes. **Direct mode** (consumer-supplied LiteLLM call) streams chunks straight from the vendor SDK. **Mesh-delegate mode** (zero-code `@mesh.llm_provider`) streams through the provider's auto-generated `process_chat_stream` tool — the provider runs the agentic loop, the consumer just iterates chunks.

The two modes share the same author surface; the resolver picks the right variant based on the consumer's return type:

| Consumer return type | Resolver matches | Provider tool used |
|----------------------|------------------|--------------------|
| `mesh.Stream[str]`   | `ai.mcpmesh.stream` (REQUIRED) | `process_chat_stream` (streaming) |
| `str` / Pydantic     | `-ai.mcpmesh.stream` (EXCLUDED) | `process_chat` (buffered) |

The matcher operators are unprefixed = REQUIRED, `+` = PREFERRED (bonus score), `-` = EXCLUDED. The streaming consumer requires the tag — a consumer with `Stream[str]` will fail to resolve a pre-Phase-5 provider that never advertised the tag (rather than silently degrading to buffered). A defensive runtime fallback exists for the rare case where the provider matched on tag but the streaming MCP tool itself errors with "unknown tool" mid-call.

## What it does NOT do (v1 limitations)

- **`Stream[str]` only.** `Stream[T]` for any `T != str` is rejected at decorator-time with a clear error. Typed Pydantic streaming is intentionally unsupported — the consumer needs complete JSON for schema validation, which contradicts the streaming model.

- **Final iteration only.** Intermediate tool-calling iterations in an agentic loop are always buffered. Only the LAST iteration (text-only, no tool calls) streams.

- **First chunk may appear instant for short responses.** Anthropic batches small responses, so a 1-token answer can land in a single SSE event with no observable streaming behavior. This is provider behavior, not a mesh issue.

- **Producers are Python-only (consumers work everywhere).** As of #854 the consumer side has full cross-runtime parity — TS (`proxy.stream()`, `mesh.sseStream`, `MeshLlmAgent.stream()`) and Java (`McpMeshTool.stream()`, `MeshSse.forward()`, `MeshLlmAgent.stream()`) all consume Python streaming tools at per-chunk granularity. **Producer-side streaming** (TS/Java tools that themselves return `Stream<string>` / `Flow.Publisher<String>`) is not yet implemented; that's tracked as Phase B of #854. A TS or Java tool that wants to stream today must delegate to a Python `@mesh.tool` returning `Stream[str]` (or to a Python `@mesh.llm_provider` for LLM streams).

## Wire protocol

The streaming protocol is plain MCP. There are no mesh-specific extensions on the wire. Any vanilla MCP client can consume a streaming tool by passing a `progressToken` in `_meta` and registering a `progress_handler` callback (Cursor, Claude Desktop, Cline, the official `fastmcp.Client`, etc. all already support this).

This means a `mesh.Stream[str]` tool is interoperable with the broader MCP ecosystem — the streaming behavior is not gated on having mesh on the consumer side. It's only the *ergonomics* (`async for chunk in proxy.stream(...)`) that the mesh adds on top.

## Example

A minimal three-piece setup: a streaming tool, an SSE gateway, and a Python consumer.

**Producer — `chatbot/main.py`:**

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

@mesh.agent(name="chatbot", http_port=9181, auto_run=True)
class ChatbotAgent: pass
```

**Browser gateway — `gateway/main.py`:**

```python
import mesh
from fastapi import FastAPI
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

**MCP-native consumer — `consumer.py`:**

```python
from fastmcp import Client

async def main():
    async def on_chunk(progress, total, message):
        print(message, end="", flush=True)

    async with Client("http://localhost:9181/mcp") as client:
        await client.call_tool("chat", {"prompt": "hi"}, progress_handler=on_chunk)
```

## See Also

- [Chatbot demo](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/streaming/chatbot-demo) — real-LLM end-to-end demo with a browser UI
- [Test fixtures](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/streaming/fixtures) — minimal dry-run agents used by the integration tests
- [Schema Matching](schema-matching.md) — why typed responses don't stream (`output_type` semantics)
- [Audit Trail](audit.md) — `progressToken` and trace context propagation
- [DDDI](dddi.md) — Distributed Dynamic Dependency Injection overview
