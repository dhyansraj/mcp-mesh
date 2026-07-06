# media-gateway

The consumer in the [service-view example](../README.md). Declares one typed
service view aggregating three `media.*` capabilities and exposes a
`process_media` tool that fans a request out across all three view methods —
each served by a different provider agent.

## Overview

A TypeScript MCP Mesh agent. `mesh.serviceView(...)` sits in the tool's
`dependencies` array and expands into three edges:

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
  dependencies: [Media],
  execute: async ({ assetId, text }, media: unknown) =>
    combine(media as MeshServiceFacade<typeof Media>, assetId, text),
});
```

`caption` is `required` (missing provider → structured `dependency_unavailable`
refusal before the handler runs); `thumbnail`/`transcribe` are optional and
throw when unresolved, which the handler catches for graceful degradation.

## Setup

From the repo root, install this agent's dependencies:

```bash
npm --prefix examples/typescript/service-view/media-gateway install
```

## Build (type-check)

```bash
npm --prefix examples/typescript/service-view/media-gateway run build   # tsc
```

## Run

Start with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/typescript/service-view/media-gateway/index.ts
```

Then, with the three providers running:

```bash
meshctl call process_media '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

The agent listens on port 8133.

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
