# Multimodal LLM (TypeScript)

> Pass images, PDFs, and files to LLM agents with media option

## Overview

MCP Mesh LLM agents can process images, PDFs, and other media alongside text. This works through two mechanisms:

1. **media option** — Attach media directly when calling an LLM agent
2. **Resource link resolution** — LLMs automatically see media returned by tools via `resource_link`

## media Option

Pass media when calling an LLM agent:

```typescript
agent.addTool({
  name: "analyze",
  ...mesh.llm({
    provider: { capability: "llm" },
    filter: [{ tags: ["tools"] }],
  }),
  capability: "analyzer",
  parameters: z.object({ question: z.string() }),
  execute: async ({ question }, { llm }) => {
    // Single URI
    return await llm("Describe this image", {
      media: ["file:///tmp/photo.png"],
    });

    // Raw bytes
    return await llm("What is this?", {
      media: [{ data: pngBuffer, mimeType: "image/png" }],
    });

    // Multiple items
    return await llm("Compare these", {
      media: [
        "file:///tmp/a.png",
        "s3://bucket/b.jpg",
        { data: pdfBuffer, mimeType: "application/pdf" },
      ],
    });
  },
});
```

### Media Item Types

Each item in the `media` array can be:

| Type          | Format                               | Example                                      |
| ------------- | ------------------------------------ | -------------------------------------------- |
| URI string    | `string`                             | `"file:///tmp/photo.png"`                    |
| Buffer object | `{ data: Buffer, mimeType: string }` | `{ data: pngBuffer, mimeType: "image/png" }` |

## mediaParam() Type Helper

Mark tool parameters that accept media URIs using Zod schemas:

```typescript
import { mediaParam } from "@mcpmesh/sdk";

agent.addTool({
  name: "analyze",
  ...mesh.llm({ provider: { capability: "llm" } }),
  capability: "image_analyzer",
  parameters: z.object({
    question: z.string(),
    image: mediaParam("image/*"),
    document: mediaParam("application/pdf"),
  }),
  execute: async ({ question, image, document }, { llm }) => {
    const media: Array<string> = [];
    if (image) media.push(image);
    if (document) media.push(document);
    return await llm(question, { media });
  },
});
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

When an LLM calls a tool that returns a `resource_link`, the media is automatically fetched and converted:

### Supported Content Types

| Type                              | Claude                | OpenAI             | Gemini             |
| --------------------------------- | --------------------- | ------------------ | ------------------ |
| Images (png, jpeg, gif, webp)     | Native image block    | image_url (base64) | image_url (base64) |
| PDF                               | Native document block | Text fallback      | Text fallback      |
| Text (plain, csv, md, html, json) | Text block            | Text block         | Text block         |

## Multi-Agent Media Chain

### Producer Agent

```typescript
import { uploadMedia, mediaResult } from "@mcpmesh/sdk";

agent.addTool({
  name: "generate_chart",
  capability: "chart_gen",
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }) => {
    const png = renderChart(query);
    const uri = await uploadMedia(png, "chart.png", "image/png");
    return mediaResult(uri, "Chart", "image/png", query, png.length);
  },
});
```

### Consumer Agent

```typescript
agent.addTool({
  name: "analyze_chart",
  ...mesh.llm({
    provider: { capability: "llm" },
    filter: [{ capability: "chart_gen" }],
    maxIterations: 3,
  }),
  capability: "chart_analyst",
  parameters: z.object({ question: z.string() }),
  execute: async ({ question }, { llm }) => {
    return await llm(`Generate a chart and analyze it: ${question}`);
    // LLM calls chart_gen → gets resource_link → image auto-resolved
  },
});
```

## LlmCallOptions

The full `media` option in the LLM call options:

```typescript
interface LlmCallOptions {
  media?: Array<string | { data: Buffer; mimeType: string }>;
  maxOutputTokens?: number;
  temperature?: number;
  maxIterations?: number;
}
```

## See Also

- `meshctl man media --typescript` - Storage backends and upload APIs
- `meshctl man llm --typescript` - LLM integration and mesh.llm()
- `meshctl man proxies --typescript` - Inter-agent communication
