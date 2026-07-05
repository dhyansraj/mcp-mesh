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
| `caption-provider`    | 8110 | `media_caption`    | Provider A — captions an asset         |
| `thumbnail-provider`  | 8111 | `media_thumbnail`  | Provider B — thumbnails an asset       |
| `transcribe-provider` | 8112 | `media_transcribe` | Provider C — transcribes an asset      |
| `media-gateway`       | 8113 | `process_media`    | Consumer — one `MediaService` view     |

The consumer declares one interface aggregating all three capabilities:

```java
@McpMeshService
public interface MediaService {
    @Selector(capability = "media_caption", required = true) CaptionResult    caption(CaptionRequest req);
    @Selector(capability = "media_thumbnail")                ThumbnailResult  thumbnail(ThumbnailRequest req);
    @Selector(capability = "media_transcribe")               TranscriptResult transcribe(TranscribeRequest req);
}
```

Spring auto-discovers the interface (classpath scan under the app's package) and
registers a facade bean named `mediaService`. The gateway `@Autowired`s it and
calls the methods directly — no manual proxy wiring. `caption` is `required`;
`thumbnail` and `transcribe` are optional.

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

### See graceful degradation

Stop one optional provider and call again — only that method degrades. Allow a
few seconds for the consumer's next heartbeat to rebind before the degraded
call; an immediate call can still hit the old provider proxy and succeed:

```bash
meshctl stop transcribe-provider
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
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

Each agent directory also ships the full scaffolded file set (`Dockerfile`,
`helm-values.yaml`, etc.) for Docker/Kubernetes deployment — see
`meshctl man deployment`.

## Documentation

- Run `meshctl man decorators --java` for the decorator reference.
- Run `meshctl man dependency-injection` for capability resolution, tags, and
  availability semantics.
