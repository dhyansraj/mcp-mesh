# Service View Example — `@McpMeshService` (RFC #1280)

**Three methods, three different provider agents, one typed interface.**

A service view is a consumer-owned interface that aggregates several ordinary
capability dependencies behind one typed facade. Each abstract method binds a
single capability via a method-level `@Selector`, and calling that method
delegates to the capability's own resolved proxy — so different methods resolve
to **different provider agents** and rebind independently as the mesh topology
changes. The group is a typed view; the capability remains the atom.

## Agents

| Agent                 | Port | Capability         | Role                                   |
|-----------------------|------|--------------------|----------------------------------------|
| `caption-provider`    | 8110 | `media.caption`    | Provider A — captions an asset         |
| `thumbnail-provider`  | 8111 | `media.thumbnail`  | Provider B — thumbnails an asset       |
| `transcribe-provider` | 8112 | `media.transcribe` | Provider C — transcribes an asset      |
| `media-gateway`       | 8113 | `process_media`, `process_media_strict` | Consumer — one `MediaService` view, consumed two ways |

Each provider publishes ONE slice of the shared, dotted `media.*` namespace, and
the consumer aggregates all three behind one typed interface.

## Producer side: publish a service, not N tools

Each provider is a producer-sugar bean: a class annotated
`@McpMeshService("media")` publishes each of its public methods as a mesh tool
under the capability `media.<methodName>` — no per-method `@MeshTool` needed.

```java
@Component
@McpMeshService("media")            // prefix is entirely user-chosen; nothing is hard-coded in the mesh
public class MediaCaptionService {
    public CaptionResult caption(@Param("assetId") String assetId,   // → capability "media.caption"
                                 @Param("text") String text) { ... }
}
```

- **Dotted capability names are first-class** across the stack — registry,
  Python, and Java validators all accept segment-wise names like `media.caption`.
  The published capability is simply `prefix + "." + methodName`.
- **The prefix is yours.** `"media"` carries no special meaning; pick any
  segment-wise name (e.g. `"media.v2"`). The three agents here all use `"media"`,
  so together they populate one namespace from three independent processes.
- **Methods are published name-sorted**, and an explicit `@MeshTool` on a method
  still WINS — reach for it only when a method needs custom `tags`, `version`, or
  `description`; the sugar intentionally uses annotation defaults otherwise.

The consumer declares one interface aggregating all three capabilities:

```java
@McpMeshService
public interface MediaService {
    @Selector(capability = "media.caption", required = true) CaptionResult    caption(CaptionRequest req);
    @Selector(capability = "media.thumbnail")                ThumbnailResult  thumbnail(ThumbnailRequest req);
    @Selector(capability = "media.transcribe")               TranscriptResult transcribe(TranscribeRequest req);
}
```

