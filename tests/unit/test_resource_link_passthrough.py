"""Unit tests for resource_link handling in proxy and ContentExtractor."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

from _mcp_mesh.shared.content_extractor import ContentExtractor

# ---------------------------------------------------------------------------
# Proxy: _convert_content_item_to_python
# ---------------------------------------------------------------------------


class TestProxyConvertResourceLink:
    """Test _convert_content_item_to_python preserves resource_link fields."""

    @pytest.fixture()
    def proxy(self):
        """Create a minimal proxy-like object with the conversion method."""
        # Import the real class so we test the actual implementation
        from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

        p = object.__new__(UnifiedMCPProxy)
        p.logger = MagicMock()
        return p

    def test_resource_link_basic(self, proxy):
        item = SimpleNamespace(
            type="resource_link",
            uri="file:///tmp/img.png",
            name="img.png",
            mimeType="image/png",
            description=None,
            size=None,
            annotations=None,
        )
        result = proxy._convert_content_item_to_python(item)
        assert result["type"] == "resource_link"
        assert result["resource"]["uri"] == "file:///tmp/img.png"
        assert result["resource"]["name"] == "img.png"
        assert result["resource"]["mimeType"] == "image/png"
        assert "description" not in result["resource"]
        assert "size" not in result["resource"]

    def test_resource_link_all_fields(self, proxy):
        annotations = SimpleNamespace()
        annotations.model_dump = lambda exclude_none=False: {"audience": ["user"]}

        item = SimpleNamespace(
            type="resource_link",
            uri="s3://bucket/media/doc.pdf",
            name="doc.pdf",
            mimeType="application/pdf",
            description="A PDF document",
            size=102400,
            annotations=annotations,
        )
        result = proxy._convert_content_item_to_python(item)
        assert result["type"] == "resource_link"
        assert result["resource"]["uri"] == "s3://bucket/media/doc.pdf"
        assert result["resource"]["name"] == "doc.pdf"
        assert result["resource"]["mimeType"] == "application/pdf"
        assert result["resource"]["description"] == "A PDF document"
        assert result["resource"]["size"] == 102400
        assert result["resource"]["annotations"] == {"audience": ["user"]}

    def test_text_content_still_works(self, proxy):
        """Backward compatibility: text content items are handled as before."""
        item = SimpleNamespace(text="just a string")
        result = proxy._convert_content_item_to_python(item)
        assert result == "just a string"

    def test_text_content_json_still_works(self, proxy):
        item = SimpleNamespace(text='{"key": "value"}')
        result = proxy._convert_content_item_to_python(item)
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# ContentExtractor: _extract_single_content / _extract_multi_content
# ---------------------------------------------------------------------------


class TestContentExtractorResourceLink:
    """Test ContentExtractor handles resource_link items."""

    def test_single_resource_link(self):
        item = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///tmp/audio.wav",
                "name": "audio.wav",
                "mimeType": "audio/wav",
                "description": "Recorded audio",
                "size": 44100,
            },
        }
        result = ContentExtractor._extract_single_content(item)
        assert result["type"] == "resource_link"
        assert result["resource"]["uri"] == "file:///tmp/audio.wav"
        assert result["resource"]["name"] == "audio.wav"
        assert result["resource"]["mimeType"] == "audio/wav"
        assert result["resource"]["description"] == "Recorded audio"
        assert result["resource"]["size"] == 44100

    def test_resource_link_minimal(self):
        item = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///data.bin",
                "name": "data.bin",
            },
        }
        result = ContentExtractor._extract_single_content(item)
        assert result["type"] == "resource_link"
        assert result["resource"]["uri"] == "file:///data.bin"
        assert result["resource"]["name"] == "data.bin"
        assert "mimeType" not in result["resource"]

    def test_multi_content_with_resource_link(self):
        items = [
            {"type": "text", "text": "Here is the file:"},
            {
                "type": "resource_link",
                "resource": {
                    "uri": "file:///report.pdf",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                },
            },
        ]
        result = ContentExtractor._extract_multi_content(items)
        assert result["type"] == "multi_content"
        assert len(result["items"]) == 2
        assert "resource: report.pdf" in result["text_summary"]

    def test_text_only_backward_compat(self):
        """Plain text content still works as before."""
        item = {"type": "text", "text": "hello world"}
        result = ContentExtractor._extract_single_content(item)
        assert result == "hello world"

    def test_text_json_backward_compat(self):
        item = {"type": "text", "text": '{"a": 1}'}
        result = ContentExtractor._extract_single_content(item)
        assert result == {"a": 1}

    def test_image_backward_compat(self):
        item = {"type": "image", "data": "base64==", "mimeType": "image/jpeg"}
        result = ContentExtractor._extract_single_content(item)
        assert result["type"] == "image"
        assert result["data"] == "base64=="
