# TypeScript SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See the <a href="../../python/">Python SDK</a></span>
</div>

> Build distributed MCP agents with TypeScript and zero boilerplate

## Overview

The MCP Mesh TypeScript SDK provides a function-based API for building distributed agent systems:

- **`mesh()`** - Wrap FastMCP with mesh capabilities
- **`agent.addTool()`** - Register tools with capabilities and tags
- **`mesh.llm()`** - Create LLM-powered tools
- **`agent.addLlmProvider()`** - Zero-code LLM providers

## Installation

```bash
# Install the SDK
npm install @mcpmesh/sdk

# Install the CLI (if not already installed)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart --typescript

# Or scaffold a new agent
meshctl scaffold --name my-agent --lang typescript
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list                      # List all topics
meshctl man <topic> --typescript        # View TypeScript version
meshctl man <topic> --typescript --raw  # Get markdown output
```

## Key Topics

| Topic                | Command                               | Description                   |
| -------------------- | ------------------------------------- | ----------------------------- |
| Quick Start          | `meshctl man quickstart --typescript` | Get started in minutes        |
| Mesh Functions       | `meshctl man decorators --typescript` | mesh(), addTool(), mesh.llm() |
| Dependency Injection | `meshctl man di --typescript`         | How DI works                  |
| LLM Integration      | `meshctl man llm --typescript`        | Build AI-powered agents       |
| Deployment           | `meshctl man deployment --typescript` | Local, Docker, Kubernetes     |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Mesh Functions Reference</h3>
  <p>Complete API reference</p>
  <a href="mesh-functions/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