Spring auto-discovers the interface (classpath scan under the app's package) and
registers a facade bean named `mediaService`. The gateway `@Autowired`s it and
calls the methods directly — no manual proxy wiring. `caption` is `required`;
`thumbnail` and `transcribe` are optional.

> Note the symmetry: the same `@McpMeshService` annotation marks a producer
> (on a `@Component` CLASS, with a prefix) and a consumer view (on an INTERFACE,
> no prefix). A blank prefix is valid only on the interface form.

## What it demonstrates

- **Per-method multi-agent resolution.** One `process_media` call fans out
  across all three view methods; the combined result's `servedBy` fields name
  three different provider agents — `caption-provider`, `thumbnail-provider`,
  `transcribe-provider` — answering through one interface.
- **Independent rebinding.** Stop `thumbnail-provider` and only that method's
  edge goes away; `caption` and `transcribe` keep resolving to their own agents.
- **Graceful degradation.** The optional methods throw
  `MeshToolUnavailableException` when their provider is absent; the gateway
  catches it and substitutes a fallback, exactly as the feature intends. The
  `required` `caption` edge is expected to always resolve.

## Two ways to consume a service view

The gateway exposes the SAME fan-out logic through two tools, one per
consumption style:

| Tool                    | View injected as        | Scope        | Missing REQUIRED `caption` provider                                                   | View edges in `meshctl list` |
|-------------------------|-------------------------|--------------|--------------------------------------------------------------------------------------|------------------------------|
| `process_media`         | constructor bean (phase 1) | app-wide  | handler runs, then the `caption(...)` call throws `MeshToolUnavailableException`      | none of its own (deduped)    |
| `process_media_strict`  | `@MeshTool` parameter (phase 2) | tool-scoped | tool returns the structured `dependency_unavailable` refusal **before** the handler runs | yes — 3 edges on this tool   |

> Both tools share the SAME `MediaService` interface, so the three capabilities
> register **once**, not twice. The bean path's synthetic carrier dedupes against
> `process_media_strict`'s tool-declared edges (the tool-declared edge wins), so
> `meshctl list` shows three view edges total — on `process_media_strict` — not
> six. Had no tool consumed the view, the bean path would register those three on
> its own synthetic carrier instead.

```java
// Phase 1 — bean: app-wide facade, no tool-boundary refusal
@MeshTool(capability = "process_media")
public Map<String, Object> processMedia(@Param("assetId") String assetId,
                                        @Param("text") String text) {
    return combine(this.media, assetId, text);        // this.media is @Autowired
}

// Phase 2 — tool parameter: view methods become dependency edges ON THIS TOOL,
// positionally after any explicit @Selector deps; required edges gate the tool.
@MeshTool(capability = "process_media_strict")
public Map<String, Object> processStrict(@Param("assetId") String assetId,
                                         @Param("text") String text,
                                         MediaService media) {   // NOT @Param
    return combine(media, assetId, text);
}
```

Because `caption` is `required = true`, the tool-parameter form gets a
tool-boundary pre-invoke guard: the mesh refuses the call with a structured
error the instant the caption edge is unresolved, so the handler body never runs
with a missing required dependency. The bean form has no such boundary — the
view is app-wide and a missing required capability only surfaces as an exception
mid-handler.

## Method rules (recap)

- Every abstract method carries `@Selector` with a non-empty `capability`.
- Parameters follow the `@MeshTool` convention: 0 params → no-arg call; exactly
  one unannotated POJO/record param → single-object conversion (used here);
  otherwise every param needs `@Param("name")`.
- Return `T` (sync), `CompletableFuture<T>` (async), or
  `Flow.Publisher<String>` (streaming).
- Optional `@McpMeshService(minAvailable = N)` adds an availability floor: below
  `N` resolvable methods, every facade call throws
  `MeshServiceUnavailableException`.

## Run it locally

`meshctl start` runs each Maven agent and starts a local registry automatically
if none is running. Use four terminals (or add `--detach`):

```bash
# Terminal 1 — provider A (also starts the local registry)
meshctl start examples/java/service-view/caption-provider

# Terminal 2 — provider B
meshctl start examples/java/service-view/thumbnail-provider

# Terminal 3 — provider C
meshctl start examples/java/service-view/transcribe-provider

# Terminal 4 — the consumer/gateway
meshctl start examples/java/service-view/media-gateway
```

Once all four are healthy, call either entry-point tool — both fan out across
all three providers and return the same shape:

```bash
meshctl call process_media        '{"assetId": "asset-1", "text": "a cat on a sofa"}'
meshctl call process_media_strict '{"assetId": "asset-1", "text": "a cat on a sofa"}'
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

`process_media_strict` also lists the three view edges as its own dependencies:

```bash
meshctl list   # media-gateway's process_media_strict shows media.caption, media.thumbnail, media.transcribe
```

The three producer capabilities also render as one grouped service — the
per-method view: one `media` service, three methods, three different provider
agents:

```bash
meshctl list --services
```

```
SERVICE  METHOD      AGENT                STATUS
------------------------------------------------------------------
media    caption     caption-provider     available
media    thumbnail   thumbnail-provider   available
media    transcribe  transcribe-provider  available
```

You can also call any producer capability directly by its dotted name —
`meshctl call` matches the capability name as-is:

```bash
meshctl call media.caption '{"assetId": "asset-1", "text": "a cat on a sofa"}'
# -> {"assetId":"asset-1","caption":"A scene showing a cat on a sofa.","provider":"caption-provider"}
```

### See graceful degradation (optional edge)

Stop one OPTIONAL provider and call again — only that method degrades, in BOTH
tools. Allow a few seconds for the consumer's next heartbeat to rebind before
the degraded call; an immediate call can still hit the old provider proxy and
succeed:

```bash
meshctl stop transcribe-provider
meshctl call process_media_strict '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

```json
{
  "assetId": "asset-1",
  "caption":    { "value": "A scene showing a cat on a sofa.",     "servedBy": "caption-provider" },
  "thumbnail":  { "value": "thumb://asset-1?w=320&h=180 (320x180)", "servedBy": "thumbnail-provider" },
  "transcript": { "value": "(no transcript — provider offline)",    "servedBy": "unavailable" }
}
```

The `caption` and `thumbnail` methods still resolve to their own agents — proof
that each view method is an independent dependency edge.

### See the tool-boundary refusal (required edge)

Now stop the REQUIRED `caption-provider` and contrast the two consumption
styles:

```bash
meshctl stop caption-provider

# Phase 2 — tool parameter: refused BEFORE the handler runs, with a structured error
meshctl call process_media_strict '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

The call comes back as an MCP error result — `isError: true`, with the structured
refusal as JSON escaped inside `content[0].text`:

```json
{
  "content": [
    { "type": "text", "text": "{\"error\": \"dependency_unavailable\", \"capability\": \"media.caption\"}" }
  ],
  "isError": true
}
```

```bash
# Phase 1 — bean: no tool-boundary gate; the handler runs and the required
# caption call throws MeshToolUnavailableException, surfacing as a plain tool error
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

Only the tool-parameter form (`process_media_strict`) turns a missing REQUIRED
view method into a clean, structured pre-invoke refusal — the guarantee the
tool-parameter form adds.
Restart `caption-provider` (and `transcribe-provider`) to return to the healthy
output above.

Each agent directory also ships the full scaffolded file set (`Dockerfile`,
`helm-values.yaml`, etc.) for Docker/Kubernetes deployment — see
`meshctl man deployment`.

## Documentation

- Run `meshctl man decorators --java` for the decorator reference.
- Run `meshctl man dependency-injection` for capability resolution, tags, and
  availability semantics.
