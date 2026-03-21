#!/usr/bin/env python3
"""
media-llm-consumer - MCP Mesh Media LLM Consumer Agent

Demonstrates the full multimodal pipeline: asks an LLM to generate a chart
via a mesh tool and then describe the resulting image. The flow is:

1. Consumer's tool is called with a topic
2. The LLM (via mesh-delegated provider) is asked to generate and analyze a chart
3. The LLM calls the media-producer's generate_chart tool (via provider-side execution)
4. The provider's media resolver converts the resource_link to an inline base64 image
5. The LLM sees the actual image and describes it

This tests that resource_links are correctly resolved to multimodal content
before being sent to the LLM.

Also supports multi-provider testing with Claude, OpenAI, and Gemini for
analyzing real distributed tracing screenshots via the image-tool agent.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Media LLM Consumer")

# ---------------------------------------------------------------------------
# Existing Claude chart/image analysis tools
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[
        {"capability": "chart_generator"},
        {"capability": "image_generator"},
    ],
    max_iterations=5,
    system_prompt=(
        "You are an image analysis assistant. You have access to tools that "
        "generate charts and images. When asked to analyze a topic, FIRST use "
        "the generate_chart tool to create a chart, THEN describe what you see "
        "in the resulting image. Be specific about colors, labels, and values."
    ),
)
@mesh.tool(
    capability="image_analyzer",
    description="Generates a chart via media-producer then asks the LLM to describe it",
)
async def analyze_image(topic: str = "Sales", llm: mesh.MeshLlmAgent = None) -> str:
    """Generate a chart on the given topic and ask the LLM to describe the image."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Generate a bar chart about {topic} with a few data categories, "
        f"then describe the chart image you see in detail."
    )
    return f"LLM Analysis:\n{result}"


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[
        {"capability": "image_generator"},
    ],
    max_iterations=5,
    system_prompt=(
        "You are an image analysis assistant. You have access to a tool that "
        "returns a sample PNG image. When asked, use the get_sample_image tool "
        "to retrieve the image, then describe exactly what you see."
    ),
)
@mesh.tool(
    capability="png_analyzer",
    description="Retrieves a sample PNG image via media-producer then asks the LLM to describe it",
)
async def analyze_png(llm: mesh.MeshLlmAgent = None) -> str:
    """Retrieve a sample PNG from the media-producer and ask the LLM to describe it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm("Get the sample image and describe what you see in it.")
    return f"LLM Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Real trace image analysis - Claude
# ---------------------------------------------------------------------------

TRACE_SYSTEM_PROMPT = (
    "You are an expert at analyzing distributed tracing screenshots from "
    "tools like Jaeger and Tempo. You have access to a tool that provides "
    "real trace screenshots. When asked, use the get_trace_image tool to "
    "retrieve the image, then describe what you see: services involved, "
    "span hierarchy, latencies, errors, and any performance observations."
)


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[{"capability": "trace_image_provider"}],
    max_iterations=3,
    system_prompt=TRACE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="trace_analyzer_claude",
    description="Analyzes a real trace screenshot using Claude",
)
async def analyze_trace_claude(
    image_number: int = 1, llm: mesh.MeshLlmAgent = None
) -> str:
    """Fetch a real trace screenshot and ask Claude to analyze it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get trace image number {image_number} and analyze the distributed "
        f"tracing screenshot in detail. What services are shown? What are the "
        f"span timings? Are there any errors or performance issues?"
    )
    return f"Claude Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Real trace image analysis - OpenAI
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    filter=[{"capability": "trace_image_provider"}],
    max_iterations=3,
    system_prompt=TRACE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="trace_analyzer_openai",
    description="Analyzes a real trace screenshot using OpenAI GPT-4o",
)
async def analyze_trace_openai(
    image_number: int = 1, llm: mesh.MeshLlmAgent = None
) -> str:
    """Fetch a real trace screenshot and ask OpenAI GPT-4o to analyze it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get trace image number {image_number} and analyze the distributed "
        f"tracing screenshot in detail. What services are shown? What are the "
        f"span timings? Are there any errors or performance issues?"
    )
    return f"OpenAI Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Real trace image analysis - Gemini
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    filter=[{"capability": "trace_image_provider"}],
    max_iterations=3,
    system_prompt=TRACE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="trace_analyzer_gemini",
    description="Analyzes a real trace screenshot using Google Gemini 2.0 Flash",
)
async def analyze_trace_gemini(
    image_number: int = 1, llm: mesh.MeshLlmAgent = None
) -> str:
    """Fetch a real trace screenshot and ask Gemini to analyze it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get trace image number {image_number} and analyze the distributed "
        f"tracing screenshot in detail. What services are shown? What are the "
        f"span timings? Are there any errors or performance issues?"
    )
    return f"Gemini Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Multi-image analysis - Claude
