"""Unit tests for media resolver — resource_link to provider-native multimodal."""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the Python runtime source to the path so imports work outside tox
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

from _mcp_mesh.media.resolver import (
    IMAGE_MIME_TYPES,
    _has_resource_link,
    resolve_media_as_user_message,
    resolve_resource_links,
    resolve_resource_links_for_tool_message,
)

# Shared test fixtures
FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-data"
FAKE_PNG_B64 = base64.b64encode(FAKE_PNG_BYTES).decode("ascii")


def _make_resource_link(
    uri: str = "file:///tmp/test.png",
    name: str = "test.png",
    mime_type: str = "image/png",
) -> dict:
    """Build a resource_link dict matching the format from ContentExtractor."""
    result = {
        "type": "resource_link",
        "resource": {
            "uri": uri,
            "name": name,
        },
    }
    if mime_type:
        result["resource"]["mimeType"] = mime_type
    return result


def _mock_media_store(data: bytes = FAKE_PNG_BYTES, mime: str = "image/png"):
    """Return a mock MediaStore whose fetch() returns (data, mime)."""
    store = MagicMock()
    store.fetch = AsyncMock(return_value=(data, mime))
    return store


# ---------------------------------------------------------------------------
# test: image resource_link -> Claude format
# ---------------------------------------------------------------------------
class TestResolveImageResourceLinkClaude:
    @pytest.mark.asyncio
    async def test_returns_claude_image_block(self):
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "anthropic")

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "image"
        assert part["source"]["type"] == "base64"
        assert part["source"]["media_type"] == "image/png"
        assert part["source"]["data"] == FAKE_PNG_B64
        mock_store.fetch.assert_awaited_once_with("file:///tmp/test.png")


# ---------------------------------------------------------------------------
# test: image resource_link -> OpenAI format
# ---------------------------------------------------------------------------
class TestResolveImageResourceLinkOpenAI:
    @pytest.mark.asyncio
    async def test_returns_openai_data_url(self):
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "openai")

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "image_url"
        assert part["image_url"]["detail"] == "high"
        expected_url = f"data:image/png;base64,{FAKE_PNG_B64}"
        assert part["image_url"]["url"] == expected_url

    @pytest.mark.asyncio
    async def test_gemini_uses_openai_format(self):
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "gemini")

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# test: non-image resource_link -> text passthrough
# ---------------------------------------------------------------------------
class TestResolveNonImagePassthrough:
    @pytest.mark.asyncio
    async def test_text_markdown_becomes_text_description(self):
        resource_link = _make_resource_link(
            uri="file:///tmp/readme.md",
            name="readme.md",
            mime_type="text/markdown",
        )

        # No need to mock MediaStore — should not be called for non-image
        parts = await resolve_resource_links(resource_link, "anthropic")

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "text"
        assert "readme.md" in part["text"]
        assert "text/markdown" in part["text"]

    @pytest.mark.asyncio
    async def test_application_pdf_becomes_text_description(self):
        resource_link = _make_resource_link(
            uri="s3://bucket/report.pdf",
            name="report.pdf",
            mime_type="application/pdf",
        )

        parts = await resolve_resource_links(resource_link, "openai")

        assert len(parts) == 1
        assert parts[0]["type"] == "text"
        assert "report.pdf" in parts[0]["text"]


# ---------------------------------------------------------------------------
# test: plain text result -> wrapped unchanged
# ---------------------------------------------------------------------------
class TestResolvePlainTextUnchanged:
    @pytest.mark.asyncio
    async def test_string_becomes_text_block(self):
        parts = await resolve_resource_links("hello world", "anthropic")

        assert len(parts) == 1
        assert parts[0] == {"type": "text", "text": "hello world"}

    @pytest.mark.asyncio
    async def test_dict_without_type_becomes_json_text(self):
        data = {"answer": 42, "status": "ok"}
        parts = await resolve_resource_links(data, "openai")

        assert len(parts) == 1
        assert parts[0]["type"] == "text"
        assert json.loads(parts[0]["text"]) == data


