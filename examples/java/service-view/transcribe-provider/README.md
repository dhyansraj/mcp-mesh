# transcribe-provider

Provider C in the [`@McpMeshService` service-view example](../README.md). Publishes
the `media.transcribe` capability, bound by the OPTIONAL
`MediaService.transcribe(...)` view method in the `media-gateway` consumer.

## Overview

A Java/Spring Boot MCP Mesh agent. Turns an asset id + source text into a
deterministic transcript.

The capability is published with producer sugar: `MediaTranscribeService` is a
`@Component` annotated `@McpMeshService("media")`, so its public `transcribe(...)`
method is exposed as the dotted capability `media.transcribe` — no per-method
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
meshctl start examples/java/service-view/transcribe-provider
```

The agent will start on port 8112 by default.

## Project Structure

```text
transcribe-provider/
├── pom.xml
├── Dockerfile
├── helm-values.yaml
└── src/main/java/com/example/transcribeprovider/
    ├── TranscribeProviderApplication.java  # agent bootstrap
    └── MediaTranscribeService.java         # @McpMeshService("media") producer bean
```

## Docker

```bash
# Build the image
docker build -t transcribe-provider:latest .

# Run the container
docker run -p 8112:8112 transcribe-provider:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install transcribe-provider oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/transcribe-provider \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Java SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/java)
- Run `meshctl man decorators --java` for decorator reference

## License

MIT
