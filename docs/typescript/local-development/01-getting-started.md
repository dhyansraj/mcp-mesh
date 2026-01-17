# Getting Started (TypeScript)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/local-development/01-getting-started/">Python Getting Started</a></span>
</div>

> Install meshctl CLI to start building MCP Mesh agents with TypeScript

## Prerequisites

- **Node.js 18+** - for meshctl CLI and TypeScript runtime

## Install meshctl CLI

```bash
npm install -g @mcpmesh/cli

# Verify
meshctl --version
```

!!! info "Per-Agent Dependencies"
Unlike Python (shared `.venv`), each TypeScript agent is its own npm project. The SDK is installed per-agent via `npm install` after scaffolding.

## Next Steps

Continue to [Scaffold Agents](./02-scaffold.md) — creates a complete agent project with `package.json` and all dependencies listed.
