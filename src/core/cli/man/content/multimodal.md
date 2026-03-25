# Multimodal LLM

> Pass images, PDFs, and files to LLM agents with media= parameter
> Full guide: https://mcp-mesh.ai/multimodal/

## media= Parameter

```python
return await llm("Describe this image", media=["file:///tmp/photo.png"])
return await llm("What is this?", media=[(png_bytes, "image/png")])
```

### Media Item Types

| Type        | Format              | Example                                              |
| ----------- | ------------------- | ---------------------------------------------------- |
| URI string  | `str`               | `"file:///tmp/photo.png"` or `"s3://bucket/img.jpg"` |
| Bytes tuple | `tuple[bytes, str]` | `(png_bytes, "image/png")`                           |

URIs are fetched from the configured MediaStore backend. See `meshctl man media` for storage configuration.

## MediaParam Type Hint

```python
@mesh.tool(capability="image_analyzer")
async def analyze(
    image: mesh.MediaParam("image/*") = None,
    document: mesh.MediaParam("application/pdf") = None,
    llm: mesh.MeshLlmAgent = None,
) -> str: ...
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

LLM providers auto-resolve `resource_link` URIs — the provider fetches media bytes and converts them to the vendor's native format. No manual fetching needed.

Only the **producer** (write) and **provider** (read) need MediaStore access. See `meshctl man media` for setup.

## Multi-Agent Media Chain

For multi-agent media chain examples, see https://mcp-mesh.ai/multimodal/getting-started/

## Passing Media from External Sources

For web upload integration and external media handling, see https://mcp-mesh.ai/multimodal/media-store/

## See Also

- `meshctl man media` - Storage backends and upload APIs
- `meshctl man llm` - LLM integration and @mesh.llm decorator
- `meshctl man proxies` - Inter-agent communication
