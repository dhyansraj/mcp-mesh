# ts-basic

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
ts-basic/
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
docker build -t ts-basic:latest .

# Run the container
docker run -p 8080:8080 ts-basic:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install ts-basic oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/ts-basic \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [TypeScript SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/typescript)
- Run `meshctl man decorators --typescript` for decorator reference
