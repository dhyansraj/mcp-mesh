# meshctl scaffold Command Reference

> Generate MCP Mesh agents from templates with interactive or CLI-based configuration

## Overview

The `meshctl scaffold` command generates new MCP Mesh agents from templates. It supports three agent types, multiple input modes, and extensive customization options.

## Quick Start

```bash
# Interactive mode - guided wizard
meshctl scaffold

# Generate a basic tool agent
meshctl scaffold --name my-tool --agent-type tool

# Generate an LLM-powered agent
meshctl scaffold --name my-agent --agent-type llm-agent

# Generate an LLM provider
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5
```

## Agent Types

### 1. Tool Agent (`--agent-type tool`)

Basic MCP tool agent using `@mesh.tool` decorator. Best for simple tools and utilities.

```bash
meshctl scaffold --name date-service --agent-type tool --port 9100
```

**Generated structure:**

```
date-service/
├── __init__.py
├── __main__.py
├── main.py           # Agent with @mesh.tool decorated functions
├── README.md
└── requirements.txt
```

### 2. LLM Agent (`--agent-type llm-agent`)

LLM-powered agent using `@mesh.llm` + `@mesh.tool` decorators. Best for AI-driven processing.

```bash
meshctl scaffold --name emotion-analyzer --agent-type llm-agent \
  --llm-selector claude \
  --response-format json \
  --max-iterations 1
```

**Generated structure:**

```
emotion-analyzer/
├── __init__.py
├── __main__.py
├── main.py           # Agent with @mesh.llm decorator
├── prompts/          # Jinja2 prompt templates
│   └── emotion-analyzer.jinja2
├── README.md
└── requirements.txt
```

### 3. LLM Provider (`--agent-type llm-provider`)

Zero-code LLM provider using `@mesh.llm_provider` decorator. Exposes LLM access to other agents.

```bash
meshctl scaffold --name claude-provider --agent-type llm-provider \
  --model anthropic/claude-sonnet-4-5 \
  --port 9110
```

**Generated structure:**

```
claude-provider/
├── __init__.py
├── __main__.py
├── main.py           # Provider with @mesh.llm_provider decorator
├── README.md
└── requirements.txt
```

## Input Modes

### Interactive Mode (Default)

When no flags are provided, scaffold launches an interactive wizard:

```bash
meshctl scaffold
```

The wizard guides you through:

1. Agent type selection
2. Name and description
3. Port configuration
4. LLM-specific options (provider, filter, response format)

### CLI Flags Mode

Specify all options via command-line flags:

```bash
meshctl scaffold \
  --name my-agent \
  --agent-type llm-agent \
  --llm-selector openai \
  --filter '{"tags":["executor","tools"]}' \
  --filter-mode all \
  --max-iterations 3 \
  --response-format json \
  --port 9200
```

### YAML Config Mode

Use a configuration file for complex setups:

```bash
meshctl scaffold --config agent-config.yaml
```

**Example `agent-config.yaml`:**

```yaml
agent_type: llm-agent
name: document-processor
description: Process and analyze documents using LLM
port: 9200

llm:
  provider: claude
  provider_tags: ["llm", "+claude"]
  max_iterations: 5
  system_prompt: "file://prompts/document.jinja2"
  context_param: doc_ctx
  response_format: json
  filter:
    - capability: pdf_extractor
    - tags: ["document", "parser"]
  filter_mode: all

tags:
  - document
  - analysis
  - llm
```

## Common Options

### General Options

| Flag               | Short | Default  | Description                                     |
| ------------------ | ----- | -------- | ----------------------------------------------- |
| `--name`           | `-n`  |          | Agent name (required)                           |
| `--agent-type`     |       | `tool`   | Agent type: `tool`, `llm-agent`, `llm-provider` |
| `--description`    |       |          | Agent description                               |
| `--port`           | `-p`  | `9000`   | HTTP server port                                |
| `--output`         | `-o`  | `.`      | Output directory                                |
| `--lang`           | `-l`  | `python` | Language: `python`                              |
| `--tags`           |       |          | Tags for discovery (comma-separated)            |
| `--no-interactive` |       | `false`  | Disable interactive mode                        |

### LLM Agent Options

| Flag                | Default  | Description                             |
| ------------------- | -------- | --------------------------------------- |
| `--llm-selector`    | `claude` | LLM provider: `claude`, `openai`        |
| `--max-iterations`  | `1`      | Max agentic loop iterations             |
| `--system-prompt`   |          | System prompt (inline or `file://path`) |
| `--context-param`   | `ctx`    | Context parameter name                  |
| `--response-format` | `text`   | Response format: `text`, `json`         |
| `--filter`          |          | Tool filter (JSON format)               |
| `--filter-mode`     | `all`    | Filter mode: `all`, `best_match`, `*`   |

### LLM Provider Options

| Flag      | Default | Description                                         |
| --------- | ------- | --------------------------------------------------- |
| `--model` |         | LiteLLM model (e.g., `anthropic/claude-sonnet-4-5`) |

## Tool Filter Configuration

