# MediaResult

> Upload binary data and return an MCP resource_link in one step.

## Python

### `mesh.MediaResult`

```python
result = await mesh.MediaResult(
    data=png_bytes,
    filename="chart.png",
    mime_type="image/png",
    name="Sales Chart",
    description="Q3 revenue chart",
)
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `data` | `bytes` | Yes | Raw binary content |
| `filename` | `str` | Yes | Filename for storage |
| `mime_type` | `str` | Yes | MIME type |
| `name` | `str` | No | Display name (defaults to filename) |
| `description` | `str` | No | Optional description |

**Returns**: MCP `ResourceLink` (awaitable).

### `mesh.media_result()`

Create a ResourceLink from an existing URI (no upload):

```python
link = mesh.media_result(uri, name, mime_type, description=None, size=None)
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `uri` | `str` | Yes | Media URI from `upload_media()` |
| `name` | `str` | Yes | Display name |
| `mime_type` | `str` | Yes | MIME type |
| `description` | `str` | No | Optional description |
| `size` | `int` | No | File size in bytes |

**Returns**: MCP `ResourceLink`.

### `mesh.upload_media()`

Upload raw bytes to MediaStore:

```python
uri = await mesh.upload_media(data, filename, mime_type)
```

**Returns**: URI string (`file://...` or `s3://...`).

---

## TypeScript

### `createMediaResult()`

```typescript
import { createMediaResult } from "@mcpmesh/sdk";

const link = await createMediaResult(data, filename, mimeType, name?, description?);
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `data` | `Buffer` | Yes | Raw binary content |
| `filename` | `string` | Yes | Filename for storage |
| `mimeType` | `string` | Yes | MIME type |
| `name` | `string` | No | Display name |
| `description` | `string` | No | Optional description |

**Returns**: MCP `ResourceLink`.

### `MediaResult` class

```typescript
import { MediaResult } from "@mcpmesh/sdk";

const result = new MediaResult(data, filename, mimeType, name?, description?);
const link = await result.toResourceLink();
```

### `mediaResult()`

Create a ResourceLink from an existing URI:

```typescript
import { mediaResult } from "@mcpmesh/sdk";

const link = mediaResult(uri, name, mimeType, description?, size?);
```

### `uploadMedia()`

```typescript
import { uploadMedia } from "@mcpmesh/sdk";

const uri = await uploadMedia(data, filename, mimeType);
```

---

## Java

### `MeshMedia.mediaResult()` (bytes)

```java
import io.mcpmesh.spring.media.MeshMedia;

ResourceLink link = MeshMedia.mediaResult(data, filename, mimeType, mediaStore);
ResourceLink link = MeshMedia.mediaResult(data, filename, mimeType, name, description, mediaStore);
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `data` | `byte[]` | Yes | Raw binary content |
| `filename` | `String` | Yes | Filename for storage |
| `mimeType` | `String` | Yes | MIME type |
| `mediaStore` | `MediaStore` | Yes | Injected storage bean |
| `name` | `String` | No | Display name |
| `description` | `String` | No | Optional description |

### `MeshMedia.mediaResult()` (URI)

```java
ResourceLink link = MeshMedia.mediaResult(uri, name, mimeType);
ResourceLink link = MeshMedia.mediaResult(uri, name, mimeType, description, size);
```

## See Also

- [Returning Media](../multimodal/returning-media.md) -- Usage guide
- [MediaStore](media-store.md) -- Storage interface
