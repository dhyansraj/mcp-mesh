# Multimodal LLM (Java/Spring Boot)

> Pass images, PDFs, and files to LLM agents with @MediaParam
> Full guide: https://mcp-mesh.ai/multimodal/

## @MediaParam Annotation

```java
@MeshTool(capability = "image_analyzer", description = "Analyze images with AI")
public String analyze(
    @Param("question") String question,
    @MediaParam("image/*") @Param("image") String imageUri,
    MeshLlmAgent llm
) {
    return llm.request().user(question).media(imageUri).generate();
}
```

### MIME Type Patterns

| Pattern             | Accepts                          |
| ------------------- | -------------------------------- |
| `"image/*"`         | Any image (png, jpeg, gif, webp) |
| `"application/pdf"` | PDF documents                    |
| `"text/*"`          | Text files                       |
| `"*/*"`             | Any media type (default)         |

`@MediaParam` adds `x-media-type` to the parameter's JSON schema, enabling LLMs to route media URIs to the correct parameter.

## Resource Link Resolution

LLM providers auto-resolve `resource_link` URIs — the provider fetches media bytes and converts them to the vendor's native format. No manual fetching needed.

### Supported Content Types

| Type                              | Claude                | OpenAI             | Gemini             |
| --------------------------------- | --------------------- | ------------------ | ------------------ |
| Images (png, jpeg, gif, webp)     | Native image block    | image_url (base64) | Native image block |
| PDF                               | Native document block | Text fallback      | Text fallback      |
| Text (plain, csv, md, html, json) | Text block            | Text block         | Text block         |

## Multi-Agent Media Chain

For multi-agent media chain examples, see https://mcp-mesh.ai/multimodal/getting-started/

## See Also

- `meshctl man media --java` - Storage backends and MeshMedia helpers
- `meshctl man llm --java` - LLM integration and @MeshLlm annotation
- `meshctl man decorators --java` - All annotations reference
