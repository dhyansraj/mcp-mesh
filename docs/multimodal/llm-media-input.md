# LLM Media Input

Once media is in the mesh -- uploaded by a user or produced by a tool -- pass it to an LLM using the `media` parameter.

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

When an LLM calls a tool that returns a `resource_link`, the SDK resolves it automatically -- the LLM provider fetches the media bytes and converts them to the vendor's native format. No `media=` parameter is needed for tool-returned media. See [Getting Started](getting-started.md) for the full flow.

## Reading Media in Agents

When an agent receives a media URI (e.g., from a tool parameter or another agent) and needs to read the actual bytes — not pass it to an LLM — use `download_media`:

=== "Python"

    ```python
    data, mime_type = await mesh.download_media("s3://mcp-mesh-media/media/report.csv")
    ```

=== "TypeScript"

    ```typescript
    import { downloadMedia } from "@mcpmesh/sdk";
    const { data, mimeType } = await downloadMedia("s3://mcp-mesh-media/media/report.csv");
    ```

=== "Java"

    ```java
    MediaFetchResult result = MeshMedia.downloadMedia(uri, mediaStore);
    byte[] data = result.data();
    ```

This reads from the same MediaStore backend (local or S3) that `upload_media` wrote to.

## See Also

- [MediaParam](media-param.md) -- Type hints for media parameters
- [Provider Support](provider-support.md) -- What each vendor supports
- [Returning Media](returning-media.md) -- How tools produce media
