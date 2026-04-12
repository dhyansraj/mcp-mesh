# openai-provider

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

TripPlanner OpenAI LLM provider (Day 4). Wraps the OpenAI API as a zero-code mesh LLM capability.

## Prerequisites

- Python 3.11+
- MCP Mesh SDK
- `OPENAI_API_KEY` environment variable set

## Running the Agent

```bash
meshctl start main.py
```

## Available Capabilities

| Capability | Tags | Description |
|------------|------|-------------|
| `llm` | `openai`, `gpt` | OpenAI LLM provider via mesh delegation |

## License

MIT
