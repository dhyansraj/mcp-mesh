# openai-provider-ts

MCP Mesh LLM provider for openai/gpt-4o.

## Quick Start

```bash
# Set API key
export OPENAI_API_KEY=your-key

# Install dependencies
npm install

# Run the provider
npm start
```

## How It Works

This provider uses `mesh.llmProvider()` which:

- Wraps the openai/gpt-4o model using Vercel AI SDK
- Registers with mesh for other agents to discover
- Provides health checks for API connectivity
- Handles rate limiting and error recovery

## Using This Provider

Other agents can use this provider via `mesh.llm()`:

```typescript
server.addTool(
  mesh.llm({
    name: "my_tool",
    provider: { capability: "llm", tags: ["gpt"] },
    // ... rest of config
  }),
);
```

## Docker

```bash
docker build -t openai-provider-ts:latest .
docker run -p 9000:9000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  openai-provider-ts:latest
```

## Kubernetes

Create a secret first:

```bash
kubectl create secret generic llm-secrets \
  --from-literal=openai-api-key=$OPENAI_API_KEY
```

Then deploy:

```bash
helm install openai-provider-ts oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent -f helm-values.yaml
```

## Documentation

- Run `meshctl man llm` for LLM integration guide
- Run `meshctl man decorators --typescript` for decorator reference
