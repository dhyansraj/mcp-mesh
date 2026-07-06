# thumbnail-provider

Provider B in the [`@McpMeshService` service-view example](../README.md). Publishes
the `media.thumbnail` capability, bound by the OPTIONAL
`MediaService.thumbnail(...)` view method in the `media-gateway` consumer — stop
this agent to see the gateway degrade gracefully.

## Overview

A Java/Spring Boot MCP Mesh agent. Turns an asset id + width into a deterministic
thumbnail descriptor.

The capability is published with producer sugar: `MediaThumbnailService` is a
`@Component` annotated `@McpMeshService("media")`, so its public `thumbnail(...)`
method is exposed as the dotted capability `media.thumbnail` — no per-method
`@MeshTool` required.

## Getting Started

### Prerequisites

- Java 17+
- Maven 3.9+
- MCP Mesh SDK

### Running the Agent

```bash
mvn spring-boot:run
```

Or with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/java/service-view/thumbnail-provider
```

The agent will start on port 8111 by default.

## Project Structure

```text
thumbnail-provider/
├── pom.xml
├── Dockerfile
├── helm-values.yaml
└── src/main/java/com/example/thumbnailprovider/
    ├── ThumbnailProviderApplication.java  # agent bootstrap
    └── MediaThumbnailService.java         # @McpMeshService("media") producer bean
```

## Docker

```bash
# Build the image
docker build -t thumbnail-provider:latest .

# Run the container
docker run -p 8111:8111 thumbnail-provider:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install thumbnail-provider oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/thumbnail-provider \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Java SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/java)
- Run `meshctl man decorators --java` for decorator reference

## License

MIT
