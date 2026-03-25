# MediaStore Configuration

MediaStore handles where media bytes are saved. For local development, the defaults work -- no configuration needed. Configure storage explicitly when deploying to Docker, Kubernetes, or any environment where agents run on different machines.

Two backends are available:

| Backend             | Best For                    | URI Format                                   |
| ------------------- | --------------------------- | -------------------------------------------- |
| **Local** (default) | Development, single-machine | `file:///tmp/mcp-mesh-media/media/chart.png` |
| **S3**              | Production, multi-agent     | `s3://mcp-mesh-media/media/chart.png`        |

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

| Variable                          | Default               | Description                |
| --------------------------------- | --------------------- | -------------------------- |
| `MCP_MESH_MEDIA_STORAGE`          | `local`               | Backend: `local` or `s3`   |
| `MCP_MESH_MEDIA_STORAGE_PATH`     | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `MCP_MESH_MEDIA_STORAGE_BUCKET`   | `mcp-mesh-media`      | S3 bucket name             |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | _(none)_              | S3-compatible endpoint URL |
| `MCP_MESH_MEDIA_STORAGE_PREFIX`   | `media/`              | Key/directory prefix       |

## Distributed Deployment

In multi-agent deployments (Docker, Kubernetes), local filesystem storage does not work across containers. A `file:///tmp/...` URI produced by one container is inaccessible to another. Use S3 or MinIO for any deployment where agents run in separate processes or containers.

### Which Agents Need S3 Config?

| Agent Role                          | Needs S3?              | Why                                                            |
| ----------------------------------- | ---------------------- | -------------------------------------------------------------- |
| **Producer** (uploads media)        | Yes -- WRITE           | Calls `upload_media()` / `MediaResult`                         |
| **LLM Provider** (resolves media)   | Yes -- READ            | Fetches `resource_link` URIs to show the LLM the image         |
| **Router / Consumer** (passes URIs) | Optional               | Just passes URI strings through -- no MediaStore access needed |
| **Expert** (receives URI params)    | Only if using `media=` | Needs READ access if it passes media to its own LLM call       |

### MinIO for Local Development

```yaml
# docker-compose.yml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001" # Console UI
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin

  createbucket:
    image: minio/mc
    depends_on: [minio]
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin;
      mc mb local/mcp-mesh-media --ignore-existing;
      "
```

### Kubernetes

Add the following environment variables to every agent deployment that needs media access:

```yaml
env:
  - name: MCP_MESH_MEDIA_STORAGE
    value: "s3"
  - name: MCP_MESH_MEDIA_STORAGE_BUCKET
    value: "mcp-mesh-media"
  - name: MCP_MESH_MEDIA_STORAGE_ENDPOINT
    value: "http://minio:9000"
  - name: AWS_ACCESS_KEY_ID
    valueFrom:
      secretKeyRef:
        name: minio-credentials
        key: access-key
  - name: AWS_SECRET_ACCESS_KEY
    valueFrom:
      secretKeyRef:
        name: minio-credentials
        key: secret-key
```

## Security

- **Path traversal protection** -- Local storage validates all paths against directory traversal attacks
- **S3 credentials** -- Use IAM roles or environment variables; never hardcode
- **Storage isolation** -- Each deployment's media is isolated by the configured prefix

## See Also

- [Returning Media](returning-media.md) — How to upload and return media from tools
- [Environment Variables](../environment-variables.md) — Full configuration reference
