# caption-provider

Provider A in the [service-view example](../README.md).

## Overview

A TypeScript MCP Mesh agent. Publishes the `media.caption` capability via **producer
sugar**: `agent.addService("media", { ... })` publishes one method as the dotted
capability `media.caption` — no per-method `addTool`.

The `media.*` capability + its parameters match the Java and Python providers
exactly, so gateways in ANY runtime are interchangeable.

## Setup

From the repo root, install this agent's dependencies:

```bash
npm --prefix examples/typescript/service-view/caption-provider install
```

## Build (type-check)

```bash
npm --prefix examples/typescript/service-view/caption-provider run build   # tsc
```

## Run

Start with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/typescript/service-view/caption-provider/index.ts
```

The agent listens on port 8130.

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
