#!/usr/bin/env python3
"""
image-tool - MCP Mesh Image Tool Agent

Reads real JPG images from disk and returns them as resource_links via
the mesh media API. Used to test multimodal pipelines with actual
photographic images (distributed tracing screenshots) rather than
programmatically generated content.
"""

import mesh
from fastmcp import FastMCP
from mcp.types import ResourceLink
from pathlib import Path

app = FastMCP("Image Tool")

# Navigate from multimedia/ -> python/ -> examples/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@app.tool()
@mesh.tool(
    capability="trace_image_provider",
    description="Provides a real distributed tracing screenshot for LLM analysis",
)
async def get_trace_image(image_number: int = 1) -> ResourceLink:
    """Upload a real trace screenshot and return a resource_link.

    Args:
        image_number: Which trace image to return (1 or 2).
    """
    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(
            f"Image {image_number}.jpg not found at {PROJECT_ROOT}. "
            f"Expected files: 1.jpg, 2.jpg in the project root."
        )

    data = image_path.read_bytes()
    filename = f"trace_{image_number}.jpg"
    uri = await mesh.upload_media(data=data, filename=filename, mime_type="image/jpeg")
    return mesh.media_result(
        uri=uri,
        name=f"Trace Screenshot {image_number}",
        mime_type="image/jpeg",
        description=f"Distributed tracing screenshot #{image_number} (Jaeger/Tempo)",
        size=len(data),
    )


@app.tool()
@mesh.tool(
    capability="multi_image_provider",
    description="Returns multiple images at once",
)
async def get_multiple_images(count: int = 2) -> list:
    """Return multiple images as a list of ResourceLinks.

    Args:
        count: Number of images to return (1-5).
    """
    results = []
    for i in range(1, min(count + 1, 6)):  # images 1-5
        image_path = PROJECT_ROOT / f"{i}.jpg"
        if image_path.exists():
            data = image_path.read_bytes()
            filename = f"multi_{i}.jpg"
            uri = await mesh.upload_media(data, filename, "image/jpeg")
            results.append(
                mesh.media_result(
                    uri=uri,
                    name=f"Image {i}",
                    mime_type="image/jpeg",
                    size=len(data),
                )
            )
    return results


@app.tool()
@mesh.tool(
    capability="mixed_content_provider",
    description="Returns mixed text + image content",
)
async def get_mixed_content(image_number: int = 1) -> list:
    """Return a mix of text and image content.

    Args:
        image_number: Which image to include (1 or 2).
    """
    from mcp.types import TextContent

    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(f"Image {image_number}.jpg not found")

    data = image_path.read_bytes()
    uri = await mesh.upload_media(data, f"mixed_{image_number}.jpg", "image/jpeg")

    return [
        TextContent(
            type="text",
            text=f"Here is image #{image_number} along with this description.",
        ),
        mesh.media_result(
            uri=uri,
            name=f"Image {image_number}",
            mime_type="image/jpeg",
            size=len(data),
        ),
        TextContent(type="text", text="Please analyze the image above."),
    ]


@app.tool()
@mesh.tool(
    capability="document_provider",
    description="Returns a markdown document as resource_link",
)
async def get_document() -> ResourceLink:
    """Return a markdown document (non-image) as resource_link."""
    content = (
        "# Test Document\n\n"
        "This is a test document to verify non-image resource_link handling.\n\n"
        "## Section 1\nSome content here."
    )
    uri = await mesh.upload_media(content.encode(), "test_doc.md", "text/markdown")
    return mesh.media_result(
        uri=uri,
        name="Test Document",
        mime_type="text/markdown",
        size=len(content.encode()),
    )


@mesh.agent(
    name="image-tool",
    version="1.0.0",
    description="Provides real JPG images for multimodal testing",
    http_port=9206,
    enable_http=True,
    auto_run=True,
)
class ImageToolAgent:
    pass
