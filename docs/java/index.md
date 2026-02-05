# Java SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See the <a href="../../python/">Python SDK</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See the <a href="../../typescript/">TypeScript SDK</a></span>
</div>

> Build distributed MCP agents with Java annotations and zero boilerplate

## Overview

The MCP Mesh Java SDK provides an annotation-based API for building distributed agent systems:

- **`@MeshAgent`** - Configure agent servers with auto-run
- **`@MeshTool`** - Register capabilities with dependency injection
- **`@MeshLlm`** - LLM-powered tools with automatic tool discovery
- **`@MeshLlmProvider`** - Zero-code LLM providers via LiteLLM
- **`@MeshRoute`** - Spring Boot routes with mesh DI

## Installation

```xml
<!-- Add to your pom.xml -->
<dependency>
    <groupId>io.mcpmesh</groupId>
    <artifactId>mcp-mesh</artifactId>
    <version>LATEST</version>
</dependency>
```

```bash
# Install the CLI (required for development)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart --java

# Or scaffold a new agent
meshctl scaffold --name my-agent --lang java
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list              # List all topics
meshctl man <topic> --java      # View Java version
meshctl man <topic> --java --raw  # Get markdown output (LLM-friendly)
```

## Key Topics

| Topic | Command | Description |
|-------|---------|-------------|
| Quick Start | `meshctl man quickstart --java` | Get started in minutes |
| Annotations | `meshctl man decorators --java` | @MeshTool, @MeshAgent, @MeshLlm |
| Dependency Injection | `meshctl man di --java` | How DI works |
| LLM Integration | `meshctl man llm --java` | Build AI-powered agents |
| Deployment | `meshctl man deployment --java` | Local, Docker, Kubernetes |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Annotations Reference</h3>
  <p>Complete API reference for all annotations</p>
  <a href="annotations/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
