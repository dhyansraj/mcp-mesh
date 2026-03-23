# MediaParam

> Mark tool parameters that accept media URIs.

## Python

### `mesh.MediaParam()`

```python
def MediaParam(media_type: str = "*/*") -> Annotated[Optional[str], ...]
```

Usage as a type hint on tool parameters:

```python
@mesh.tool(capability="analyzer")
async def analyze(
    question: str,
    image: mesh.MediaParam("image/*") = None,
    document: mesh.MediaParam("application/pdf") = None,
) -> str:
    ...
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `media_type` | `str` | `"*/*"` | MIME type pattern to accept |

**Effect**: Adds `x-media-type` field to the parameter's JSON schema.

### MIME Type Patterns

| Pattern | Accepts |
| --- | --- |
| `"image/*"` | PNG, JPEG, GIF, WebP |
| `"application/pdf"` | PDF documents |
| `"text/*"` | Plain text, CSV, Markdown, HTML |
| `"*/*"` | Any media type |

---

## TypeScript

### `mediaParam()`

```typescript
import { mediaParam } from "@mcpmesh/sdk";

const schema = mediaParam(mediaType?: string);
```

Returns a Zod `z.string().optional()` schema with media type annotation.

```typescript
parameters: z.object({
  question: z.string(),
  image: mediaParam("image/*"),
})
```

---

## Java

### `@MediaParam`

```java
import io.mcpmesh.MediaParam;

@MeshTool(capability = "analyzer")
public String analyze(
    @Param("question") String question,
    @MediaParam("image/*") @Param("image") String imageUri
) { ... }
```

| Element | Type | Default | Description |
| --- | --- | --- | --- |
| `value` | `String` | `"*/*"` | MIME type pattern |

**Retention**: `RUNTIME`. **Target**: `PARAMETER`.

## Generated JSON Schema

```json
{
  "image": {
    "type": "string",
    "x-media-type": "image/*",
    "description": "Media URI for this parameter (accepts media URI: image/*)"
  }
}
```

## See Also

- [MediaParam Guide](../multimodal/media-param.md) -- Usage patterns and multi-agent flow