The `--filter` flag controls which mesh tools the LLM agent can access.

### Filter Formats

```bash
# Simple capability filter
--filter 'date_service'

# Tag-based filter
--filter '{"tags":["executor","tools"]}'

# Capability + tags filter
--filter '{"capability":"document","tags":["pdf","advanced"]}'

# Multiple filters (array)
--filter '[{"capability":"date_service"},{"tags":["system"]}]'
```

### Filter Modes

| Mode         | Description                                    |
| ------------ | ---------------------------------------------- |
| `all`        | Include all tools matching any filter criteria |
| `best_match` | One tool per capability (best tag match)       |
| `*`          | All available tools in mesh (wildcard)         |

### Examples

```bash
# Access all tools with "executor" tag
meshctl scaffold --name dev-agent --agent-type llm-agent \
  --filter '{"tags":["executor","tools"]}' \
  --filter-mode all

# Access specific capabilities
meshctl scaffold --name multi-agent --agent-type llm-agent \
  --filter '[{"capability":"date_service"},{"capability":"weather"}]'

# Access ALL mesh tools (wildcard)
meshctl scaffold --name super-agent --agent-type llm-agent \
  --filter-mode '*'

# No tool access (LLM-only, no tool calling)
meshctl scaffold --name chat-agent --agent-type llm-agent
```

## System Prompt Configuration

### Inline Prompt

```bash
meshctl scaffold --name my-agent --agent-type llm-agent \
  --system-prompt "You are a helpful assistant that processes user requests."
```

### File-based Prompt (Jinja2)

```bash
meshctl scaffold --name my-agent --agent-type llm-agent \
  --system-prompt "file://prompts/my-agent.jinja2"
```

When using file-based prompts, context fields are available directly in the template:

```jinja2
{# prompts/my-agent.jinja2 #}
You are {{ agent_name }}, an AI assistant.

## Input
{{ input_text }}

## Instructions
Analyze the input and respond appropriately.
```

**Note:** Context fields are accessed directly (e.g., `{{ input_text }}`), not via the context parameter (e.g., ~~`{{ ctx.input_text }}`~~).

## Complete Examples

### 1. Basic Tool Agent

```bash
meshctl scaffold \
  --name date-service \
  --agent-type tool \
  --description "Provides date and time utilities" \
  --port 9100 \
  --tags "date,time,utility"
```

### 2. LLM Agent with Claude

```bash
meshctl scaffold \
  --name sentiment-analyzer \
  --agent-type llm-agent \
  --description "Analyze sentiment of text using Claude" \
  --llm-selector claude \
  --response-format json \
  --max-iterations 1 \
  --port 9200
```

### 3. LLM Agent with Tool Access

```bash
meshctl scaffold \
  --name developer-agent \
  --agent-type llm-agent \
  --llm-selector claude \
  --filter '{"tags":["executor","tools"]}' \
  --filter-mode all \
  --max-iterations 10 \
  --port 9300
```

### 4. OpenAI LLM Provider

```bash
meshctl scaffold \
  --name openai-provider \
  --agent-type llm-provider \
  --model openai/gpt-4o \
  --port 9110 \
  --tags "llm,openai,gpt,provider"
```

### 5. Claude LLM Provider

```bash
meshctl scaffold \
  --name claude-provider \
  --agent-type llm-provider \
  --model anthropic/claude-sonnet-4-5 \
  --port 9111
```

## Running Generated Agents

After scaffolding, start your agent with:

```bash
cd my-agent
meshctl start main.py

# Or with debug logging
meshctl start main.py --debug
```

## Project Structure Reference

### Tool Agent

```
my-tool/
├── __init__.py       # Package initialization
├── __main__.py       # Module entry point
├── main.py           # @mesh.tool decorated functions
├── README.md         # Documentation
└── requirements.txt  # Dependencies
```

### LLM Agent

```
my-llm-agent/
├── __init__.py
├── __main__.py
├── main.py           # @mesh.llm + @mesh.tool decorated function
├── prompts/
│   └── my-llm-agent.jinja2  # Jinja2 system prompt
├── README.md
└── requirements.txt
```

### LLM Provider

```
my-provider/
├── __init__.py
├── __main__.py
├── main.py           # @mesh.llm_provider decorated function
├── README.md
└── requirements.txt
```

## Troubleshooting

### Common Issues

**"name is required" error**

```bash
# Use --no-interactive when scripting
meshctl scaffold --name my-agent --agent-type tool --no-interactive
```

**Invalid filter format**

```bash
# Ensure JSON is properly quoted
meshctl scaffold --name my-agent --agent-type llm-agent \
  --filter '{"tags":["a","b"]}'  # Correct
```

**Template not found**

```bash
# Check template directory
meshctl scaffold --list-modes  # Shows available modes and templates
```

## See Also

- [meshctl CLI Reference](./meshctl-cli.md) - All meshctl commands
- [MCP Mesh Decorators](./mesh-decorators.md) - @mesh.tool, @mesh.llm, @mesh.llm_provider
- [LLM Integration](./01-getting-started/06-llm-integration.md) - Using LLM agents
