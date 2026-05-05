"""Unit tests for ``_mcp_mesh.media.resolver`` vendor dispatch.

Background:
    Issue #860 moved LLM content-block translation upstream — the mesh
    emitter is now the source of vendor-native shape on the native dispatch
    path (e.g. ``_provider_agentic_loop`` calling ``anthropic_native``),
    while the LiteLLM fallback path keeps emitting OpenAI-shape blocks for
    LiteLLM's adapters to translate.

    The resolver is the single source of vendor-native shape — these tests
    pin its formatter contract so that:

    * a regression in ``_VENDOR_FORMATTERS`` is caught at unit-test time,
      not at end-to-end test time on a real provider call;
    * the relationship between "ask the resolver for vendor X" and "get a
      block the vendor's API will accept" is explicit;
    * future formatter changes (e.g. real Gemini-native ``inline_data``
      from the resolver instead of the current OpenAI-alias) are visible
      diffs to these tests.

    No vendor SDK is required to run these tests — they exercise pure
    formatting logic with stub byte data and ``patch``ed media stores.
"""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from _mcp_mesh.media.resolver import (
    _VENDOR_FORMATTERS,
    _format_for_claude,
    _format_for_gemini,
    _format_for_openai,
    resolve_resource_links,
)


# ---------------------------------------------------------------------------
# Vendor formatter mapping
# ---------------------------------------------------------------------------


class TestVendorFormatterMap:
    """Pin the vendor → formatter dispatch table directly. The mapping is the
    contract upstream callers rely on; if a vendor key is removed or its
    formatter is swapped, downstream code (helpers.py, native adapters)
    breaks silently — make it explicit."""

    def test_anthropic_routes_to_claude_formatter(self):
        assert _VENDOR_FORMATTERS["anthropic"] is _format_for_claude

    def test_openai_routes_to_openai_formatter(self):
        assert _VENDOR_FORMATTERS["openai"] is _format_for_openai

    def test_gemini_aliases_route_to_gemini_formatter(self):
        # ``_format_for_gemini`` is currently aliased to ``_format_for_openai``
        # because LiteLLM's gemini adapter expects OpenAI-shape input. When
        # we eventually emit native ``inline_data`` from the resolver, the
        # alias will be replaced — this test pins the dispatch keys, not the
        # alias.
        assert _VENDOR_FORMATTERS["gemini"] is _format_for_gemini
        assert _VENDOR_FORMATTERS["google"] is _format_for_gemini
        assert _VENDOR_FORMATTERS["vertex_ai"] is _format_for_gemini


# ---------------------------------------------------------------------------
# Per-formatter shape contracts
# ---------------------------------------------------------------------------


class TestFormatterShapes:
    """Each formatter emits a well-defined block shape that the corresponding
    vendor's API (Claude / OpenAI / Gemini-via-LiteLLM) accepts. Pin those
    shapes so that a downstream API rejecting the block surfaces at unit
    test time."""

    def test_claude_formatter_emits_anthropic_image_block(self):
        block = _format_for_claude("BASE64DATA", "image/png")
        assert block == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "BASE64DATA",
            },
        }

    def test_openai_formatter_emits_image_url_data_uri(self):
        block = _format_for_openai("BASE64DATA", "image/jpeg")
        assert block == {
            "type": "image_url",
            "image_url": {
                "url": "data:image/jpeg;base64,BASE64DATA",
                "detail": "high",
            },
        }

    def test_gemini_formatter_currently_emits_openai_shape(self):
        """Pinning the alias: today the gemini formatter is OpenAI-shape so
        LiteLLM's gemini adapter handles conversion. When this test starts
        failing because the formatter was switched to native ``inline_data``,
        update the assertion AND verify ``gemini_native``'s translator is a
        no-op for the new shape."""
        block = _format_for_gemini("BASE64DATA", "image/png")
        assert block == {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,BASE64DATA",
                "detail": "high",
            },
        }


# ---------------------------------------------------------------------------
# resolve_resource_links: end-to-end vendor dispatch on a resource_link
# ---------------------------------------------------------------------------


class TestResolveResourceLinksVendorDispatch:
    """Verify the public ``resolve_resource_links`` entry point picks the
    correct formatter based on the ``vendor`` arg. This is the call site
    that ``mesh/helpers.py:_execute_tool_calls_for_iteration`` and
    ``mesh_llm_agent._resolve_media_in_tool_results`` invoke — its vendor
    contract is what issue #860 is about."""

    def _patched_store(self, payload: bytes, mime: str):
        store_mock = AsyncMock()
        store_mock.fetch = AsyncMock(return_value=(payload, mime))
        return patch(
            "_mcp_mesh.media.resolver.get_media_store",
            return_value=store_mock,
        )

    @pytest.mark.asyncio
    async def test_resource_link_image_with_anthropic_vendor_returns_claude_block(
        self,
    ):
        resource_link = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///tmp/cat.png",
                "mimeType": "image/png",
                "name": "cat.png",
            },
        }
        png_bytes = b"\x89PNG\r\n\x1a\n"
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")

        with self._patched_store(png_bytes, "image/png"):
            parts = await resolve_resource_links(resource_link, "anthropic")

        assert parts == [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": expected_b64,
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_resource_link_image_with_openai_vendor_returns_image_url(self):
        resource_link = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///tmp/cat.png",
                "mimeType": "image/png",
                "name": "cat.png",
            },
        }
        png_bytes = b"\x89PNG\r\n\x1a\n"
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")

        with self._patched_store(png_bytes, "image/png"):
            parts = await resolve_resource_links(resource_link, "openai")

        assert parts == [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{expected_b64}",
                    "detail": "high",
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_resource_link_image_with_gemini_vendor_returns_image_url(self):
        """Gemini formatter is aliased to OpenAI today (see
        ``TestFormatterShapes.test_gemini_formatter_currently_emits_openai_shape``).
        LiteLLM's gemini adapter handles conversion to native ``inline_data``."""
        resource_link = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///tmp/cat.png",
                "mimeType": "image/png",
                "name": "cat.png",
            },
        }
        png_bytes = b"\x89PNG\r\n\x1a\n"
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")

        with self._patched_store(png_bytes, "image/png"):
            parts = await resolve_resource_links(resource_link, "gemini")

        assert parts == [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{expected_b64}",
                    "detail": "high",
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_resource_link_image_with_unknown_vendor_falls_back_to_openai(self):
        """Unknown vendor → OpenAI formatter (the safe default that LiteLLM
        accepts). Pin this so a typo in the vendor string doesn't silently
        produce something Anthropic-shaped going to OpenAI."""
        resource_link = {
            "type": "resource_link",
            "resource": {
                "uri": "file:///tmp/cat.png",
                "mimeType": "image/png",
                "name": "cat.png",
            },
        }
        png_bytes = b"\x89PNG\r\n\x1a\n"
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")

        with self._patched_store(png_bytes, "image/png"):
            parts = await resolve_resource_links(resource_link, "claude")  # not in map

        # ``claude`` is not in ``_VENDOR_FORMATTERS`` (only "anthropic" is) —
        # so the resolver falls back to ``_format_for_openai``.
        assert parts == [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{expected_b64}",
                    "detail": "high",
                },
            }
        ]
