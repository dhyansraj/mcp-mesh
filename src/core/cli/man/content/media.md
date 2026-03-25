# Media Storage

> Store, retrieve, and return binary media (images, PDFs, files) from mesh tools
> Full guide: https://mcp-mesh.ai/multimodal/

## Storage Backends

### Local Filesystem (Default)

```bash
export MCP_MESH_MEDIA_STORAGE=local          # default
export MCP_MESH_MEDIA_STORAGE_PATH=/tmp/mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/   # subdirectory prefix
```

### S3 / S3-Compatible

```bash
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000  # MinIO
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
```

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

```python
from mcp_mesh import mesh

uri = await mesh.upload_media(png_bytes, "chart.png", "image/png")
```

| Parameter   | Type    | Description                     |
| ----------- | ------- | ------------------------------- |
| `data`      | `bytes` | Raw binary content              |
| `filename`  | `str`   | Filename (used in URI path)     |
| `mime_type` | `str`   | MIME type (e.g., `"image/png"`) |

Returns: URI string (`file://...` or `s3://...`).

## Returning Media from Tools

### media_result() — URI to ResourceLink

```python
uri = await mesh.upload_media(png_bytes, "chart.png", "image/png")
return mesh.media_result(uri=uri, name="Sales Chart", mime_type="image/png")
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

```python
return await mesh.MediaResult(
    data=png_bytes, filename="chart.png", mime_type="image/png", name="Sales Chart",
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

```python
uri = await mesh.save_upload(file)  # FastAPI UploadFile
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
# result.uri, result.name, result.mime_type, result.size
```

Returns: `MediaUpload(uri, name, mime_type, size)`.

## Resource Link Format

```json
{
  "type": "resource_link",
  "uri": "file:///tmp/mcp-mesh-media/media/chart.png",
  "name": "Sales Chart",
  "mimeType": "image/png",
  "_meta": { "size": 45678 }
}
```

## Distributed Deployment

> For distributed deployment and S3 configuration, see https://mcp-mesh.ai/multimodal/media-store/

## Security

- **Path traversal protection**: Local storage validates all paths against directory traversal
- **S3 credentials**: Use IAM roles or environment variables — never hardcode credentials

## See Also

- `meshctl man multimodal` - LLM media resolution and media= parameter
- `meshctl man environment` - All environment variables
- `meshctl man api` - Web framework integration
