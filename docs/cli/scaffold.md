# meshctl scaffold

> Generate MCP Mesh agent code from templates

## Usage

```bash
meshctl scaffold [options]
```

## Options

| Option             | Description                  | Default       |
| ------------------ | ---------------------------- | ------------- |
| `--name`           | Agent name                   | (interactive) |
| `--agent-type`     | Agent type                   | (interactive) |
| `--lang`           | Language: python, typescript | python        |
| `--port`           | HTTP port                    | 9000          |
| `--output`         | Output directory             | .             |
| `--dry-run`        | Preview without creating     | false         |
| `--no-interactive` | Disable prompts              | false         |

## Agent Types

| Type           | Description            |
| -------------- | ---------------------- |
| `tool`         | Basic capability agent |
| `llm-agent`    | LLM-powered agent      |
| `llm-provider` | Zero-code LLM provider |

## Examples

### Interactive Mode

```bash
meshctl scaffold
```

Prompts:

```
? Agent name: my-agent
? Agent type: tool
? Language: python
? HTTP port: 9000

✅ Created my-agent/
   ├── my_agent.py
   ├── requirements.txt
   └── README.md
```

### Non-Interactive

```bash
meshctl scaffold --name my-agent --agent-type tool --no-interactive
```

### TypeScript Agent

```bash
meshctl scaffold --name my-agent --agent-type tool --lang typescript
```

### LLM Agent

```bash
meshctl scaffold --name ai-agent --agent-type llm-agent --llm-selector claude
```

### LLM Provider

```bash
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5
```

### Preview (Dry Run)

```bash
meshctl scaffold --name my-agent --agent-type tool --dry-run
```

Output:

```python
# Preview: my_agent.py

import mesh
from fastmcp import FastMCP

app = FastMCP("My Agent")

@app.tool()
@mesh.tool(capability="my_capability")
def my_tool() -> str:
    """Tool description."""
    return "Hello from my-agent!"

@mesh.agent(name="my-agent", http_port=9000, auto_run=True)
class MyAgent:
    pass
```

## Adding Tools

Add tools to existing agents:

```bash
# Add basic tool
meshctl scaffold --name my-agent --add-tool new_function --tool-type mesh.tool

# Add LLM tool
meshctl scaffold --name my-agent --add-tool smart_function --tool-type mesh.llm
```

## Docker Compose Generation

Generate docker-compose.yml for agents:

```bash
# Basic compose
meshctl scaffold --compose

# With observability (Redis, Tempo, Grafana)
meshctl scaffold --compose --observability

# Custom project name
meshctl scaffold --compose --project-name my-project
```

## LLM Agent Options

| Option            | Description              |
| ----------------- | ------------------------ |
| `--llm-selector`  | Provider: claude, openai |
| `--filter`        | Tool filter JSON         |
| `--system-prompt` | System prompt file       |

### Filter Examples

```bash
# Filter by capability
meshctl scaffold --name analyzer --agent-type llm-agent \
  --filter '[{"capability": "calculator"}]'

# Filter by tags
meshctl scaffold --name analyzer --agent-type llm-agent \
  --filter '[{"tags": ["tools"]}]'
```

## LLM Provider Options

| Option    | Description          |
| --------- | -------------------- |
| `--model` | LiteLLM model string |
| `--tags`  | Provider tags        |

### Model Examples

```bash
# Claude Sonnet
meshctl scaffold --agent-type llm-provider --model anthropic/claude-sonnet-4-5

# OpenAI GPT-4
meshctl scaffold --agent-type llm-provider --model openai/gpt-4o

# Ollama
meshctl scaffold --agent-type llm-provider --model ollama/llama3
```

## Output Structure

### Python Agent

```
my-agent/
├── my_agent.py        # Agent code
├── requirements.txt   # Dependencies
├── .env.example       # Environment template
└── README.md          # Documentation
```

### TypeScript Agent

```
my-agent/
├── src/
│   └── index.ts       # Agent code
├── package.json       # Dependencies
├── tsconfig.json      # TypeScript config
├── .env.example       # Environment template
└── README.md          # Documentation
```

## See Also

- [start](start.md) - Start agents
- [Python Decorators](../python/decorators.md) - Python API
- [TypeScript Functions](../typescript/mesh-functions.md) - TypeScript API
