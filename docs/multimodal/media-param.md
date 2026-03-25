# MediaParam Type Hints

In multi-agent chains, LLMs need to know which tool parameters accept media URIs. `MediaParam` type hints annotate your tool schema so media is routed to the right place.

## Usage

=== "Python"

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

=== "TypeScript"

    ```typescript
    import { mediaParam } from "@mcpmesh/sdk";

    agent.addTool({
      name: "analyze",
      capability: "image_analyzer",
      parameters: z.object({
        question: z.string(),
        image: mediaParam("image/*"),
        document: mediaParam("application/pdf"),
      }),
      execute: async ({ question, image, document }, { llm }) => {
        const media = [image, document].filter(Boolean);
        return await llm(question, { media });
      },
    });
    ```

=== "Java"

    ```java
    @MeshTool(capability = "image_analyzer")
    public String analyze(
        @Param("question") String question,
        @MediaParam("image/*") @Param("image") String imageUri,
        @MediaParam("application/pdf") @Param("document") String documentUri,
        MeshLlmAgent llm
    ) {
        // Use imageUri / documentUri with LLM
        return llm.request().user(question).media(imageUri).generate();
    }
    ```

## MIME Type Patterns

| Pattern             | Accepts                                 |
| ------------------- | --------------------------------------- |
| `"image/*"`         | Any image (PNG, JPEG, GIF, WebP)        |
| `"application/pdf"` | PDF documents                           |
| `"text/*"`          | Text files (plain, CSV, markdown, HTML) |
| `"*/*"`             | Any media type (default)                |

## How It Works

`MediaParam` adds `x-media-type` to the parameter's JSON schema:

```json
{
  "type": "object",
  "properties": {
    "question": { "type": "string" },
    "image": {
      "type": "string",
      "x-media-type": "image/*",
      "description": "Media URI for this parameter (accepts media URI: image/*)"
    }
  }
}
```

When an LLM discovers this tool via the mesh, it sees the `x-media-type` annotation and knows to pass media URIs to that parameter.

## Multi-Agent Media Flow

`MediaParam` enables media to flow through multi-agent chains:

```
User uploads image
    -> Web API saves to MediaStore -> URI
        -> Calls router tool with image=URI
            -> Router LLM passes URI to analyzer tool (sees x-media-type)
                -> Analyzer LLM resolves URI -> sees actual image
```

Each agent in the chain passes the URI string. Only the final LLM agent resolves the URI to actual bytes.

## See Also

- [LLM Media Input](llm-media-input.md) -- The media= parameter
- [Returning Media](returning-media.md) -- Producing media from tools
- [Provider Support](provider-support.md) -- Vendor capabilities
