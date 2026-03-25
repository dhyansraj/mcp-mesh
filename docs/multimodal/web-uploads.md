# Web Framework Uploads

The most common way media enters the mesh is through a user upload. Use the framework helpers to receive files and store them in MediaStore.

## End-to-End Example

Upload an image via HTTP, then analyze it with an LLM:

=== "Python"

    ```python
    @app.post("/analyze")
    async def analyze_upload(file: UploadFile, question: str):
        uri = await mesh.save_upload(file)
        result = await call_tool("image_analyzer", {
            "question": question,
            "image": uri,
        })
        return {"analysis": result}
    ```

=== "TypeScript"

    ```typescript
    app.post("/analyze", upload.single("file"), async (req, res) => {
      const uri = await saveUpload(req.file);
      const result = await callTool("image_analyzer", {
        question: req.body.question,
        image: uri,
      });
      res.json({ analysis: result });
    });
    ```

## FastAPI (Python)

```python
from fastapi import UploadFile
import mesh

@app.post("/upload")
async def upload(file: UploadFile):
    uri = await mesh.save_upload(file)
    return {"uri": uri}
```

### With Full Metadata

```python
result = await mesh.save_upload_result(file)
# result.uri = "file:///tmp/mcp-mesh-media/media/photo.jpg"
# result.name = "photo.jpg"
# result.mime_type = "image/jpeg"
# result.size = 12345
```

### Parameters

| Parameter   | Type          | Description           |
| ----------- | ------------- | --------------------- |
| `upload`    | `UploadFile`  | FastAPI upload object |
| `filename`  | `str \| None` | Override filename     |
| `mime_type` | `str \| None` | Override MIME type    |

## Express (TypeScript)

Using multer for file uploads:

```typescript
import { saveUpload, saveUploadResult } from "@mcpmesh/sdk";
import multer from "multer";

const upload = multer({ storage: multer.memoryStorage() });

app.post("/upload", upload.single("file"), async (req, res) => {
  const uri = await saveUpload(req.file);
  res.json({ uri });
});
```

### With Full Metadata

```typescript
const result = await saveUploadResult(req.file);
// result.uri, result.name, result.mimeType, result.size
```

## Spring Boot (Java)

```java
import org.springframework.web.multipart.MultipartFile;
import io.mcpmesh.spring.media.MeshMedia;
import io.mcpmesh.spring.media.MediaStore;

@PostMapping("/upload")
public Map<String, String> upload(
    @RequestParam("file") MultipartFile file,
    MediaStore mediaStore
) {
    String uri = MeshMedia.saveUpload(file, mediaStore);
    return Map.of("uri", uri);
}
```

### With Full Metadata

```java
MediaUploadResult result = MeshMedia.saveUploadResult(file, mediaStore);
// result.uri(), result.name(), result.mimeType(), result.size()
```

Once you have a URI from `save_upload()`, pass it to tools via `MediaParam` or directly via the `media=` parameter. See [Returning Media](returning-media.md) for the reverse direction -- producing media from tools.

## See Also

- [MediaStore Configuration](media-store.md) -- Storage backends
- [Returning Media](returning-media.md) -- MediaResult for tool responses