# ---------------------------------------------------------------------------
# test: multi_content with mixed text + resource_link
# ---------------------------------------------------------------------------
class TestResolveMultiContent:
    @pytest.mark.asyncio
    async def test_mixed_multi_content(self):
        multi = {
            "type": "multi_content",
            "items": [
                "Here is the analysis:",
                _make_resource_link(
                    uri="file:///tmp/chart.png",
                    name="chart.png",
                    mime_type="image/png",
                ),
                {"answer": "some text result"},
            ],
        }
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(multi, "anthropic")

        assert len(parts) == 3
        # First: text part
        assert parts[0] == {"type": "text", "text": "Here is the analysis:"}
        # Second: image part (Claude format)
        assert parts[1]["type"] == "image"
        assert parts[1]["source"]["data"] == FAKE_PNG_B64
        # Third: dict serialized as text
        assert parts[2]["type"] == "text"
        assert json.loads(parts[2]["text"]) == {"answer": "some text result"}

    @pytest.mark.asyncio
    async def test_multi_content_with_content_key(self):
        """multi_content from proxy uses 'content' key instead of 'items'."""
        multi = {
            "type": "multi_content",
            "content": [
                _make_resource_link(
                    uri="file:///tmp/photo.jpeg",
                    name="photo.jpeg",
                    mime_type="image/jpeg",
                ),
            ],
        }
        mock_store = _mock_media_store(mime="image/jpeg")

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(multi, "openai")

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# test: graceful fallback when MediaStore fetch fails
# ---------------------------------------------------------------------------
class TestResolveNoMediaStore:
    @pytest.mark.asyncio
    async def test_fetch_failure_falls_back_to_text(self):
        resource_link = _make_resource_link()
        mock_store = MagicMock()
        mock_store.fetch = AsyncMock(side_effect=FileNotFoundError("not found"))

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "anthropic")

        assert len(parts) == 1
        part = parts[0]
        assert part["type"] == "text"
        assert "fetch failed" in part["text"]
        assert "test.png" in part["text"]

    @pytest.mark.asyncio
    async def test_store_exception_falls_back_to_text(self):
        resource_link = _make_resource_link()
        mock_store = MagicMock()
        mock_store.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "openai")

        assert len(parts) == 1
        assert parts[0]["type"] == "text"
        assert "fetch failed" in parts[0]["text"]


# ---------------------------------------------------------------------------
# test: _has_resource_link helper
# ---------------------------------------------------------------------------
class TestHasResourceLink:
    def test_resource_link_dict(self):
        assert _has_resource_link(_make_resource_link()) is True

    def test_multi_content_with_resource_link(self):
        multi = {
            "type": "multi_content",
            "items": [
                "text",
                _make_resource_link(),
            ],
        }
        assert _has_resource_link(multi) is True

    def test_multi_content_without_resource_link(self):
        multi = {
            "type": "multi_content",
            "items": ["just text", {"answer": 42}],
        }
        assert _has_resource_link(multi) is False

    def test_plain_string(self):
        assert _has_resource_link("hello") is False

    def test_plain_dict(self):
        assert _has_resource_link({"answer": 42}) is False

    def test_none(self):
        assert _has_resource_link(None) is False


# ---------------------------------------------------------------------------
# test: all image mime types are supported
# ---------------------------------------------------------------------------
class TestImageMimeTypes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mime", sorted(IMAGE_MIME_TYPES))
    async def test_all_image_mimes_resolve(self, mime):
        ext = mime.split("/")[1]
        resource_link = _make_resource_link(
            uri=f"file:///tmp/test.{ext}",
            name=f"test.{ext}",
            mime_type=mime,
        )
        mock_store = _mock_media_store(mime=mime)

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "anthropic")

        assert len(parts) == 1
        assert parts[0]["type"] == "image"


