# Media Storage (TypeScript)

> Store, retrieve, and return binary media from mesh tools
> Full guide: https://mcp-mesh.ai/multimodal/

## Storage Backends

### Local Filesystem (Default)

```bash
export MCP_MESH_MEDIA_STORAGE=local
export MCP_MESH_MEDIA_STORAGE_PATH=/tmp/mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
```

### S3 / S3-Compatible

```bash
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000
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

## Uploading Media

```typescript
import { uploadMedia } from "@mcpmesh/sdk";
const uri = await uploadMedia(pngBuffer, "chart.png", "image/png");
```

| Parameter  | Type     | Description                 |
| ---------- | -------- | --------------------------- |
| `data`     | `Buffer` | Raw binary content          |
| `filename` | `string` | Filename (used in URI path) |
| `mimeType` | `string` | MIME type                   |

Returns: URI string.

## Downloading Media

```typescript
import { downloadMedia } from "@mcpmesh/sdk";
const { data, mimeType } = await downloadMedia(
  "s3://mcp-mesh-media/media/chart.png",
);
```

| Parameter | Type     | Description           |
| --------- | -------- | --------------------- |
| `uri`     | `string` | Media URI from upload |

Returns: `{ data: Buffer, mimeType: string }`.

## Returning Media from Tools

### mediaResult() — URI to ResourceLink

```typescript
const uri = await uploadMedia(pngBuffer, "chart.png", "image/png");
return mediaResult(
  uri,
  "Sales Chart",
  "image/png",
  "Q3 revenue",
  pngBuffer.length,
);
```

| Parameter     | Type      | Description          |
| ------------- | --------- | -------------------- |
| `uri`         | `string`  | Media URI            |
| `name`        | `string`  | Display name         |
| `mimeType`    | `string`  | MIME type            |
| `description` | `string?` | Optional description |
| `size`        | `number?` | Optional file size   |

Returns: MCP `ResourceLink`.

### createMediaResult() — Upload + Link in One Step

```typescript
import { createMediaResult } from "@mcpmesh/sdk";
const link = await createMediaResult(
  pngBuffer,
  "chart.png",
  "image/png",
  "Sales Chart",
);
```

## Web Framework Helpers

### saveUpload() — Express/Multer File Upload

```typescript
import { saveUpload } from "@mcpmesh/sdk";
const uri = await saveUpload(req.file); // multer file object
```

### saveUploadResult() — Full Metadata

```typescript
const result = await saveUploadResult(req.file);
// result.uri, result.name, result.mimeType, result.size
```

Returns: `MediaUploadResult { uri, name, mimeType, size }`.

## See Also

- `meshctl man multimodal --typescript` - LLM media resolution and media option
- `meshctl man environment` - All environment variables
- `meshctl man api --typescript` - Express integration
