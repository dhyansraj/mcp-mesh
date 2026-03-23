# Media Storage (TypeScript)

> Store, retrieve, and return binary media from mesh tools

## Overview

MCP Mesh includes a pluggable media storage system for tools that produce or consume binary content — images, PDFs, audio, documents. Media is stored in a configurable backend (local filesystem or S3) and referenced via URIs. Tools return media as MCP `resource_link` objects that LLMs can resolve.

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

Lazy-loads `@aws-sdk/client-s3` — only needed when S3 backend is configured.

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
// Returns: "file:///tmp/mcp-mesh-media/media/chart.png"
```

| Parameter  | Type     | Description                 |
| ---------- | -------- | --------------------------- |
| `data`     | `Buffer` | Raw binary content          |
| `filename` | `string` | Filename (used in URI path) |
| `mimeType` | `string` | MIME type                   |

Returns: URI string.

## Returning Media from Tools

### mediaResult() — URI to ResourceLink

```typescript
import { mediaResult, uploadMedia } from "@mcpmesh/sdk";

agent.addTool({
  name: "generate_chart",
  capability: "chart_gen",
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }) => {
    const pngBuffer = renderChart(query);
    const uri = await uploadMedia(pngBuffer, "chart.png", "image/png");
    return mediaResult(
      uri,
      "Sales Chart",
      "image/png",
      "Q3 revenue",
      pngBuffer.length,
    );
  },
});
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
  "Q3 chart",
);
```

Or use the class form:

```typescript
import { MediaResult } from "@mcpmesh/sdk";

const result = new MediaResult(
  pngBuffer,
  "chart.png",
  "image/png",
  "Sales Chart",
);
const link = await result.toResourceLink();
```

## Web Framework Helpers

### saveUpload() — Express/Multer File Upload

Compatible with multer's file format:

```typescript
import { saveUpload } from "@mcpmesh/sdk";
import multer from "multer";

const upload = multer({ storage: multer.memoryStorage() });

app.post("/upload", upload.single("file"), async (req, res) => {
  const uri = await saveUpload(req.file);
  res.json({ uri });
});
```

### saveUploadResult() — Full Metadata

```typescript
import { saveUploadResult } from "@mcpmesh/sdk";

const result = await saveUploadResult(req.file);
// result.uri, result.name, result.mimeType, result.size
```

Returns: `MediaUploadResult { uri, name, mimeType, size }`.

## See Also

- `meshctl man multimodal --typescript` - LLM media resolution and media option
- `meshctl man environment` - All environment variables
- `meshctl man api --typescript` - Express integration
