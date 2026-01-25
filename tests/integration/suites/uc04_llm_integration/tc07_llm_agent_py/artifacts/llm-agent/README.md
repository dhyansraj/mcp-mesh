# llm-agent

A MCP Mesh LLM agent generated using `meshctl scaffold`.

## Overview

This is an LLM-powered MCP Mesh agent that uses Claude for processing.

## Getting Started

### Prerequisites

- Python 3.11+
- MCP Mesh SDK
- FastMCP
- An LLM provider agent running (e.g., claude-provider or openai-provider)

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

The agent will start on port 9000 by default.

## Configuration

| Parameter       | Value  | Description                     |
| --------------- | ------ | ------------------------------- |
| LLM Provider    | claude | Provider used for LLM calls     |
| Max Iterations  | 1      | Maximum agentic loop iterations |
| Response Format | text   | Output format (text/json)       |
| Context Param   | ctx    | Parameter name for context      |

## Available Tools

| Tool        | Capability  | Description             |
| ----------- | ----------- | ----------------------- |
| `llm_agent` | `llm_agent` | Process input using LLM |

## Project Structure

```
llm-agent/
├── __init__.py       # Package init
├── __main__.py       # Module entry point
├── main.py           # Agent implementation
├── README.md         # This file
└── requirements.txt  # Python dependencies
```

## Customizing the Agent

### Modifying the Context

Edit the `LlmAgentContext` class to add fields needed for your use case:

```python
class LlmAgentContext(BaseModel):
    input_text: str = Field(..., description="Input text")
    user_id: str = Field(..., description="User identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Changing the System Prompt

Modify the `SYSTEM_PROMPT` constant in `main.py` to change LLM behavior.

### Switching LLM Provider

Change the `provider` tags in the `@mesh.llm` decorator:

```python
@mesh.llm(
    provider={"capability": "llm", "tags": ["llm", "+claude"]},  # For Claude
    # or
    provider={"capability": "llm", "tags": ["llm", "+gpt"]},     # For OpenAI
    ...
)
```

## License

MIT
