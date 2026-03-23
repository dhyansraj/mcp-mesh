# LLM Media Input

> Pass images, PDFs, and files directly to LLM agents.

## Overview

The `media=` parameter lets you attach media when calling an LLM agent. The SDK resolves URIs from MediaStore and converts them to provider-native formats automatically.

## Basic Usage

=== "Python"

    ```python
    @mesh.llm(provider={"capability": "llm"})
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
        ])
    ```

=== "TypeScript"

    ```typescript
    execute: async ({ question }, { llm }) => {
      // Single URI
      return await llm("Describe this image", {
        media: ["file:///tmp/photo.png"],
      });

      // Buffer
      return await llm("What is this?", {
        media: [{ data: pngBuffer, mimeType: "image/png" }],
      });

      // Multiple items
      return await llm("Compare these", {
        media: ["file:///tmp/a.png", "s3://bucket/b.jpg"],
      });
    }
    ```

=== "Java"

    ```java
    return llm.request()
        .user("Describe this image")
        .media(imageUri)
        .generate();
    ```

## Media Item Types

=== "Python"

    Each item in the `media` list can be:

    | Type | Format | Example |
    | --- | --- | --- |
    | URI string | `str` | `"file:///tmp/photo.png"` |
    | Bytes tuple | `tuple[bytes, str]` | `(png_bytes, "image/png")` |

=== "TypeScript"

    Each item in the `media` array can be:

    | Type | Format | Example |
    | --- | --- | --- |
    | URI string | `string` | `"file:///tmp/photo.png"` |
    | Buffer object | `{ data: Buffer, mimeType: string }` | `{ data: pngBuffer, mimeType: "image/png" }` |

## Automatic Resource Link Resolution

You don't need to use `media=` explicitly when an LLM calls tools that return `resource_link`. The resolution is automatic:

```
1. LLM calls tool -> tool returns resource_link
2. SDK detects resource_link in tool result
3. SDK fetches media bytes from MediaStore
4. SDK converts to provider-native format
5. LLM sees the actual image/document content
```

This means a simple agentic loop works for multimodal:

=== "Python"

    ```python
    @mesh.llm(
        provider={"capability": "llm"},
        filter=[{"capability": "chart_gen"}],
        max_iterations=3,
    )
    @mesh.tool(capability="analyst")
    async def analyze(question: str, llm: mesh.MeshLlmAgent = None) -> str:
        # LLM calls chart_gen, gets image back, analyzes it
        return await llm(f"Generate and analyze a chart: {question}")
    ```

=== "TypeScript"

    ```typescript
    const tool = mesh.llm({
      provider: { capability: "llm" },
      filter: [{ capability: "chart_gen" }],
      maxIterations: 3,
    });
    // LLM calls chart_gen, gets image back, analyzes it
    ```

=== "Java"

    ```java
    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
        filter = @Selector(capability = "chart_gen"),
        maxIterations = 3
    )
    @MeshTool(capability = "analyst")
    public String analyze(@Param("question") String question, MeshLlmAgent llm) {
        return llm.request()
            .user("Generate and analyze a chart: " + question)
            .generate();
    }
    ```

## See Also

- [MediaParam](media-param.md) -- Type hints for media parameters
- [Provider Support](provider-support.md) -- What each vendor supports
- [Returning Media](returning-media.md) -- How tools produce media
