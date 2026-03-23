# MediaStore

> Storage abstraction for binary media content.

## Interface

=== "Python"

    ```python
    class MediaStore:
        async def upload(self, data: bytes, filename: str, mime_type: str) -> str: ...
        async def fetch(self, uri: str) -> tuple[bytes, str]: ...
        async def exists(self, uri: str) -> bool: ...
    ```

=== "TypeScript"

    ```typescript
    interface MediaStore {
      upload(data: Buffer, filename: string, mimeType: string): Promise<string>;
      fetch(uri: string): Promise<{ data: Buffer; mimeType: string }>;
      exists(uri: string): Promise<boolean>;
    }
    ```

=== "Java"

    ```java
    public interface MediaStore {
        String upload(byte[] data, String filename, String mimeType);
        MediaFetchResult fetch(String uri);
        boolean exists(String uri);
    }

    public record MediaFetchResult(byte[] data, String mimeType) {}
    ```

## Implementations

### LocalMediaStore

Default backend. Stores files on the local filesystem.

| Config | Default | Description |
| --- | --- | --- |
| `MCP_MESH_MEDIA_STORAGE_PATH` | `/tmp/mcp-mesh-media` | Base directory |
| `MCP_MESH_MEDIA_STORAGE_PREFIX` | `media/` | Subdirectory prefix |

URI format: `file:///path/to/file`

### S3MediaStore

Production backend for S3-compatible storage (AWS S3, MinIO).

| Config | Default | Description |
| --- | --- | --- |
| `MCP_MESH_MEDIA_STORAGE_BUCKET` | `mcp-mesh-media` | Bucket name |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | _(none)_ | Custom endpoint URL |
| `MCP_MESH_MEDIA_STORAGE_PREFIX` | `media/` | Key prefix |

URI format: `s3://bucket/prefix/filename`

## Factory

=== "Python"

    ```python
    from _mcp_mesh.media.media_store import get_media_store

    store = get_media_store()  # singleton based on MCP_MESH_MEDIA_STORAGE
    ```

=== "TypeScript"

    ```typescript
    import { getMediaStore } from "@mcpmesh/sdk";

    const store = getMediaStore();
    ```

=== "Java"

    ```java
    @Autowired
    private MediaStore mediaStore;  // auto-configured bean
    ```

Backend selected by `MCP_MESH_MEDIA_STORAGE` environment variable (`local` or `s3`).

## See Also

- [MediaStore Configuration](../multimodal/media-store.md) -- Full setup guide
- [Environment Variables](../environment-variables.md) -- All config options
