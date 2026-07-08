# Service View Example — `mesh.serviceView` (RFC #1280, TypeScript)

**Three methods, three different provider agents, one typed interface.**

This is the TypeScript sibling of
[`examples/java/service-view`](../../java/service-view) and
[`examples/python/service-view`](../../python/service-view). All three tell the
same story with the **same `media.*` capabilities**, so the agents are
**cross-runtime interchangeable** — a TypeScript gateway can consume the Java or
Python providers, and vice versa.

A service view aggregates several ordinary capability dependencies behind one
typed facade. Each method binds a single capability, and calling it delegates to
that capability's own resolved proxy — so different methods resolve to
**different provider agents** and rebind independently as topology changes.

## Agents

| Agent                 | Port | Capability         | Role                                   |
|-----------------------|------|--------------------|----------------------------------------|
| `caption-provider`    | 8130 | `media.caption`    | Provider A — captions an asset         |
| `thumbnail-provider`  | 8131 | `media.thumbnail`  | Provider B — thumbnails an asset       |
| `transcribe-provider` | 8132 | `media.transcribe` | Provider C — transcribes an asset      |
| `media-gateway`       | 8133 | `process_media`    | Consumer — one service view            |

## Producer side: publish each dotted capability explicitly

Each provider declares its dotted capability with an ordinary
`agent.addTool({ capability: "media.<method>", ... })`.

```ts
agent.addTool({
  name: "caption",
  capability: "media.caption",   // dotted name is user-chosen; nothing is hard-coded
  parameters: z.object({ assetId: z.string(), text: z.string() }),
  execute: async (args) => {
    const { assetId, text } = args as { assetId: string; text: string };
    return {
      assetId,
      caption: `A scene showing ${text.trim().toLowerCase()}.`,
      provider: "caption-provider",
    };
  },
});
```

- **Dotted capability names are first-class** across the stack — the
  registry and the Java/Python/TypeScript runtimes all accept segment-wise names
  like `media.caption`.
- **The namespace is yours.** All three agents publish under `media.*`, so
  together they populate one namespace from three independent processes.
- Declaring each tool explicitly lets it carry its own `tags`, `version`, and
  `dependencies` — a producer-side capability is just a normal mesh tool.

## Consumer side: one typed view

```ts
const Media = mesh.serviceView({
  methods: {
    caption: { capability: "media.caption", required: true },
    thumbnail: "media.thumbnail",
    transcribe: "media.transcribe",
  },
});

agent.addTool({
  name: "process_media",
  parameters: z.object({ assetId: z.string(), text: z.string() }),
  dependencies: [Media],   // ONE slot, expands into three name-sorted edges
  execute: async ({ assetId, text }, media: unknown) =>
    combine(media as MeshServiceFacade<typeof Media>, assetId, text),
});
```

The `serviceView` occupies one positional slot in `dependencies` but expands
into a dependency edge per method. `caption` is `required`;
`thumbnail`/`transcribe` are optional. The facade is injected at that slot.

## What it demonstrates

- **Per-method multi-agent resolution.** One `process_media` call fans out
  across all three methods; the combined result's `servedBy` fields name three
  different provider agents answering through one interface.
- **Independent rebinding.** Stop `thumbnail-provider` and only that method's
  edge goes away; the others keep resolving to their own agents.
- **Two refusal behaviors:**
  - a missing **required** `caption` provider → the tool returns the structured
    `dependency_unavailable` refusal BEFORE the handler runs;
  - a missing **optional** provider → the facade call throws, which the handler
    catches and substitutes a fallback (graceful degradation).

## Build

Each agent is a standalone TypeScript project (mirrors the sibling TS examples):

```bash
cd examples/typescript/service-view/caption-provider
npm install
npm run build      # tsc — type-checks against the local @mcpmesh/sdk
```

## Run it locally

`meshctl start` runs each agent (via `tsx`) and starts a local registry
automatically if none is running. Use four terminals (or add `--detach`):

```bash
# Terminal 1 — provider A (also starts the local registry)
meshctl start examples/typescript/service-view/caption-provider/index.ts

# Terminal 2 — provider B
meshctl start examples/typescript/service-view/thumbnail-provider/index.ts

# Terminal 3 — provider C
meshctl start examples/typescript/service-view/transcribe-provider/index.ts

# Terminal 4 — the consumer/gateway
meshctl start examples/typescript/service-view/media-gateway/index.ts
```

Once all four are healthy:

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

Call a producer capability directly by its dotted name, and inspect the mesh:

```bash
meshctl call media.caption '{"assetId": "asset-1", "text": "a cat on a sofa"}'
meshctl list --services   # media.caption / media.thumbnail / media.transcribe and their agents
```

### See graceful degradation (optional edge)

```bash
meshctl stop transcribe-provider
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
# -> transcript: { "value": "(no transcript — provider offline)", "servedBy": "unavailable" }
```

### See the tool-boundary refusal (required edge)

```bash
meshctl stop caption-provider
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
# refused before the handler runs:
# { "error": "dependency_unavailable", "capability": "media.caption" }
```

Restart the providers to return to the healthy output above.

## Cross-runtime interchangeability

The capabilities (`media.caption` / `media.thumbnail` / `media.transcribe`) and
their `assetId` / `text` / `width` parameters are identical across the Java,
Python, and TypeScript examples, so you can mix runtimes freely — e.g. run the
Python providers and this TypeScript gateway, or vice versa.

## Documentation

- Run `meshctl man decorators` for the decorator reference.
- Run `meshctl man dependency-injection` for capability resolution and
  availability semantics.
