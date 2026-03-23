# Media Storage

> Store, retrieve, and return binary media (images, PDFs, files) from mesh tools

## Overview

MCP Mesh includes a pluggable media storage system for tools that produce or consume binary content — images, PDFs, audio, documents. Media is stored in a configurable backend (local filesystem or S3) and referenced via URIs. Tools return media as MCP `resource_link` objects that LLMs can resolve.

## Storage Backends

### Local Filesystem (Default)

Files stored at `MCP_MESH_MEDIA_STORAGE_PATH` (default: `/tmp/mcp-mesh-media`):

```bash
export MCP_MESH_MEDIA_STORAGE=local          # default
export MCP_MESH_MEDIA_STORAGE_PATH=/tmp/mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/   # subdirectory prefix
```

### S3 / S3-Compatible

For production or shared storage (MinIO, AWS S3):

```bash
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000  # MinIO
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
```

Requires `boto3` package. Uses standard AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).

## Environment Variables

| Variable                          | Default               | Description                |
| --------------------------------- | --------------------- | -------------------------- |
| `MCP_MESH_MEDIA_STORAGE`          | `local`               | Backend: `local` or `s3`   |
| `MCP_MESH_MEDIA_STORAGE_PATH`     | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `MCP_MESH_MEDIA_STORAGE_BUCKET`   | `mcp-mesh-media`      | S3 bucket name             |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | (none)                | S3-compatible endpoint URL |
| `MCP_MESH_MEDIA_STORAGE_PREFIX`   | `media/`              | Key/directory prefix       |
| `AWS_ACCESS_KEY_ID`               | _(none)_              | S3 access key (or IAM)     |
| `AWS_SECRET_ACCESS_KEY`           | _(none)_              | S3 secret key (or IAM)     |

## Uploading Media

Upload raw bytes and get a URI:

```python
from mcp_mesh import mesh

uri = await mesh.upload_media(png_bytes, "chart.png", "image/png")
# Returns: "file:///tmp/mcp-mesh-media/media/chart.png" (local)
# Returns: "s3://mcp-mesh-media/media/chart.png" (S3)
```

| Parameter   | Type    | Description                     |
| ----------- | ------- | ------------------------------- |
| `data`      | `bytes` | Raw binary content              |
| `filename`  | `str`   | Filename (used in URI path)     |
| `mime_type` | `str`   | MIME type (e.g., `"image/png"`) |

Returns: URI string (`file://...` or `s3://...`).

## Returning Media from Tools

### media_result() — URI to ResourceLink

Create an MCP ResourceLink from an existing URI:

```python
@mesh.tool(capability="chart_gen")
async def generate_chart(query: str) -> ResourceLink:
    png_bytes = render_chart(query)
    uri = await mesh.upload_media(png_bytes, "chart.png", "image/png")
    return mesh.media_result(
        uri=uri,
        name="Sales Chart",
        mime_type="image/png",
        description="Q3 revenue chart",
        size=len(png_bytes),
    )
```

| Parameter     | Type          | Description                     |
| ------------- | ------------- | ------------------------------- |
| `uri`         | `str`         | Media URI (from `upload_media`) |
| `name`        | `str`         | Display name                    |
| `mime_type`   | `str`         | MIME type                       |
| `description` | `str \| None` | Optional description            |
| `size`        | `int \| None` | Optional file size in bytes     |

Returns: MCP `ResourceLink` object.

### MediaResult — Upload + Link in One Step

Combines `upload_media` + `media_result` into a single awaitable:

```python
@mesh.tool(capability="chart_gen")
async def generate_chart(query: str) -> ResourceLink:
    png_bytes = render_chart(query)
    return await mesh.MediaResult(
        data=png_bytes,
        filename="chart.png",
        mime_type="image/png",
        name="Sales Chart",
        description="Quarterly revenue chart",
    )
```

| Parameter     | Type          | Description                         |
| ------------- | ------------- | ----------------------------------- |
| `data`        | `bytes`       | Raw binary content                  |
| `filename`    | `str`         | Filename for storage                |
| `mime_type`   | `str`         | MIME type                           |
| `name`        | `str \| None` | Display name (defaults to filename) |
| `description` | `str \| None` | Optional description                |

Returns: MCP `ResourceLink` (awaitable).

## Web Framework Helpers

### save_upload() — FastAPI File Upload

Save a FastAPI `UploadFile` directly to media storage:

```python
from fastapi import UploadFile
from mcp_mesh import mesh

@app.post("/upload")
async def upload(file: UploadFile):
    uri = await mesh.save_upload(file)
    # Local: "file:///tmp/mcp-mesh-media/media/photo.jpg"
    # S3:    "s3://mcp-mesh-media/media/photo.jpg"
```

| Parameter   | Type          | Description                                         |
| ----------- | ------------- | --------------------------------------------------- |
| `upload`    | `UploadFile`  | FastAPI upload object                               |
| `filename`  | `str \| None` | Override filename (default: upload's filename)      |
| `mime_type` | `str \| None` | Override MIME type (default: upload's content type) |

Returns: URI string.

### save_upload_result() — Full Metadata

```python
result = await mesh.save_upload_result(file)
# result.uri = "file:///tmp/..."
# result.name = "photo.jpg"
# result.mime_type = "image/jpeg"
# result.size = 12345
```

Returns: `MediaUpload(uri, name, mime_type, size)`.

## Resource Link Format

Tools return media as MCP `resource_link` content:

```json
{
  "type": "resource_link",
  "uri": "file:///tmp/mcp-mesh-media/media/chart.png",
  "name": "Sales Chart",
  "mimeType": "image/png",
  "description": "Q3 revenue chart",
  "_meta": { "size": 45678 }
}
```

When an LLM agent calls a tool that returns a `resource_link`, the media is automatically fetched and resolved to provider-native format. See `meshctl man multimodal` for details.

## Distributed Deployment

!!! warning "All agents that read or write media must share the same storage config"

In multi-agent deployments (Docker, Kubernetes), **local filesystem storage does not work across containers**. A `file:///tmp/...` URI from one pod is inaccessible to another.

Use S3/MinIO for any deployment where agents run in separate processes or containers:

```bash
# Set on ALL agents that produce or consume media
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://minio:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
```

### Which Agents Need S3 Config?

| Agent Role | Needs S3? | Why |
| --- | --- | --- |
| **Producer** (uploads media) | Yes — WRITE | Calls `upload_media()` / `MediaResult` |
| **LLM Provider** (resolves media) | Yes — READ | Fetches `resource_link` URIs to show LLM the image |
| **Router / Consumer** (passes URIs) | Optional | Just passes URI strings through — no MediaStore access needed |
| **Expert** (receives URI params) | Only if using `media=` | Needs READ access if it passes media to its own LLM call |

### MinIO for Local Development

```yaml
# docker-compose.yml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"  # Console UI
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

```yaml
# Add to every agent deployment that needs media access
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

- **Path traversal protection**: Local storage validates all paths against directory traversal attacks
- **S3 credentials**: Use IAM roles or environment variables — never hardcode credentials
- **Storage isolation**: Each agent's media is stored with the configured prefix

## See Also

- `meshctl man multimodal` - LLM media resolution and media= parameter
- `meshctl man environment` - All environment variables
- `meshctl man api` - Web framework integration
