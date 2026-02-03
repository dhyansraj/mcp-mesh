# weather-tool-ts

MCP Mesh agent generated using meshctl scaffold.

## Quick Start

```bash
# Install dependencies
npm install

# Run the agent (development)
npm run dev

# Run the agent (production)
npm start
```

## Project Structure

```
weather-tool-ts/
├── src/
│   └── index.ts      # Agent implementation
├── package.json      # Dependencies
├── tsconfig.json     # TypeScript config
├── Dockerfile        # Container build
└── helm-values.yaml  # Kubernetes deployment
```

## Docker

```bash
# Build the image
docker build -t weather-tool-ts:latest .

# Run the container
docker run -p 9000:9000 weather-tool-ts:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install weather-tool-ts oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -f helm-values.yaml \
  --set image.repository=your-registry/weather-tool-ts \
  --set image.tag=v1.0.0
```

## Adding Tools

Add new tools in `src/index.ts`:

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  description: "What this tool does",
  tags: ["tools"],
  parameters: z.object({
    input: z.string().describe("Input parameter"),
  }),
  execute: async ({ input }) => {
    // Implement your tool logic
    return `Result: ${input}`;
  },
});
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [TypeScript SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/typescript)
- Run `meshctl man decorators --typescript` for decorator reference
