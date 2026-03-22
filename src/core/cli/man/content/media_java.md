# Media Storage (Java/Spring Boot)

> Store, retrieve, and return binary media from mesh tools

## Overview

MCP Mesh includes a pluggable media storage system for Java/Spring Boot tools that produce or consume binary content. Media is stored in a configurable backend (local filesystem or S3) and referenced via URIs. Tools return media as MCP `resource_link` objects that LLMs can resolve.

## Storage Backends

Configure via Spring Boot properties or environment variables.

### Local Filesystem (Default)

```yaml
mesh:
  media:
    storage: local
    storagePath: /tmp/mcp-mesh-media
    storagePrefix: media/
```

### S3 / S3-Compatible

```yaml
mesh:
  media:
    storage: s3
    storageBucket: mcp-mesh-media
    storageEndpoint: http://localhost:9000 # MinIO
    storagePrefix: media/
```

## Configuration Properties

| Property                     | Default               | Description                |
| ---------------------------- | --------------------- | -------------------------- |
| `mesh.media.storage`         | `local`               | Backend: `local` or `s3`   |
| `mesh.media.storagePath`     | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `mesh.media.storageBucket`   | (none)                | S3 bucket name             |
| `mesh.media.storageEndpoint` | (none)                | S3-compatible endpoint URL |
| `mesh.media.storagePrefix`   | `media/`              | Key/directory prefix       |

Auto-configured via `MediaStoreAutoConfiguration` — a `MediaStore` bean is created automatically based on properties.

## Returning Media from Tools

### MeshMedia.mediaResult() — Bytes to ResourceLink

Upload bytes and create a ResourceLink in one step:

```java
import io.mcpmesh.spring.media.MeshMedia;
import io.mcpmesh.spring.media.MediaStore;
import io.modelcontextprotocol.spec.McpSchema.ResourceLink;

@MeshTool(capability = "chart_gen", description = "Generate a chart")
public ResourceLink generateChart(
    @Param("query") String query,
    MediaStore mediaStore  // Auto-injected
) {
    byte[] png = renderChart(query);
    return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
}
```

With optional name and description:

```java
return MeshMedia.mediaResult(
    png, "chart.png", "image/png",
    "Sales Chart", "Q3 revenue chart",
    mediaStore
);
```

### MeshMedia.mediaResult() — URI to ResourceLink

Create a ResourceLink from an existing URI:

```java
String uri = mediaStore.upload(pngBytes, "chart.png", "image/png");
ResourceLink link = MeshMedia.mediaResult(uri, "Sales Chart", "image/png");
// Or with description and size:
ResourceLink link = MeshMedia.mediaResult(
    uri, "Sales Chart", "image/png", "Q3 chart", (long) pngBytes.length
);
```

## Web Framework Helpers

### saveUpload() — Spring MultipartFile

Save a Spring `MultipartFile` directly to media storage:

```java
import org.springframework.web.multipart.MultipartFile;
import io.mcpmesh.spring.media.MeshMedia;

@PostMapping("/upload")
public Map<String, String> upload(
    @RequestParam("file") MultipartFile file,
    MediaStore mediaStore
) {
    String uri = MeshMedia.saveUpload(file, mediaStore);
    return Map.of("uri", uri);
}
```

### saveUploadResult() — Full Metadata

```java
MediaUploadResult result = MeshMedia.saveUploadResult(file, mediaStore);
// result.uri(), result.name(), result.mimeType(), result.size()
```

Returns: `MediaUploadResult(String uri, String name, String mimeType, long size)`.

## MediaStore Interface

For direct low-level access:

```java
public interface MediaStore {
    String upload(byte[] data, String filename, String mimeType);
    MediaFetchResult fetch(String uri);
    boolean exists(String uri);
}

public record MediaFetchResult(byte[] data, String mimeType) {}
```

Inject `MediaStore` as a Spring bean into your components:

```java
@Autowired
private MediaStore mediaStore;
```

## See Also

- `meshctl man multimodal --java` - LLM media resolution and @MediaParam
- `meshctl man decorators --java` - All annotations reference
- `meshctl man api --java` - Spring Boot integration
