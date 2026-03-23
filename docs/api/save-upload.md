# save_upload

> Save web framework file uploads directly to MediaStore.

## Python (FastAPI)

### `mesh.save_upload()`

```python
uri = await mesh.save_upload(upload, filename=None, mime_type=None)
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `upload` | `UploadFile` | Yes | FastAPI upload object |
| `filename` | `str` | No | Override filename |
| `mime_type` | `str` | No | Override MIME type |

**Returns**: URI string.

### `mesh.save_upload_result()`

```python
result = await mesh.save_upload_result(upload)
```

**Returns**: `MediaUpload(uri, name, mime_type, size)`.

---

## TypeScript (Express/Multer)

### `saveUpload()`

```typescript
import { saveUpload } from "@mcpmesh/sdk";

const uri = await saveUpload(file, options?);
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | multer `File` or `{ data, name, mimeType }` | Yes | Upload object |
| `options.filename` | `string` | No | Override filename |
| `options.mimeType` | `string` | No | Override MIME type |

**Returns**: URI string.

### `saveUploadResult()`

```typescript
import { saveUploadResult } from "@mcpmesh/sdk";

const result = await saveUploadResult(file);
// { uri, name, mimeType, size }
```

**Returns**: `MediaUploadResult`.

---

## Java (Spring Boot)

### `MeshMedia.saveUpload()`

```java
import io.mcpmesh.spring.media.MeshMedia;

String uri = MeshMedia.saveUpload(file, mediaStore);
String uri = MeshMedia.saveUpload(file, mediaStore, filename, mimeType);
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | `MultipartFile` | Yes | Spring upload object |
| `mediaStore` | `MediaStore` | Yes | Injected storage bean |
| `filename` | `String` | No | Override filename |
| `mimeType` | `String` | No | Override MIME type |

### `MeshMedia.saveUploadResult()`

```java
MediaUploadResult result = MeshMedia.saveUploadResult(file, mediaStore);
// result.uri(), result.name(), result.mimeType(), result.size()
```

**Returns**: `MediaUploadResult(String uri, String name, String mimeType, long size)`.

## See Also

- [Web Uploads Guide](../multimodal/web-uploads.md) -- End-to-end examples
- [MediaStore](media-store.md) -- Storage configuration
