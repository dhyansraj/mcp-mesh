# Service View Example — `@mesh.service` (RFC #1280, Python)

**Three methods, three different provider agents, one typed interface.**

This is the Python sibling of
[`examples/java/service-view`](../../java/service-view) and
[`examples/typescript/service-view`](../../typescript/service-view). All three
tell the same story with the **same `media.*` capabilities**, so the agents are
**cross-runtime interchangeable** — a Python gateway can consume the Java
providers, a Java gateway can consume the TypeScript providers, and so on.

A service view aggregates several ordinary capability dependencies behind one
typed interface. Each method binds a single capability, and calling it delegates
to that capability's own resolved proxy — so different methods resolve to
**different provider agents** and rebind independently as topology changes.

## Agents

| Agent                 | Port | Capability         | Role                                   |
|-----------------------|------|--------------------|----------------------------------------|
| `caption-provider`    | 8120 | `media.caption`    | Provider A — captions an asset         |
| `thumbnail-provider`  | 8121 | `media.thumbnail`  | Provider B — thumbnails an asset       |
| `transcribe-provider` | 8122 | `media.transcribe` | Provider C — transcribes an asset      |
| `media-gateway`       | 8123 | `process_media`    | Consumer — one `MediaService` view     |

## Producer side: publish a dotted capability explicitly

Each provider declares its dotted wire capability directly on the tool with
`@mesh.tool(capability="media.<method>")`. The capability is chosen
deliberately — it is never derived from the Python function name.

```python
@app.tool()
@mesh.tool(capability="media.caption")   # dotted capability declared explicitly
async def caption(assetId: str, text: str) -> dict:
    return {"assetId": assetId, "caption": ..., "provider": "caption-provider"}
```

- **Dotted capability names are first-class** across the stack — the
  registry and the Python/Java/TypeScript runtimes all accept segment-wise names
  like `media.caption`.
- **The namespace is yours** — `"media"` carries no special meaning. All three
  agents publish into `media.*`, so together they populate one namespace from
  three independent processes.
- Declaring the capability on `@mesh.tool` keeps the full tool contract in your
  hands — tags, version, and dependencies live right next to the capability.

## Consumer side: one typed view

```python
@mesh.service
class MediaService:
    @mesh.selector("media.caption", required=True)
    async def caption(self, args: dict) -> dict: ...
    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...
    @mesh.selector("media.transcribe")
    async def transcribe(self, args: dict) -> dict: ...

@mesh.tool(capability="process_media", tags=["media", "gateway"])
async def process_media(assetId: str, text: str, media: MediaService = None) -> dict:
    ...  # media is the injected facade, hidden from the MCP input schema
```

The view is injected as a **tool parameter**: each method becomes a dependency
edge on `process_media`, expanded name-sorted. `caption` is `required`;
`thumbnail`/`transcribe` are optional.

## What it demonstrates

- **Per-method multi-agent resolution.** One `process_media` call fans out
  across all three methods; the combined result's `servedBy` fields name three
  different provider agents answering through one interface.
- **Independent rebinding.** Stop `thumbnail-provider` and only that method's
  edge goes away; the others keep resolving to their own agents.
- **Two refusal behaviors:**
  - a missing **required** `caption` provider → the tool returns the structured
    `dependency_unavailable` refusal BEFORE the handler runs;
  - a missing **optional** provider → the facade call raises `ToolError`, which
    the handler catches and substitutes a fallback (graceful degradation).

## Run it locally

`meshctl start` runs each agent and starts a local registry automatically if
none is running. Use four terminals (or add `--detach`):

```bash
# Terminal 1 — provider A (also starts the local registry)
meshctl start examples/python/service-view/caption-provider/main.py

# Terminal 2 — provider B
meshctl start examples/python/service-view/thumbnail-provider/main.py

# Terminal 3 — provider C
meshctl start examples/python/service-view/transcribe-provider/main.py

# Terminal 4 — the consumer/gateway
meshctl start examples/python/service-view/media-gateway/main.py
```

Once all four are healthy, call the gateway's entry-point tool:

```bash
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

Expected output — one interface, three different serving agents:

```json
{
  "assetId": "asset-1",
  "caption":    { "value": "A scene showing a cat on a sofa.",     "servedBy": "caption-provider" },
  "thumbnail":  { "value": "thumb://asset-1?w=320&h=180 (320x180)", "servedBy": "thumbnail-provider" },
  "transcript": { "value": "[asset-1] A CAT ON A SOFA [5 words]",   "servedBy": "transcribe-provider" }
}
```

You can also call any producer capability directly by its dotted name:

```bash
meshctl call media.caption '{"assetId": "asset-1", "text": "a cat on a sofa"}'
# -> {"assetId":"asset-1","caption":"A scene showing a cat on a sofa.","provider":"caption-provider"}
```

Inspect the published services and the view edges:

```bash
meshctl list --services   # media.caption / media.thumbnail / media.transcribe and their agents
```

### See graceful degradation (optional edge)

Stop one OPTIONAL provider and call again — only that method degrades. Allow a
few seconds for the consumer's next heartbeat to rebind:

```bash
meshctl stop transcribe-provider
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
# -> transcript: { "value": "(no transcript — provider offline)", "servedBy": "unavailable" }
```

### See the tool-boundary refusal (required edge)

Stop the REQUIRED `caption-provider` and call again:

```bash
meshctl stop caption-provider
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

The call is refused BEFORE the handler runs, with the structured error carried
as JSON in the tool result:

```json
{ "error": "dependency_unavailable", "capability": "media.caption" }
```

Restart the providers to return to the healthy output above.

## Cross-runtime interchangeability

Because the capabilities (`media.caption` / `media.thumbnail` /
`media.transcribe`) and their `assetId` / `text` / `width` parameters are
identical across the Java, Python, and TypeScript examples, you can mix runtimes
freely. For example, start the Java providers and this Python gateway:

```bash
# Java providers
meshctl start examples/java/service-view/caption-provider
meshctl start examples/java/service-view/thumbnail-provider
meshctl start examples/java/service-view/transcribe-provider
# Python gateway over them
meshctl start examples/python/service-view/media-gateway/main.py
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

## Documentation

- Run `meshctl man decorators` for the decorator reference.
- Run `meshctl man dependency-injection` for capability resolution and
  availability semantics.