# ---------------------------------------------------------------------------

MULTI_IMAGE_SYSTEM_PROMPT = (
    "You analyze images. When asked, use the available tool to get images, "
    "then describe ALL images you see."
)


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[{"capability": "multi_image_provider"}],
    max_iterations=3,
    system_prompt=MULTI_IMAGE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="multi_image_analyzer",
    description="Tests multiple images in one response",
)
async def analyze_multiple_images(
    count: int = 2, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get multiple images and ask Claude to describe each one."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get {count} images and briefly describe each one you see."
    )
    return f"Multi-Image Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Mixed content analysis - Claude
# ---------------------------------------------------------------------------

MIXED_CONTENT_SYSTEM_PROMPT = (
    "You analyze mixed content. Use the tool to get content, then describe "
    "what you received — both text and images."
)


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[{"capability": "mixed_content_provider"}],
    max_iterations=3,
    system_prompt=MIXED_CONTENT_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="mixed_content_analyzer",
    description="Tests mixed text + image content",
)
async def analyze_mixed_content(
    image_number: int = 3, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get mixed text+image content and ask Claude to describe everything."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get the mixed content for image {image_number} and describe "
        f"everything you see — both the text and the image."
    )
    return f"Mixed Content Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Non-image resource_link - Claude
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[{"capability": "document_provider"}],
    max_iterations=3,
    system_prompt=(
        "You process documents. Use the tool to get a document, "
        "then describe what you received."
    ),
)
@mesh.tool(
    capability="document_analyzer",
    description="Tests non-image resource_link (markdown)",
)
async def analyze_document(llm: mesh.MeshLlmAgent = None) -> str:
    """Get a markdown document and ask Claude to describe it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm("Get the test document and tell me what you received.")
    return f"Document Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Multi-image analysis - OpenAI
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    filter=[{"capability": "multi_image_provider"}],
    max_iterations=3,
    system_prompt=MULTI_IMAGE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="multi_image_analyzer_openai",
    description="Tests multiple images with OpenAI",
)
async def analyze_multiple_images_openai(
    count: int = 2, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get multiple images and ask OpenAI GPT-4o to describe each one."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get {count} images and briefly describe each one you see."
    )
    return f"OpenAI Multi-Image:\n{result}"


# ---------------------------------------------------------------------------
# Image analysis (chart generation) - OpenAI
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    filter=[
        {"capability": "chart_generator"},
        {"capability": "image_generator"},
    ],
    max_iterations=5,
    system_prompt=(
        "You are an image analysis assistant. You have access to tools that "
        "generate charts and images. When asked to analyze a topic, FIRST use "
        "the generate_chart tool to create a chart, THEN describe what you see "
        "in the resulting image. Be specific about colors, labels, and values."
    ),
)
@mesh.tool(
    capability="image_analyzer_openai",
    description="Generates a chart via media-producer then asks OpenAI to describe it",
)
async def analyze_image_openai(topic: str = "Sales", llm: mesh.MeshLlmAgent = None) -> str:
    """Generate a chart on the given topic and ask OpenAI GPT-4o to describe the image."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Generate a bar chart about {topic} with a few data categories, "
        f"then describe the chart image you see in detail."
    )
    return f"OpenAI Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Mixed content analysis - OpenAI
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    filter=[{"capability": "mixed_content_provider"}],
    max_iterations=3,
    system_prompt=MIXED_CONTENT_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="mixed_content_analyzer_openai",
    description="Tests mixed text + image content with OpenAI",
)
async def analyze_mixed_content_openai(
    image_number: int = 3, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get mixed text+image content and ask OpenAI GPT-4o to describe everything."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get the mixed content for image {image_number} and describe "
        f"everything you see — both the text and the image."
    )
    return f"OpenAI Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Non-image resource_link - OpenAI
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    filter=[{"capability": "document_provider"}],
    max_iterations=3,
    system_prompt=(
        "You process documents. Use the tool to get a document, "
        "then describe what you received."
    ),
)
@mesh.tool(
    capability="document_analyzer_openai",
    description="Tests non-image resource_link (markdown) with OpenAI",
)
async def analyze_document_openai(llm: mesh.MeshLlmAgent = None) -> str:
    """Get a markdown document and ask OpenAI GPT-4o to describe it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm("Get the test document and tell me what you received.")
    return f"OpenAI Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Image analysis (chart generation) - Gemini
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    filter=[
        {"capability": "chart_generator"},
        {"capability": "image_generator"},
    ],
    max_iterations=5,
    system_prompt=(
        "You are an image analysis assistant. You have access to tools that "
        "generate charts and images. When asked to analyze a topic, FIRST use "
        "the generate_chart tool to create a chart, THEN describe what you see "
        "in the resulting image. Be specific about colors, labels, and values."
    ),
)
@mesh.tool(
    capability="image_analyzer_gemini",
    description="Generates a chart via media-producer then asks Gemini to describe it",
)
async def analyze_image_gemini(topic: str = "Sales", llm: mesh.MeshLlmAgent = None) -> str:
    """Generate a chart on the given topic and ask Gemini to describe the image."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Generate a bar chart about {topic} with a few data categories, "
        f"then describe the chart image you see in detail."
    )
    return f"Gemini Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Multi-image analysis - Gemini
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    filter=[{"capability": "multi_image_provider"}],
    max_iterations=3,
    system_prompt=MULTI_IMAGE_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="multi_image_analyzer_gemini",
    description="Tests multiple images with Gemini",
)
async def analyze_multiple_images_gemini(
    count: int = 2, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get multiple images and ask Gemini to describe each one."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get {count} images and briefly describe each one you see."
    )
    return f"Gemini Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Mixed content analysis - Gemini
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    filter=[{"capability": "mixed_content_provider"}],
    max_iterations=3,
    system_prompt=MIXED_CONTENT_SYSTEM_PROMPT,
)
@mesh.tool(
    capability="mixed_content_analyzer_gemini",
    description="Tests mixed text + image content with Gemini",
)
async def analyze_mixed_content_gemini(
    image_number: int = 3, llm: mesh.MeshLlmAgent = None
) -> str:
    """Get mixed text+image content and ask Gemini to describe everything."""
    if not llm:
        return "Error: LLM not available"

    result = await llm(
        f"Get the mixed content for image {image_number} and describe "
        f"everything you see — both the text and the image."
    )
    return f"Gemini Analysis:\n{result}"


# ---------------------------------------------------------------------------
# Non-image resource_link - Gemini
# ---------------------------------------------------------------------------


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    filter=[{"capability": "document_provider"}],
    max_iterations=3,
    system_prompt=(
        "You process documents. Use the tool to get a document, "
        "then describe what you received."
    ),
)
@mesh.tool(
    capability="document_analyzer_gemini",
    description="Tests non-image resource_link (markdown) with Gemini",
)
async def analyze_document_gemini(llm: mesh.MeshLlmAgent = None) -> str:
    """Get a markdown document and ask Gemini to describe it."""
    if not llm:
        return "Error: LLM not available"

    result = await llm("Get the test document and tell me what you received.")
    return f"Gemini Analysis:\n{result}"


@mesh.agent(
    name="media-llm-consumer",
    version="1.0.0",
    description="LLM consumer that generates and analyzes media from the producer, supports Claude/OpenAI/Gemini",
    http_port=9203,
    enable_http=True,
    auto_run=True,
)
class MediaLlmConsumer:
    pass
