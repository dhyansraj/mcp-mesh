# Tool Call Integration Test Agents

Contains agents for comprehensive tool call testing across SDKs.

## Agents

This test suite includes 12 agents total:

### Consumer Agents (3)

- **ts-consumer** - TypeScript consumer that calls tools from all providers
- **python-consumer** - Python consumer that calls tools from all providers
- **java-consumer** - Java consumer that calls tools from all providers

### Provider Agents (6)

- **ts-claude-provider** - TypeScript provider using Claude
- **ts-openai-provider** - TypeScript provider using OpenAI
- **python-claude-provider** - Python provider using Claude
- **python-openai-provider** - Python provider using OpenAI
- **java-claude-provider** - Java provider using Claude
- **java-openai-provider** - Java provider using OpenAI

### Tool Agents (3)

- **ts-tools** - TypeScript agent exposing test tools
- **python-tools** - Python agent exposing test tools
- **java-tools** - Java agent exposing test tools

## Usage

### Start the mesh registry

```bash
meshctl start
```

### Run all agents

```bash
cd examples/toolcalls
meshctl run .
```

### Run specific agents

```bash
meshctl run ts-consumer ts-tools
```

### Override HTTP port

Set the `MCP_MESH_HTTP_PORT` environment variable to override the default port:

```bash
MCP_MESH_HTTP_PORT=9000 meshctl start
```

## Environment Setup

Copy `.env.template` to `.env` and fill in your API keys:

```bash
cp .env.template .env
```

Then edit `.env` with your actual API keys.
