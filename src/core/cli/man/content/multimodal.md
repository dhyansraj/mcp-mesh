# Multimodal LLM

> Pass images, PDFs, and files to LLM agents with media= parameter

## Overview

MCP Mesh LLM agents can process images, PDFs, and other media alongside text. This works through two mechanisms:

1. **media= parameter** — Attach media directly when calling an LLM agent
2. **Resource link resolution** — LLMs automatically see media returned by tools via `resource_link`

Both mechanisms resolve media URIs from the MediaStore and convert them to provider-native formats (Claude image blocks, OpenAI image_url, etc.).

## media= Parameter

Pass media when calling an LLM agent:

```python
@mesh.llm(provider={"capability": "llm"}, filter=[{"tags": ["tools"]}])
@mesh.tool(capability="analyzer")
async def analyze(question: str, llm: mesh.MeshLlmAgent = None) -> str:
    # Single image URI
    return await llm("Describe this image", media=["file:///tmp/photo.png"])

    # Raw bytes
    return await llm("What is this?", media=[(png_bytes, "image/png")])

    # Multiple items
    return await llm("Compare these", media=[
        "file:///tmp/a.png",
        "s3://bucket/b.jpg",
        (pdf_bytes, "application/pdf"),
    ])
```

### Media Item Types

Each item in the `media` list can be:

| Type        | Format              | Example                                              |
| ----------- | ------------------- | ---------------------------------------------------- |
| URI string  | `str`               | `"file:///tmp/photo.png"` or `"s3://bucket/img.jpg"` |
| Bytes tuple | `tuple[bytes, str]` | `(png_bytes, "image/png")`                           |

URIs are fetched from the configured MediaStore backend. See `meshctl man media` for storage configuration.

## MediaParam Type Hint

Mark tool parameters that accept media URIs, so LLMs know which parameters can receive media:

```python
@mesh.tool(capability="image_analyzer")
async def analyze(
    question: str,
    image: mesh.MediaParam("image/*") = None,
    document: mesh.MediaParam("application/pdf") = None,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    media = []
    if image:
        media.append(image)
    if document:
        media.append(document)
    return await llm(question, media=media)
```

### MIME Type Patterns

| Pattern             | Accepts                                 |
| ------------------- | --------------------------------------- |
| `"image/*"`         | Any image (png, jpeg, gif, webp)        |
| `"application/pdf"` | PDF documents                           |
| `"text/*"`          | Text files (plain, csv, markdown, html) |
| `"*/*"`             | Any media type (default)                |

`MediaParam` adds `x-media-type` to the JSON schema, enabling LLMs to route media URIs to the correct parameter in multi-agent chains.

## Resource Link Resolution

When an LLM agent calls a tool that returns a `resource_link`, the media is automatically fetched and converted to the LLM's native format:

```
Tool returns resource_link(uri="file:///chart.png", mimeType="image/png")
    ↓
SDK fetches bytes from MediaStore
    ↓
SDK converts to provider format:
  - Claude:  {"type": "image", "source": {"type": "base64", ...}}
  - OpenAI:  {"type": "image_url", "image_url": {"url": "data:...", "detail": "high"}}
  - Gemini:  {"type": "image_url", "image_url": {"url": "data:..."}}
```

### Supported Content Types

| Type                              | Claude                | OpenAI             | Gemini             |
| --------------------------------- | --------------------- | ------------------ | ------------------ |
| Images (png, jpeg, gif, webp)     | Native image block    | image_url (base64) | image_url (base64) |
| PDF                               | Native document block | Text fallback      | Text fallback      |
| Text (plain, csv, md, html, json) | Text block            | Text block         | Text block         |

### Image Handling by Vendor

- **Claude**: Images supported in both tool results and user messages
- **OpenAI/Gemini**: Images in tool results are sent as a separate user message (these vendors don't support images in tool messages)

## Multi-Agent Media Chain

A common pattern: one agent produces media, another consumes it with an LLM.

### Producer Agent

```python
@mesh.tool(capability="chart_gen")
async def generate_chart(query: str) -> ResourceLink:
    png = render_chart(query)
    return await mesh.MediaResult(
        data=png, filename="chart.png", mime_type="image/png",
        name="Chart", description=query,
    )
```

### Consumer Agent

```python
@mesh.llm(
    provider={"capability": "llm"},
    filter=[{"capability": "chart_gen"}],
    max_iterations=3,
)
@mesh.tool(capability="chart_analyst")
async def analyze_chart(question: str, llm: mesh.MeshLlmAgent = None) -> str:
    return await llm(f"Generate a chart and analyze it: {question}")
    # LLM calls chart_gen → gets resource_link → image auto-resolved
```

The LLM calls `chart_gen`, receives the `resource_link`, and the SDK automatically resolves it to a native image before the next LLM turn.

## Passing Media from External Sources

Upload external media first, then pass the URI:

```python
@mesh.tool(capability="photo_analyzer")
async def analyze_photo(
    question: str,
    photo: mesh.MediaParam("image/*") = None,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    media = [photo] if photo else []
    return await llm(question, media=media)

# From a web endpoint:
@app.post("/analyze")
async def analyze_endpoint(file: UploadFile, question: str):
    uri = await mesh.save_upload(file)
    result = await call_tool("photo_analyzer", {"question": question, "photo": uri})
    return result
```

## See Also

- `meshctl man media` - Storage backends and upload APIs
- `meshctl man llm` - LLM integration and @mesh.llm decorator
- `meshctl man proxies` - Inter-agent communication