# ---------------------------------------------------------------------------
# test: unknown vendor falls back to OpenAI format
# ---------------------------------------------------------------------------
class TestUnknownVendor:
    @pytest.mark.asyncio
    async def test_unknown_vendor_uses_openai_format(self):
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links(resource_link, "some_unknown_vendor")

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# test: resolve_resource_links_for_tool_message — vendor-aware tool content
# ---------------------------------------------------------------------------
class TestResolveForToolMessage:
    @pytest.mark.asyncio
    async def test_claude_returns_full_image_inline(self):
        """Anthropic supports images in tool messages — image should be inline."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links_for_tool_message(
                resource_link, "anthropic"
            )

        assert len(parts) == 1
        assert parts[0]["type"] == "image"
        assert parts[0]["source"]["data"] == FAKE_PNG_B64

    @pytest.mark.asyncio
    async def test_openai_returns_text_placeholder(self):
        """OpenAI does NOT support images in tool messages — should get placeholder."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links_for_tool_message(
                resource_link, "openai"
            )

        assert len(parts) == 1
        assert parts[0]["type"] == "text"
        assert "see next message" in parts[0]["text"].lower()

    @pytest.mark.asyncio
    async def test_gemini_returns_text_placeholder(self):
        """Gemini does NOT support images in tool messages — should get placeholder."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            parts = await resolve_resource_links_for_tool_message(
                resource_link, "gemini"
            )

        assert len(parts) == 1
        assert parts[0]["type"] == "text"
        assert "see next message" in parts[0]["text"].lower()

    @pytest.mark.asyncio
    async def test_plain_text_unchanged_for_openai(self):
        """Non-image results pass through unchanged regardless of vendor."""
        parts = await resolve_resource_links_for_tool_message(
            "hello world", "openai"
        )
        assert len(parts) == 1
        assert parts[0] == {"type": "text", "text": "hello world"}


# ---------------------------------------------------------------------------
# test: resolve_media_as_user_message — separate user message for images
# ---------------------------------------------------------------------------
class TestResolveMediaAsUserMessage:
    @pytest.mark.asyncio
    async def test_claude_returns_none(self):
        """Anthropic doesn't need a separate user message — image is inline."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            msg = await resolve_media_as_user_message(resource_link, "anthropic")

        assert msg is None

    @pytest.mark.asyncio
    async def test_openai_returns_user_message_with_image(self):
        """OpenAI should get a user message with the image."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            msg = await resolve_media_as_user_message(resource_link, "openai")

        assert msg is not None
        assert msg["role"] == "user"
        content = msg["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert "tool returned" in content[0]["text"].lower()
        assert content[1]["type"] == "image_url"
        expected_url = f"data:image/png;base64,{FAKE_PNG_B64}"
        assert content[1]["image_url"]["url"] == expected_url

    @pytest.mark.asyncio
    async def test_gemini_returns_user_message_with_image(self):
        """Gemini should get a user message with the image."""
        resource_link = _make_resource_link()
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            msg = await resolve_media_as_user_message(resource_link, "gemini")

        assert msg is not None
        assert msg["role"] == "user"
        assert len(msg["content"]) == 2
        assert msg["content"][1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_no_image_returns_none(self):
        """Non-image resource_links should not produce a user message."""
        resource_link = _make_resource_link(
            uri="file:///tmp/readme.md",
            name="readme.md",
            mime_type="text/markdown",
        )

        msg = await resolve_media_as_user_message(resource_link, "openai")
        assert msg is None

    @pytest.mark.asyncio
    async def test_plain_text_returns_none(self):
        """Plain text tool results should not produce a user message."""
        msg = await resolve_media_as_user_message("hello", "openai")
        assert msg is None

    @pytest.mark.asyncio
    async def test_multi_content_with_image(self):
        """multi_content with an image should produce a user message for OpenAI."""
        multi = {
            "type": "multi_content",
            "items": [
                "Here is the chart:",
                _make_resource_link(
                    uri="file:///tmp/chart.png",
                    name="chart.png",
                    mime_type="image/png",
                ),
            ],
        }
        mock_store = _mock_media_store()

        with patch(
            "_mcp_mesh.media.resolver.get_media_store", return_value=mock_store
        ):
            msg = await resolve_media_as_user_message(multi, "openai")

        assert msg is not None
        assert msg["role"] == "user"
        content = msg["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
