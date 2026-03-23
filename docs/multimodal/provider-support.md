# Provider Support Matrix

> What each LLM provider supports for multimodal content.

## Overview

Different LLM providers handle media differently. The MCP Mesh SDK automatically converts media to each provider's native format, but capabilities vary.

## Support Matrix

| Content Type | Claude | OpenAI | Gemini |
| --- | --- | --- | --- |
| **Images** (PNG, JPEG, GIF, WebP) | Native image blocks | image_url (base64) | image_url (base64) |
| **PDF** | Native document blocks | Text extraction fallback | Text extraction fallback |
| **Text files** (plain, CSV, MD, HTML, JSON) | Text content blocks | Text content blocks | Text content blocks |
| **Images in tool results** | Inline in tool message | Separate user message | Separate user message |

## Image Handling

All three providers support images, but with different mechanics:

### Claude (Anthropic)

- Images supported in both user messages and tool result messages
- Native `image` content blocks with base64 encoding
- Supports PNG, JPEG, GIF, WebP
- Best multimodal experience -- images appear inline with tool results

### OpenAI

- Images supported in user messages only
- Uses `image_url` content blocks with base64 data URIs
- When a tool returns an image, the SDK sends it as a follow-up user message
- Supports PNG, JPEG, GIF, WebP

### Gemini

- Similar to OpenAI -- images in user messages only
- Uses `image_url` format compatible with OpenAI
- Tool result images sent as follow-up user messages

!!! tip "Claude is Recommended for Media-Heavy Workloads"
    Claude provides the best multimodal experience because it supports images directly in tool result messages. This means the LLM sees the image in context with the tool output, rather than as a separate message.

## PDF Handling

| Provider | Support |
| --- | --- |
| **Claude** | Native `document` blocks -- full PDF understanding |
| **OpenAI** | Text extraction fallback (first 50,000 characters) |
| **Gemini** | Text extraction fallback (first 50,000 characters) |

## Text File Handling

All providers receive text files as plain text content blocks. Files are decoded as UTF-8 (with Latin-1 fallback) and truncated to 50,000 characters.

Supported text MIME types:

- `text/plain`, `text/csv`, `text/markdown`, `text/html`, `text/xml`
- `application/json`, `application/xml`, `application/csv`

## Provider Selection for Multimodal

When building multimodal agents, select providers based on your media needs:

=== "Python"

    ```python
    # Prefer Claude for image-heavy workloads
    @mesh.llm(
        provider={"capability": "llm", "tags": ["+claude"]},
        filter=[{"capability": "chart_gen"}],
    )
    ```

=== "TypeScript"

    ```typescript
    mesh.llm({
      provider: { capability: "llm", tags: ["+claude"] },
      filter: [{ capability: "chart_gen" }],
    })
    ```

=== "Java"

    ```java
    @MeshLlm(
        providerSelector = @Selector(capability = "llm", tags = {"+claude"}),
        filter = @Selector(capability = "chart_gen")
    )
    ```

## See Also

- [LLM Media Input](llm-media-input.md) -- Passing media to LLMs
- [Returning Media](returning-media.md) -- How tools produce media
- [LLM Integration (Python)](../python/llm/index.md) -- Full LLM documentation
