# Multimodal Quick Start

> Return images, PDFs, and files from mesh tools — and pass them to LLMs.

## Overview

MCP Mesh v1.0.0 adds multimodal support across all runtimes:

- **MediaStore** — Pluggable storage (local filesystem or S3) for binary content
- **MediaResult / media_result** — Return media from tools as MCP `resource_link` objects
- **media= parameter** — Pass images and documents directly to LLM agents
- **MediaParam** — Type hints that tell LLMs which parameters accept media URIs
- **Auto-resolution** — LLM providers automatically fetch and convert media to native formats

## 5-Minute Example

A tool that generates a chart image, and an LLM agent that analyzes it:

=== "Python"

    ```python
    # chart_agent.py — produces an image
    import mesh
    from fastmcp import FastMCP

    app = FastMCP("Chart Agent")

    @app.tool()
    @mesh.tool(capability="chart_gen", tags=["tools"])
    async def generate_chart(query: str):
        png_bytes = render_chart(query)  # your rendering logic
        return await mesh.MediaResult(
            data=png_bytes,
            filename="chart.png",
            mime_type="image/png",
            name="Chart",
            description=query,
        )

    @mesh.agent(name="chart-agent", http_port=9010, auto_run=True)
    class ChartAgent:
        pass
    ```

    ```python
    # analyst_agent.py — LLM that calls chart_gen and sees the image
    import mesh
    from fastmcp import FastMCP

    app = FastMCP("Analyst Agent")

    @app.tool()
    @mesh.llm(
        provider={"capability": "llm"},
        filter=[{"capability": "chart_gen"}],
        max_iterations=3,
    )
    @mesh.tool(capability="chart_analyst", tags=["llm"])
    async def analyze(question: str, llm: mesh.MeshLlmAgent = None) -> str:
        return await llm(f"Generate a chart and analyze it: {question}")
        # LLM calls chart_gen → gets resource_link → image auto-resolved

    @mesh.agent(name="analyst", http_port=9011, auto_run=True)
    class AnalystAgent:
        pass
    ```

=== "TypeScript"

    ```typescript
    // chart-agent.ts — produces an image
    import { FastMCP, mesh, uploadMedia, mediaResult } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "Chart Agent", version: "1.0.0" });
    const agent = mesh(server, { name: "chart-agent", httpPort: 9010 });

    agent.addTool({
      name: "generate_chart",
      capability: "chart_gen",
      tags: ["tools"],
      parameters: z.object({ query: z.string() }),
      execute: async ({ query }) => {
        const png = renderChart(query);
        const uri = await uploadMedia(png, "chart.png", "image/png");
        return mediaResult(uri, "Chart", "image/png", query, png.length);
      },
    });
    ```

    ```typescript
    // analyst-agent.ts — LLM that calls chart_gen and sees the image
    import { FastMCP, mesh } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "Analyst", version: "1.0.0" });

    const llmTool = mesh.llm({
      provider: { capability: "llm" },
      filter: [{ capability: "chart_gen" }],
      maxIterations: 3,
    });

    server.addTool({
      name: "analyze",
      ...llmTool,
      capability: "chart_analyst",
      tags: ["llm"],
      parameters: z.object({ question: z.string() }),
      execute: async ({ question }, { llm }) => {
        return await llm(`Generate a chart and analyze it: ${question}`);
      },
    });

    const agent = mesh(server, { name: "analyst", httpPort: 9011 });
    ```

=== "Java"

    ```java
    // ChartAgent.java — produces an image
    @MeshAgent(name = "chart-agent", port = 9010)
    @SpringBootApplication
    public class ChartAgentApplication {
        @MeshTool(capability = "chart_gen", tags = {"tools"})
        public ResourceLink generateChart(
            @Param("query") String query,
            MediaStore mediaStore
        ) {
            byte[] png = renderChart(query);
            return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
        }
    }
    ```

    ```java
    // AnalystAgent.java — LLM that calls chart_gen and sees the image
    @MeshAgent(name = "analyst", port = 9011)
    @SpringBootApplication
    public class AnalystApplication {
        @MeshLlm(
            providerSelector = @Selector(capability = "llm"),
            filter = @Selector(capability = "chart_gen"),
            maxIterations = 3
        )
        @MeshTool(capability = "chart_analyst", tags = {"llm"})
        public String analyze(
            @Param("question") String question,
            MeshLlmAgent llm
        ) {
            return llm.request()
                .user("Generate a chart and analyze it: " + question)
                .generate();
        }
    }
    ```

## How It Works

```
1. Analyst LLM calls chart_gen tool
2. chart_gen renders PNG → uploads to MediaStore → returns resource_link
3. SDK fetches resource_link URI from MediaStore
4. SDK converts to provider-native format (Claude image block, OpenAI image_url, etc.)
5. LLM sees the actual image and can analyze it
```

## What's Next

- [MediaStore Configuration](media-store.md) — Local vs S3 storage backends
- [Returning Media](returning-media.md) — MediaResult, upload_media, media_result
- [LLM Media Input](llm-media-input.md) — The media= parameter
- [MediaParam](media-param.md) — Type hints for multi-agent media flow
- [Provider Support](provider-support.md) — What each LLM vendor supports
