# claude-provider

A MCP Mesh LLM provider generated using `meshctl scaffold`.

## Overview

This is a zero-code LLM provider that exposes anthropic/claude-sonnet-4-5 to other MCP Mesh agents.

## Getting Started

### Prerequisites

- Python 3.9+
- MCP Mesh SDK
- FastMCP
- LiteLLM
- ANTHROPIC_API_KEY environment variable

### Installation

```bash
pip install -r requirements.txt
```

### Environment Variables

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

### Running the Provider

```bash
meshctl start main.py
```

Or with debug logging:

```bash
meshctl start main.py --debug
```

The provider will start on port 8090 by default.

## Configuration

| Parameter | Value                       | Description              |
| --------- | --------------------------- | ------------------------ |
| Model     | anthropic/claude-sonnet-4-5 | LiteLLM model identifier |
| Port      | 8090                        | HTTP server port         |
| Tags      | llm, claude                 | Discovery tags           |

## How It Works

This provider uses the `@mesh.llm_provider` decorator to automatically:

1. Create a `process_chat` function that handles LLM requests
2. Wrap LiteLLM with error handling and retries
3. Register with the mesh network for discovery
4. Handle tool calling and streaming responses

## Using This Provider

Other agents can use this provider with the `@mesh.llm` decorator:

```python
@mesh.llm(
    provider={"capability": "llm", "tags": ["llm","claude"]},
    max_iterations=1,
    system_prompt="You are a helpful assistant.",
    context_param="ctx",
)
@mesh.tool(...)
def my_llm_tool(ctx: MyContext, llm: mesh.MeshLlmAgent = None):
    return llm("Process this request")
```

## Project Structure

```
claude-provider/
├── __init__.py       # Package init
├── __main__.py       # Module entry point
├── main.py           # Provider implementation
├── README.md         # This file
└── requirements.txt  # Python dependencies
```

## Health Check

The provider includes a health check that validates:

- ANTHROPIC_API_KEY is set
- Anthropic API is reachable

Health status is cached for 30 seconds.

## License

MIT
