#!/usr/bin/env python3
"""
phase3-consumer - Phase 3 LLM Consumer Agent

Demonstrates Phase 3.3 feature: the media= parameter on MeshLlmAgent.__call__.
Uploads images to MediaStore, then passes URIs or raw bytes to the LLM for
vision analysis. Tests various media input modes:

  - media= with a single URI (file:// from MediaStore)
  - media= with raw bytes tuple (bytes, mime_type)
  - media= with multiple URIs
  - media= with mixed URIs and bytes
  - No media (backward compatibility)

Requires an LLM provider that supports vision (e.g., Claude, GPT-4o, Gemini).
"""

import mesh
from fastmcp import FastMCP
from pathlib import Path

app = FastMCP("Phase 3 Consumer")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

IMAGE_DESCRIPTION_PROMPT = (
    "You describe images. When given an image, describe what you see "
    "concisely in 2-3 sentences."
)


# ---------------------------------------------------------------------------
# Test 1: media= with a single URI
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    max_iterations=1,
    system_prompt=IMAGE_DESCRIPTION_PROMPT,
)
@mesh.tool(
    capability="test_media_uri",
    description="Tests LLM media= with a single MediaStore URI",
)
async def test_media_uri(
    image_number: int = 1,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Upload an image to MediaStore, then pass its URI to the LLM."""
    if not llm:
        return "Error: LLM not available"

    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        return f"Error: {image_number}.jpg not found at {PROJECT_ROOT}"

    data = image_path.read_bytes()
    uri = await mesh.upload_media(data, f"uri_test_{image_number}.jpg", "image/jpeg")

    response = await llm(
        f"Describe this image (photo #{image_number}).",
        media=[uri],
    )
    return f"URI Test (image {image_number}):\n{response}"


# ---------------------------------------------------------------------------
# Test 2: media= with raw bytes
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    max_iterations=1,
    system_prompt=IMAGE_DESCRIPTION_PROMPT,
)
@mesh.tool(
    capability="test_media_bytes",
    description="Tests LLM media= with raw (bytes, mime_type) tuple",
)
async def test_media_bytes(
    image_number: int = 2,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Pass raw image bytes directly to the LLM via media= parameter."""
    if not llm:
        return "Error: LLM not available"

    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        return f"Error: {image_number}.jpg not found at {PROJECT_ROOT}"

    data = image_path.read_bytes()

    response = await llm(
        "Describe this image.",
        media=[(data, "image/jpeg")],
    )
    return f"Bytes Test (image {image_number}):\n{response}"


# ---------------------------------------------------------------------------
# Test 3: media= with multiple URIs
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    max_iterations=1,
    system_prompt=(
        "You describe images. When given multiple images, briefly describe "
        "each one in a numbered list."
    ),
)
@mesh.tool(
    capability="test_multi_media",
    description="Tests LLM media= with multiple image URIs",
)
async def test_multi_media(
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Upload multiple images and pass all URIs to the LLM at once."""
    if not llm:
        return "Error: LLM not available"

    uris = []
    for i in [1, 2]:
        image_path = PROJECT_ROOT / f"{i}.jpg"
        if image_path.exists():
            data = image_path.read_bytes()
            uri = await mesh.upload_media(data, f"multi_{i}.jpg", "image/jpeg")
            uris.append(uri)

    if not uris:
        return "Error: No images found in project root"

    response = await llm(
        f"Describe each of these {len(uris)} images briefly.",
        media=uris,
    )
    return f"Multi-URI Test ({len(uris)} images):\n{response}"


# ---------------------------------------------------------------------------
# Test 4: media= with mixed URIs and bytes
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    max_iterations=1,
    system_prompt=(
        "You describe images. When given multiple images, briefly describe "
        "each one in a numbered list."
    ),
)
@mesh.tool(
    capability="test_mixed_media",
    description="Tests LLM media= with mixed URIs and raw bytes",
)
async def test_mixed_media(
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Pass a mix of URI and raw bytes to the LLM via media= parameter."""
    if not llm:
        return "Error: LLM not available"

    media_items = []

    # First image as URI
    img1_path = PROJECT_ROOT / "1.jpg"
    if img1_path.exists():
        data1 = img1_path.read_bytes()
        uri = await mesh.upload_media(data1, "mixed_uri.jpg", "image/jpeg")
        media_items.append(uri)

    # Second image as raw bytes
    img2_path = PROJECT_ROOT / "2.jpg"
    if img2_path.exists():
        data2 = img2_path.read_bytes()
        media_items.append((data2, "image/jpeg"))

    if not media_items:
        return "Error: No images found in project root"

    response = await llm(
        f"Describe each of these {len(media_items)} images. "
        f"The first was sent as a URI, the second as raw bytes.",
        media=media_items,
    )
    return f"Mixed Media Test ({len(media_items)} items):\n{response}"


# ---------------------------------------------------------------------------
# Test 5: No media (backward compatibility)
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    max_iterations=1,
    system_prompt="You are a helpful assistant. Answer concisely.",
)
@mesh.tool(
    capability="test_no_media",
    description="Tests LLM without media= (backward compatibility)",
)
async def test_no_media(
    question: str = "What is 2+2?",
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Plain text LLM call without media -- should work exactly as before."""
    if not llm:
        return "Error: LLM not available"

    response = await llm(question)
    return f"No Media Test:\n{response}"


# ---------------------------------------------------------------------------
# Test 6: media= with OpenAI provider
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["openai", "media"]},
    max_iterations=1,
    system_prompt=IMAGE_DESCRIPTION_PROMPT,
)
@mesh.tool(
    capability="test_media_openai",
    description="Tests LLM media= with OpenAI GPT-4o provider",
)
async def test_media_openai(
    image_number: int = 1,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Upload an image and pass its URI to OpenAI via media= parameter."""
    if not llm:
        return "Error: LLM not available"

    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        return f"Error: {image_number}.jpg not found at {PROJECT_ROOT}"

    data = image_path.read_bytes()
    uri = await mesh.upload_media(data, f"openai_{image_number}.jpg", "image/jpeg")

    response = await llm(
        f"Describe this image (photo #{image_number}).",
        media=[uri],
    )
    return f"OpenAI Media Test (image {image_number}):\n{response}"


# ---------------------------------------------------------------------------
# Test 7: media= with Gemini provider
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini", "media"]},
    max_iterations=1,
    system_prompt=IMAGE_DESCRIPTION_PROMPT,
)
@mesh.tool(
    capability="test_media_gemini",
    description="Tests LLM media= with Google Gemini provider",
)
async def test_media_gemini(
    image_number: int = 1,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Upload an image and pass its URI to Gemini via media= parameter."""
    if not llm:
        return "Error: LLM not available"

    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        return f"Error: {image_number}.jpg not found at {PROJECT_ROOT}"

    data = image_path.read_bytes()
    uri = await mesh.upload_media(data, f"gemini_{image_number}.jpg", "image/jpeg")

    response = await llm(
        f"Describe this image (photo #{image_number}).",
        media=[uri],
    )
    return f"Gemini Media Test (image {image_number}):\n{response}"


# ---------------------------------------------------------------------------
# Test 8: MediaResult -> URI -> media= (end-to-end)
# ---------------------------------------------------------------------------

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude", "media"]},
    filter=[{"capability": "media_result_image"}],
    max_iterations=3,
    system_prompt=(
        "You analyze images. You have a tool that provides images as "
        "resource_links. When asked, use the tool to get an image, then "
        "describe what you see."
    ),
)
@mesh.tool(
    capability="test_e2e_media_result",
    description="End-to-end test: phase3-tool produces MediaResult, LLM analyzes it",
)
async def test_e2e_media_result(
    image_number: int = 1,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """End-to-end: phase3-tool creates MediaResult, provider resolves resource_link."""
    if not llm:
        return "Error: LLM not available"

    response = await llm(
        f"Use the test_media_result_image tool with image_number={image_number} "
        f"to get a photo, then describe what you see in the image."
    )
    return f"E2E MediaResult Test (image {image_number}):\n{response}"


@mesh.agent(
    name="phase3-consumer",
    version="1.0.0",
    description="Tests Phase 3 LLM media= parameter with URI, bytes, and multi-provider support",
    http_port=9211,
    enable_http=True,
    auto_run=True,
)
class Phase3ConsumerAgent:
    pass
