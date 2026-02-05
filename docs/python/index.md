# Python SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See the <a href="../../java/">Java SDK</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See the <a href="../../typescript/">TypeScript SDK</a></span>
</div>

> Build distributed MCP agents with Python decorators and zero boilerplate

## Overview

The MCP Mesh Python SDK provides a decorator-based API for building distributed agent systems. Combined with FastMCP, you get:

- **`@mesh.tool`** - Register capabilities with dependency injection
- **`@mesh.agent`** - Configure agent servers with auto-run
- **`@mesh.llm`** - LLM-powered tools with automatic tool discovery
- **`@mesh.llm_provider`** - Zero-code LLM providers via LiteLLM
- **`@mesh.route`** - FastAPI routes with mesh DI

## Installation

```bash
# Install the SDK
pip install mcp-mesh

# Install the CLI (required for development)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart

# Or scaffold a new agent
meshctl scaffold --name my-agent
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list              # List all topics
meshctl man <topic>             # View a topic
meshctl man <topic> --raw       # Get markdown output (LLM-friendly)
```

## Key Topics

| Topic | Command | Description |
|-------|---------|-------------|
| Quick Start | `meshctl man quickstart` | Get started in minutes |
| Decorators | `meshctl man decorators` | @mesh.tool, @mesh.agent, @mesh.llm |
| Dependency Injection | `meshctl man di` | How DI works |
| LLM Integration | `meshctl man llm` | Build AI-powered agents |
| Deployment | `meshctl man deployment` | Local, Docker, Kubernetes |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Decorators Reference</h3>
  <p>Complete API reference for all decorators</p>
  <a href="decorators/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
