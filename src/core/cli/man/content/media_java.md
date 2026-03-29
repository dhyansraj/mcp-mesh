# Media Storage (Java/Spring Boot)

> Store, retrieve, and return binary media from mesh tools
> Full guide: https://mcp-mesh.ai/multimodal/

## Storage Backends

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

Auto-configured via `MediaStoreAutoConfiguration`.

## Downloading Media

```java
MediaFetchResult result = MeshMedia.downloadMedia("s3://mcp-mesh-media/media/chart.png", mediaStore);
byte[] data = result.data();
String mimeType = result.mimeType();
```

| Parameter | Type         | Description           |
| --------- | ------------ | --------------------- |
| `uri`     | `String`     | Media URI from upload |
| `store`   | `MediaStore` | Injected media store  |

Returns: `MediaFetchResult` with `data()` and `mimeType()`.

## Returning Media from Tools

### MeshMedia.mediaResult() — Bytes to ResourceLink

```java
byte[] png = renderChart(query);
return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
```

With optional name and description:

```java
return MeshMedia.mediaResult(
    png, "chart.png", "image/png", "Sales Chart", "Q3 revenue chart", mediaStore
);
```

### MeshMedia.mediaResult() — URI to ResourceLink

```java
String uri = mediaStore.upload(pngBytes, "chart.png", "image/png");
ResourceLink link = MeshMedia.mediaResult(uri, "Sales Chart", "image/png");
```

## Web Framework Helpers

### saveUpload() — Spring MultipartFile

```java
String uri = MeshMedia.saveUpload(file, mediaStore); // MultipartFile
```

### saveUploadResult() — Full Metadata

```java
MediaUploadResult result = MeshMedia.saveUploadResult(file, mediaStore);
// result.uri(), result.name(), result.mimeType(), result.size()
```

Returns: `MediaUploadResult(String uri, String name, String mimeType, long size)`.

## MediaStore Interface

```java
public interface MediaStore {
    String upload(byte[] data, String filename, String mimeType);
    MediaFetchResult fetch(String uri);
    boolean exists(String uri);
}
```

## See Also

- `meshctl man multimodal --java` - LLM media resolution and @MediaParam
- `meshctl man decorators --java` - All annotations reference
- `meshctl man api --java` - Spring Boot integration
