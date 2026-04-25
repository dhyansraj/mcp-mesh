"""
Unit tests for ProviderHandlerRegistry vendor routing.

Covers:
- Built-in handler selection for known vendors (anthropic, openai, gemini)
- The vertex_ai -> GeminiHandler alias added for issue #816
- Cache behavior across the gemini/vertex_ai aliases
- Fallback to GenericHandler for unknown vendors
- list_vendors visibility of the alias
"""

import pytest

from _mcp_mesh.engine.provider_handlers.claude_handler import ClaudeHandler
from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler
from _mcp_mesh.engine.provider_handlers.generic_handler import GenericHandler
from _mcp_mesh.engine.provider_handlers.openai_handler import OpenAIHandler
from _mcp_mesh.engine.provider_handlers.provider_handler_registry import (
    ProviderHandlerRegistry,
)


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """Each test starts with an empty handler instance cache."""
    ProviderHandlerRegistry.clear_cache()
    yield
    ProviderHandlerRegistry.clear_cache()


class TestBuiltInVendorRouting:
    """Sanity: known vendors resolve to their dedicated handler classes."""

    def test_anthropic_routes_to_claude_handler(self):
        handler = ProviderHandlerRegistry.get_handler("anthropic")
        assert isinstance(handler, ClaudeHandler)

    def test_openai_routes_to_openai_handler(self):
        handler = ProviderHandlerRegistry.get_handler("openai")
        assert isinstance(handler, OpenAIHandler)

    def test_gemini_routes_to_gemini_handler(self):
        handler = ProviderHandlerRegistry.get_handler("gemini")
        assert isinstance(handler, GeminiHandler)


class TestVertexAiAlias:
    """Issue #816: vertex_ai must route through GeminiHandler."""

    def test_vertex_ai_alias_routes_to_gemini_handler(self):
        handler = ProviderHandlerRegistry.get_handler("vertex_ai")
        assert isinstance(handler, GeminiHandler)

    def test_vertex_ai_alias_visible_via_list_vendors(self):
        vendors = ProviderHandlerRegistry.list_vendors()
        assert vendors.get("vertex_ai") == "GeminiHandler"
        assert vendors.get("gemini") == "GeminiHandler"

    def test_vertex_ai_and_gemini_cache_distinctly(self):
        """Both vendor keys map to GeminiHandler but are cached as distinct
        instances.

        Acceptable since vendor is mostly metadata (used for logs and the
        media/PDF formatting branch in resolver.py, where 'gemini' and
        'google' both take the same path — vertex_ai routing is otherwise
        identical). The minor memory cost of two cached singletons is
        worth keeping the registry logic trivial and avoiding alias-
        collapsing magic in get_handler.
        """
        h1 = ProviderHandlerRegistry.get_handler("vertex_ai")
        h2 = ProviderHandlerRegistry.get_handler("gemini")

        assert isinstance(h1, GeminiHandler)
        assert isinstance(h2, GeminiHandler)
        assert h1 is not h2  # distinct cache entries

        # Cache hit returns the same instance for the same vendor key
        assert ProviderHandlerRegistry.get_handler("vertex_ai") is h1
        assert ProviderHandlerRegistry.get_handler("gemini") is h2

    def test_vertex_ai_handler_reports_gemini_vendor(self):
        """GeminiHandler hardcodes vendor='gemini' in __init__, so the
        instance returned for 'vertex_ai' will report vendor='gemini'.
        This is intentional — downstream vendor-based branching (e.g.,
        resolver._VENDOR_FORMATTERS) treats both as the same Gemini
        family. Logs may show vendor=gemini for vertex_ai calls."""
        handler = ProviderHandlerRegistry.get_handler("vertex_ai")
        assert handler.vendor == "gemini"


class TestUnknownVendorFallback:
    """Unknown / None / empty vendors fall back to GenericHandler."""

    def test_unknown_vendor_returns_generic_handler(self):
        handler = ProviderHandlerRegistry.get_handler("totally-not-a-vendor")
        assert isinstance(handler, GenericHandler)

    def test_none_vendor_returns_generic_handler(self):
        handler = ProviderHandlerRegistry.get_handler(None)
        assert isinstance(handler, GenericHandler)

    def test_empty_vendor_returns_generic_handler(self):
        handler = ProviderHandlerRegistry.get_handler("")
        assert isinstance(handler, GenericHandler)
