# Returning Media from Tools

When a tool generates an image, chart, or document, use `MediaResult` to upload the bytes and return a `resource_link`. LLM providers auto-resolve these links -- no manual fetching needed.

## MediaResult (Recommended)

The simplest approach — upload + return in one step:

=== "Python"

    ```python
    @mesh.tool(capability="chart_gen")
    async def generate_chart(query: str):
        png_bytes = render_chart(query)
        return await mesh.MediaResult(
            data=png_bytes,
            filename="chart.png",
            mime_type="image/png",
            name="Sales Chart",
            description="Q3 revenue chart",
        )
    ```

    | Parameter | Type | Description |
    | --- | --- | --- |
    | `data` | `bytes` | Raw binary content |
    | `filename` | `str` | Filename for storage |
    | `mime_type` | `str` | MIME type (e.g., `"image/png"`) |
    | `name` | `str \| None` | Display name (defaults to filename) |
    | `description` | `str \| None` | Optional description |

=== "TypeScript"

    ```typescript
    import { createMediaResult } from "@mcpmesh/sdk";

    agent.addTool({
      name: "generate_chart",
      capability: "chart_gen",
      parameters: z.object({ query: z.string() }),
      execute: async ({ query }) => {
        const png = renderChart(query);
        return await createMediaResult(
          png, "chart.png", "image/png", "Sales Chart", "Q3 revenue chart"
        );
      },
    });
    ```

=== "Java"

    ```java
    @MeshTool(capability = "chart_gen")
    public ResourceLink generateChart(
        @Param("query") String query,
        MediaStore mediaStore
    ) {
        byte[] png = renderChart(query);
        return MeshMedia.mediaResult(
            png, "chart.png", "image/png",
            "Sales Chart", "Q3 revenue chart",
            mediaStore
        );
    }
    ```

## Two-Step: upload_media + media_result

For more control, upload first, then create the link:

=== "Python"

    ```python
    uri = await mesh.upload_media(png_bytes, "chart.png", "image/png")
    return mesh.media_result(
        uri=uri,
        name="Sales Chart",
        mime_type="image/png",
        description="Q3 revenue",
        size=len(png_bytes),
    )
    ```

=== "TypeScript"

    ```typescript
    import { uploadMedia, mediaResult } from "@mcpmesh/sdk";

    const uri = await uploadMedia(png, "chart.png", "image/png");
    return mediaResult(uri, "Sales Chart", "image/png", "Q3 revenue", png.length);
    ```

=== "Java"

    ```java
    String uri = mediaStore.upload(png, "chart.png", "image/png");
    return MeshMedia.mediaResult(uri, "Sales Chart", "image/png", "Q3 chart", (long) png.length);
    ```

## Resource Link Format

Tools return media as MCP `resource_link` content:

```json
{
  "type": "resource_link",
  "uri": "file:///tmp/mcp-mesh-media/media/chart.png",
  "name": "Sales Chart",
  "mimeType": "image/png",
  "description": "Q3 revenue chart",
  "_meta": { "size": 45678 }
}
```

When an LLM agent receives this in a tool result, the SDK automatically fetches the URI from MediaStore and converts it to the provider's native format. See [Provider Support](provider-support.md) for details.

See [Provider Support](provider-support.md) for which MIME types each LLM vendor supports.

## See Also

- [MediaStore Configuration](media-store.md) — Storage backends
- [LLM Media Input](llm-media-input.md) — Passing media directly to LLMs
- [Web Uploads](web-uploads.md) — Saving uploaded files from web frameworks
