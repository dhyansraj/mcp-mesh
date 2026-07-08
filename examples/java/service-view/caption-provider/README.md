# caption-provider

Provider A in the [`@MeshService` service-view example](../README.md). Publishes
the `media.caption` capability, bound by `MediaService.caption(...)` in the
`media-gateway` consumer.

## Overview

A Java/Spring Boot MCP Mesh agent. Turns an asset id + source text into a
deterministic caption.

The capability is published by an ordinary `@Component`: `MediaCaptionService`'s
`caption(...)` method carries `@MeshTool(capability = "media.caption")`, so the
dotted capability name is declared explicitly on the annotation.

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
meshctl start examples/java/service-view/caption-provider
```

The agent will start on port 8110 by default.

## Project Structure

```text
caption-provider/
├── pom.xml
├── Dockerfile
├── helm-values.yaml
└── src/main/java/com/example/captionprovider/
    ├── CaptionProviderApplication.java  # agent bootstrap
    └── MediaCaptionService.java         # @MeshTool(capability = "media.caption")
```

## Docker

```bash
# Build the image
docker build -t caption-provider:latest .

# Run the container
docker run -p 8110:8110 caption-provider:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install caption-provider oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/caption-provider \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Java SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/java)
- Run `meshctl man decorators --java` for decorator reference

## License

MIT
