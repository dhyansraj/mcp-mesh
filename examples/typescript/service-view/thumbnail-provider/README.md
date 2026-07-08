# thumbnail-provider

Provider B (optional edge — stop it to see graceful degradation) in the [service-view example](../README.md).

## Overview

A TypeScript MCP Mesh agent. Publishes the `media.thumbnail` capability by
declaring it **explicitly**: `agent.addTool({ capability: "media.thumbnail", ... })`.

The `media.*` capability + its parameters match the Java and Python providers
exactly, so gateways in ANY runtime are interchangeable.

## Setup

From the repo root, install this agent's dependencies:

```bash
npm --prefix examples/typescript/service-view/thumbnail-provider install
```

## Build (type-check)

```bash
npm --prefix examples/typescript/service-view/thumbnail-provider run build   # tsc
```

## Run

Start with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/typescript/service-view/thumbnail-provider/index.ts
```

The agent listens on port 8131.

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for the decorator reference

## License

MIT
