# Multimodal LLM

> Pass images, PDFs, and files to LLM agents with media= parameter
> Full guide: https://mcp-mesh.ai/multimodal/

## media= Parameter

```python
return await llm("Describe this image", media=["file:///tmp/photo.png"])
return await llm("What is this?", media=[(png_bytes, "image/png")])
```

`media=` is a kwarg on `MeshLlmAgent.__call__()`. Items are resolved on the
**consumer side** into provider-native content blocks before the request is
serialized — they do not appear on the `MeshLlmRequest` wire schema.

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

LLM providers auto-resolve `resource_link` URIs returned from agentic tool calls — the provider fetches media bytes and converts them to the vendor's native format. No manual fetching needed.

### Who needs MediaStore access?

The two media flows have different access requirements:

| Flow                                       | Resolved by | Needs MediaStore access |
| ------------------------------------------ | ----------- | ----------------------- |
| `media=[uri]` kwarg on `MeshLlmAgent`      | Consumer    | Producer + **consumer** |
| `resource_link` returned from a tool call  | Provider    | Producer + **provider** |

If your consumer passes `media=["s3://..."]`, the consumer process needs S3
credentials and `boto3` installed. If you only return `resource_link` from
agentic tools and let the LLM provider fetch them, only the provider needs
MediaStore access.

See `meshctl man media` for storage setup.

## Further reading

- Multi-agent media chain examples: https://mcp-mesh.ai/multimodal/getting-started/
- Web upload integration and external media handling: https://mcp-mesh.ai/multimodal/media-store/

## See Also

- `meshctl man media` - Storage backends and upload APIs
- `meshctl man llm` - LLM integration and @mesh.llm decorator
- `meshctl man proxies` - Inter-agent communication
