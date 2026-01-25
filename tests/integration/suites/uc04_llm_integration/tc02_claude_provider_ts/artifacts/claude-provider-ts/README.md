# claude-provider-ts

MCP Mesh LLM provider for anthropic/claude-sonnet-4-5.

## Quick Start

```bash
# Set API key
export ANTHROPIC_API_KEY=your-key

# Install dependencies
npm install

# Run the provider
npm start
```

## How It Works

This provider uses `mesh.llmProvider()` which:

- Wraps the anthropic/claude-sonnet-4-5 model using Vercel AI SDK
- Registers with mesh for other agents to discover
- Provides health checks for API connectivity
- Handles rate limiting and error recovery

## Using This Provider

Other agents can use this provider via `mesh.llm()`:

```typescript
server.addTool(
  mesh.llm({
    name: "my_tool",
    provider: { capability: "llm", tags: ["claude"] },
    // ... rest of config
  }),
);
```

## Docker

```bash
docker build -t claude-provider-ts:latest .
docker run -p 9000:9000 \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  claude-provider-ts:latest
```

## Kubernetes

Create a secret first:

```bash
kubectl create secret generic llm-secrets \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY
```

Then deploy:

```bash
helm install claude-provider-ts oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent -f helm-values.yaml
```

## Documentation

- Run `meshctl man llm` for LLM integration guide
- Run `meshctl man decorators --typescript` for decorator reference
