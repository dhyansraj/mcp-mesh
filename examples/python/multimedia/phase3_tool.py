#!/usr/bin/env python3
"""
phase3-tool - Phase 3 Test Tool Agent

Demonstrates Phase 3.1 + 3.2 features:
  - MediaResult: one-step upload + resource_link convenience class
  - save_upload / save_upload_result: FastAPI UploadFile helpers
  - upload_media / media_result: low-level two-step API

Tools:
  - test_media_result: Upload text via MediaResult, return resource_link
  - test_media_result_image: Upload a real JPG via MediaResult
  - test_save_upload: Simulate save_upload with an in-memory UploadFile
  - test_save_upload_result: Simulate save_upload_result with metadata
  - test_two_step: Explicit upload_media + media_result (existing API, for comparison)
"""

import mesh
from fastmcp import FastMCP
from mcp.types import ResourceLink
from pathlib import Path

app = FastMCP("Phase 3 Tool")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Test 1: MediaResult with text content
# ---------------------------------------------------------------------------

@app.tool()
@mesh.tool(
    capability="media_result_text",
    description="Uploads text via MediaResult and returns a resource_link",
)
async def test_media_result(topic: str = "Test") -> ResourceLink:
    """Generate a markdown report and return it via MediaResult (one-step)."""
    content = (
        f"# Report: {topic}\n\n"
        f"Generated via MediaResult convenience class.\n\n"
        f"## Summary\n"
        f"This report was created to test the Phase 3.1 MediaResult API.\n"
    )
    return await mesh.MediaResult(
        data=content.encode("utf-8"),
        filename=f"report_{topic.lower().replace(' ', '_')}.md",
        mime_type="text/markdown",
        name=f"Report: {topic}",
        description=f"Test report on {topic} via MediaResult",
    )


# ---------------------------------------------------------------------------
# Test 2: MediaResult with a real image
# ---------------------------------------------------------------------------

@app.tool()
@mesh.tool(
    capability="media_result_image",
    description="Uploads a real JPG image via MediaResult and returns a resource_link",
)
async def test_media_result_image(image_number: int = 1) -> ResourceLink:
    """Upload a real JPEG image via MediaResult."""
    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(
            f"Image {image_number}.jpg not found at {PROJECT_ROOT}. "
            f"Expected files: 1.jpg, 2.jpg in the project root."
        )
    data = image_path.read_bytes()
    return await mesh.MediaResult(
        data=data,
        filename=f"photo_{image_number}.jpg",
        mime_type="image/jpeg",
        name=f"Photo {image_number}",
        description=f"Real photo #{image_number} uploaded via MediaResult",
    )


# ---------------------------------------------------------------------------
# Test 3: save_upload (simulated UploadFile)
# ---------------------------------------------------------------------------

class _FakeUploadFile:
    """Minimal UploadFile-compatible object for testing save_upload."""

    def __init__(self, data: bytes, filename: str, content_type: str):
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


@app.tool()
@mesh.tool(
    capability="save_upload_test",
    description="Tests save_upload by creating an in-memory UploadFile",
)
async def test_save_upload(image_number: int = 1) -> str:
    """Simulate a FastAPI upload and save it via mesh.save_upload."""
    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(f"Image {image_number}.jpg not found at {PROJECT_ROOT}")

    data = image_path.read_bytes()
    fake_upload = _FakeUploadFile(data, f"upload_{image_number}.jpg", "image/jpeg")

    uri = await mesh.save_upload(fake_upload)
    return (
        f"save_upload result:\n"
        f"  URI: {uri}\n"
        f"  Original size: {len(data)} bytes"
    )


# ---------------------------------------------------------------------------
# Test 4: save_upload_result (full metadata)
# ---------------------------------------------------------------------------

@app.tool()
@mesh.tool(
    capability="save_upload_result_test",
    description="Tests save_upload_result returning full MediaUpload metadata",
)
async def test_save_upload_result(image_number: int = 2) -> str:
    """Simulate a FastAPI upload and get full metadata via save_upload_result."""
    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(f"Image {image_number}.jpg not found at {PROJECT_ROOT}")

    data = image_path.read_bytes()
    fake_upload = _FakeUploadFile(data, f"detailed_{image_number}.jpg", "image/jpeg")

    result = await mesh.save_upload_result(fake_upload)
    return (
        f"save_upload_result metadata:\n"
        f"  URI:  {result.uri}\n"
        f"  Name: {result.name}\n"
        f"  MIME: {result.mime_type}\n"
        f"  Size: {result.size} bytes"
    )


# ---------------------------------------------------------------------------
# Test 5: Two-step upload_media + media_result (existing Phase 1 API)
# ---------------------------------------------------------------------------

@app.tool()
@mesh.tool(
    capability="two_step_upload",
    description="Uses the two-step upload_media + media_result API",
)
async def test_two_step(image_number: int = 1) -> ResourceLink:
    """Upload via the explicit two-step API for comparison with MediaResult."""
    image_path = PROJECT_ROOT / f"{image_number}.jpg"
    if not image_path.exists():
        raise ValueError(f"Image {image_number}.jpg not found at {PROJECT_ROOT}")

    data = image_path.read_bytes()
    uri = await mesh.upload_media(
        data=data,
        filename=f"twostep_{image_number}.jpg",
        mime_type="image/jpeg",
    )
    return mesh.media_result(
        uri=uri,
        name=f"Two-Step Photo {image_number}",
        mime_type="image/jpeg",
        description=f"Photo #{image_number} uploaded via two-step API",
        size=len(data),
    )


@mesh.agent(
    name="phase3-tool",
    version="1.0.0",
    description="Tests Phase 3 MediaResult, save_upload, and two-step media APIs",
    http_port=9210,
    enable_http=True,
    auto_run=True,
)
class Phase3ToolAgent:
    pass
