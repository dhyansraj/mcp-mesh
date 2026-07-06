# caption-provider

Provider A in the [service-view example](../README.md).

## Overview

A TypeScript MCP Mesh agent. Publishes the `media.caption` capability via **producer
sugar**: `agent.addService("media", { ... })` publishes one method as the dotted
capability `media.caption` — no per-method `addTool`.

The `media.*` capability + its parameters match the Java and Python providers
exactly, so gateways in ANY runtime are interchangeable.

## Setup

```bash
cd examples/typescript/service-view/caption-provider
npm install
```

## Build (type-check)

```bash
npm run build      # tsc
```

## Run

```bash
npx tsx index.ts
```

Or with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/typescript/service-view/caption-provider/index.ts
```

The agent listens on port 8130.

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
