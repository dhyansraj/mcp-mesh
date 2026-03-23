# MediaStore Configuration

> Configure where media files are stored — local filesystem or S3-compatible storage.

## Overview

MediaStore is the storage abstraction behind all multimodal operations. When a tool uploads media via `upload_media()` or `MediaResult`, it goes to the configured MediaStore. When an LLM needs to resolve a `resource_link`, it fetches from the same store.

Two backends are available:

| Backend | Best For | URI Format |
| --- | --- | --- |
| **Local** (default) | Development, single-machine | `file:///tmp/mcp-mesh-media/media/chart.png` |
| **S3** | Production, multi-agent | `s3://mcp-mesh-media/media/chart.png` |

## Local Filesystem (Default)

No configuration needed for development. Files are stored at `/tmp/mcp-mesh-media/media/` by default.

```bash
# Optional — customize the path
export MCP_MESH_MEDIA_STORAGE=local
export MCP_MESH_MEDIA_STORAGE_PATH=/var/lib/mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
```

!!! tip "Shared Storage for Multi-Agent"
    When running multiple agents locally, they all share the same filesystem, so local storage works out of the box. In Docker or Kubernetes, use S3 or a shared volume.

## S3 / S3-Compatible (Production)

For production deployments with MinIO, AWS S3, or any S3-compatible service:

=== "Environment Variables"

    ```bash
    export MCP_MESH_MEDIA_STORAGE=s3
    export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
    export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://minio:9000  # omit for AWS
    export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
    # Standard AWS credentials
    export AWS_ACCESS_KEY_ID=minioadmin
    export AWS_SECRET_ACCESS_KEY=minioadmin
    ```

=== "Java (application.yml)"

    ```yaml
    mesh:
      media:
        storage: s3
        storageBucket: mcp-mesh-media
        storageEndpoint: http://minio:9000
        storagePrefix: media/
    ```

=== "Docker Compose (MinIO)"

    ```yaml
    services:
      minio:
        image: minio/minio:latest
        command: server /data --console-address ":9001"
        ports:
          - "9000:9000"
          - "9001:9001"
        environment:
          MINIO_ROOT_USER: minioadmin
          MINIO_ROOT_PASSWORD: minioadmin
    ```

### S3 Dependencies

=== "Python"

    ```bash
    pip install boto3
    ```

=== "TypeScript"

    ```bash
    npm install @aws-sdk/client-s3
    ```

    The SDK lazy-loads `@aws-sdk/client-s3` only when the S3 backend is configured.

=== "Java"

    S3 client is included in `mcp-mesh-spring-boot-starter`. No additional dependency needed.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_MESH_MEDIA_STORAGE` | `local` | Backend: `local` or `s3` |
| `MCP_MESH_MEDIA_STORAGE_PATH` | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `MCP_MESH_MEDIA_STORAGE_BUCKET` | `mcp-mesh-media` | S3 bucket name |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | _(none)_ | S3-compatible endpoint URL |
| `MCP_MESH_MEDIA_STORAGE_PREFIX` | `media/` | Key/directory prefix |

## Security

- **Path traversal protection** — Local storage validates all paths against directory traversal attacks
- **S3 credentials** — Use IAM roles or environment variables; never hardcode
- **Storage isolation** — Each deployment's media is isolated by the configured prefix

## See Also

- [Returning Media](returning-media.md) — How to upload and return media from tools
- [Environment Variables](../environment-variables.md) — Full configuration reference
