# Web Framework Uploads

> Save uploaded files from FastAPI, Express, and Spring Boot directly to MediaStore.

## Overview

When building web APIs that accept file uploads, use `save_upload()` to store files in MediaStore. This gives you a URI that can be passed to mesh tools and LLM agents.

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

| Parameter | Type | Description |
| --- | --- | --- |
| `upload` | `UploadFile` | FastAPI upload object |
| `filename` | `str \| None` | Override filename |
| `mime_type` | `str \| None` | Override MIME type |

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

## See Also

- [MediaStore Configuration](media-store.md) -- Storage backends
- [Returning Media](returning-media.md) -- MediaResult for tool responses
