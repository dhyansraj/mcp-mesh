# media-gateway

The consumer in the [`@McpMeshService` service-view example](../README.md).
Declares one typed `MediaService` interface aggregating three capabilities and
exposes two tools that fan a request out across all three view methods — each
served by a different provider agent — demonstrating BOTH consumption styles:

- `process_media` — the view is a constructor-injected Spring bean (phase 1).
- `process_media_strict` — the view is a `@MeshTool` method parameter (phase 2),
  so its methods become dependency edges on that tool and the `required`
  `caption` edge gates the tool with the structured `dependency_unavailable`
  refusal. See the [top-level README](../README.md) for the side-by-side
  contrast and demo commands.

## Overview

A Java/Spring Boot MCP Mesh agent. `MediaService` is a consumer-owned service
view:

```java
@McpMeshService
public interface MediaService {
    @Selector(capability = "media_caption", required = true) CaptionResult    caption(CaptionRequest req);
    @Selector(capability = "media_thumbnail")                ThumbnailResult  thumbnail(ThumbnailRequest req);
    @Selector(capability = "media_transcribe")               TranscriptResult transcribe(TranscribeRequest req);
}
```

Spring registers a `mediaService` facade bean automatically; the gateway
`@Autowired`s it and calls the methods directly. The optional methods are
wrapped in a `MeshToolUnavailableException` catch for graceful degradation.

## Getting Started

### Prerequisites

- Java 17+
- Maven 3.9+
- MCP Mesh SDK
- The three providers running (`caption-provider`, `thumbnail-provider`,
  `transcribe-provider`)

### Running the Agent

```bash
mvn spring-boot:run
```

Or with meshctl (starts a local registry automatically if none is running):

```bash
meshctl start examples/java/service-view/media-gateway
```

The agent will start on port 8113 by default. Then:

```bash
meshctl call process_media        '{"assetId": "asset-1", "text": "a cat on a sofa"}'
meshctl call process_media_strict '{"assetId": "asset-1", "text": "a cat on a sofa"}'
```

## Project Structure

```text
media-gateway/
├── pom.xml
├── Dockerfile
├── helm-values.yaml
└── src/main/java/com/example/mediagateway/
    ├── MediaService.java            # the @McpMeshService service view
    └── MediaGatewayApplication.java # the agent + process_media tool
```

## Docker

```bash
# Build the image
docker build -t media-gateway:latest .

# Run the container
docker run -p 8113:8113 media-gateway:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install media-gateway oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/media-gateway \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Java SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/java)
- Run `meshctl man decorators --java` for decorator reference

## License

MIT
