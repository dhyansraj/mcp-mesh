# Multimodal LLM (TypeScript)

> Pass images, PDFs, and files to LLM agents with media option
> Full guide: https://mcp-mesh.ai/multimodal/

## media Option

```typescript
return await llm("Describe this image", { media: ["file:///tmp/photo.png"] });
return await llm("What is this?", {
  media: [{ data: pngBuffer, mimeType: "image/png" }],
});
```

### Media Item Types

| Type          | Format                               | Example                                      |
| ------------- | ------------------------------------ | -------------------------------------------- |
| URI string    | `string`                             | `"file:///tmp/photo.png"`                    |
| Buffer object | `{ data: Buffer, mimeType: string }` | `{ data: pngBuffer, mimeType: "image/png" }` |

## mediaParam() Type Helper

```typescript
import { mediaParam } from "@mcpmesh/sdk";
parameters: z.object({
    image: mediaParam("image/*"),
    document: mediaParam("application/pdf"),
}),
```

### MIME Type Patterns

| Pattern             | Accepts                          |
| ------------------- | -------------------------------- |
| `"image/*"`         | Any image (png, jpeg, gif, webp) |
| `"application/pdf"` | PDF documents                    |
| `"text/*"`          | Text files                       |
| `"*/*"`             | Any media type (default)         |

`mediaParam()` creates an optional string Zod schema with `x-media-type` in the JSON schema, enabling LLMs to route media URIs correctly.

## Resource Link Resolution

LLM providers auto-resolve `resource_link` URIs — the provider fetches media bytes and converts them to the vendor's native format. No manual fetching needed.

## Multi-Agent Media Chain

For multi-agent media chain examples, see https://mcp-mesh.ai/multimodal/getting-started/

## See Also

- `meshctl man media --typescript` - Storage backends and upload APIs
- `meshctl man llm --typescript` - LLM integration and mesh.llm()
- `meshctl man proxies --typescript` - Inter-agent communication
