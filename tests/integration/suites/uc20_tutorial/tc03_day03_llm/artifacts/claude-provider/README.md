# claude-provider

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner Claude LLM provider (Day 3). Wraps the Claude API as a zero-code mesh LLM capability.

## Prerequisites

- Python 3.11+
- MCP Mesh SDK
- `ANTHROPIC_API_KEY` environment variable set

## Running the Agent

```bash
meshctl start main.py
```

## Available Capabilities

| Capability | Tags | Description |
|------------|------|-------------|
| `llm` | `claude` | Claude LLM provider via mesh delegation |

## License

MIT
