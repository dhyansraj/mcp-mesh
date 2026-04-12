# chat-history-agent

A MCP Mesh agent generated for the Day 6 tutorial.

## Overview

Redis-backed chat history agent that stores and retrieves conversation turns. Other agents call it through mesh dependency injection like any other tool.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- Redis running on localhost:6379

### Installation

```bash
pip install -r requirements.txt
```

### Running the Agent

```bash
meshctl start main.py
```

Or with debug logging:

```bash
meshctl start main.py --debug
```

The agent will start on port 9109 by default.

## Available Tools

| Tool | Capability | Description |
|------|------------|-------------|
| `save_turn` | `chat_history` | Save a conversation turn to Redis |
| `get_history` | `chat_history` | Retrieve recent conversation turns |

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- Run `meshctl man decorators` for decorator reference

## License

MIT
