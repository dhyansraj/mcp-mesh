# Multimodal LLM (Java/Spring Boot)

> Pass images, PDFs, and files to LLM agents with @MediaParam

## Overview

MCP Mesh Java LLM agents can process images, PDFs, and other media alongside text. This works through two mechanisms:

1. **@MediaParam annotation** — Mark tool parameters that accept media URIs
2. **Resource link resolution** — LLMs automatically see media returned by tools via `resource_link`

## @MediaParam Annotation

Mark tool parameters that accept media URIs:

```java
import io.mcpmesh.MediaParam;
import io.mcpmesh.types.MeshLlmAgent;

@MeshLlm(providerSelector = @Selector(capability = "llm"))
@MeshTool(capability = "image_analyzer", description = "Analyze images with AI")
public String analyze(
    @Param("question") String question,
    @MediaParam("image/*") @Param("image") String imageUri,
    MeshLlmAgent llm
) {
    if (imageUri != null) {
        return llm.request()
            .user(question)
            .media(imageUri)
            .generate();
    }
    return llm.request().user(question).generate();
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

When an LLM calls a tool that returns a `ResourceLink`, the `MediaResolver` automatically fetches and converts the media:

```
Tool returns ResourceLink(uri="file:///chart.png", mimeType="image/png")
    ↓
MediaResolver fetches bytes via MediaStore
    ↓
Converts to vendor format:
  - Claude:  {"type": "image", "source": {"type": "base64", ...}}
  - OpenAI:  {"type": "image_url", "image_url": {"url": "data:...", "detail": "high"}}
  - Gemini:  {"type": "image", "source": {"type": "base64", ...}}
```

### Supported Content Types

| Type                              | Claude             | OpenAI             | Gemini             |
| --------------------------------- | ------------------ | ------------------ | ------------------ |
| Images (png, jpeg, gif, webp)     | Native image block | image_url (base64) | Native image block |
| PDF                               | Text fallback      | Text fallback      | Text fallback      |
| Text (plain, csv, md, html, json) | Text block         | Text block         | Text block         |

## Multi-Agent Media Chain

### Producer Agent

```java
import io.mcpmesh.spring.media.MeshMedia;
import io.mcpmesh.spring.media.MediaStore;
import io.modelcontextprotocol.spec.McpSchema.ResourceLink;

@MeshTool(capability = "chart_gen", description = "Generate charts")
public ResourceLink generateChart(
    @Param("query") String query,
    MediaStore mediaStore
) {
    byte[] png = renderChart(query);
    return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
}
```

### Consumer Agent

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm"),
    filter = @Selector(capability = "chart_gen"),
    maxIterations = 3
)
@MeshTool(capability = "chart_analyst", description = "Analyze charts with AI")
public String analyzeChart(
    @Param("question") String question,
    MeshLlmAgent llm
) {
    return llm.request()
        .user("Generate a chart and analyze it: " + question)
        .generate();
    // LLM calls chart_gen → gets ResourceLink → image auto-resolved
}
```

## MediaResolver

The `MediaResolver` class handles resource link resolution in tool results:

```java
import io.mcpmesh.spring.media.MediaResolver;

// Resolve resource links in a tool result
List<Map<String, Object>> resolved = MediaResolver.resolveResourceLinks(
    toolResult,   // String, Map, or List<Map>
    "anthropic",  // vendor: "anthropic", "openai", "gemini"
    mediaStore
);

// Serialize for tool result content
String serialized = MediaResolver.serializeForToolResult(resolved);
```

This is handled automatically by the LLM provider handlers — you only need `MediaResolver` directly for custom integrations.

## See Also

- `meshctl man media --java` - Storage backends and MeshMedia helpers
- `meshctl man llm --java` - LLM integration and @MeshLlm annotation
- `meshctl man decorators --java` - All annotations reference
