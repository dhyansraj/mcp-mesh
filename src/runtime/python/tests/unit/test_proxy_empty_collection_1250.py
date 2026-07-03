"""Consumer-side unit tests for empty-collection recovery (issue #1250).

A typed Python provider that returns ``[]`` emits empty content plus
``structuredContent {"result": []}`` with a ``fastmcp.wrap_result`` meta
marker. The proxy must recover the value from structuredContent instead of
collapsing empty content to ``None``, while a genuine ``None`` return (empty
content, no structuredContent) still resolves to ``None``.

Covers both consumer transports:
  * ``_convert_mcp_result_to_python`` (FastMCP client CallToolResult path)
  * ``_normalize_http_result`` (direct HTTP JSON-envelope path)
"""

from __future__ import annotations

from typing import Any

import pytest

from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy


class _FakeCallToolResult:
    """Minimal stand-in for mcp.types.CallToolResult."""

    def __init__(
        self,
        content: list[Any],
        structuredContent: Any | None = None,
        meta: Any | None = None,
        isError: bool = False,
    ):
        self.content = content
        self.structuredContent = structuredContent
        self.meta = meta
        self.isError = isError


def _proxy() -> UnifiedMCPProxy:
    return UnifiedMCPProxy(endpoint="http://fake:9000", function_name="get_items")


_WRAP_META = {"fastmcp": {"wrap_result": True}}


# ---------------------------------------------------------------------------
# FastMCP client path: _convert_mcp_result_to_python
# ---------------------------------------------------------------------------


def test_client_empty_content_with_wrapped_structured_recovers_empty_list():
    proxy = _proxy()
    result = _FakeCallToolResult(
        content=[], structuredContent={"result": []}, meta=_WRAP_META
    )
    assert proxy._convert_mcp_result_to_python(result) == []


def test_client_empty_content_no_structured_stays_none():
    proxy = _proxy()
    result = _FakeCallToolResult(content=[], structuredContent=None, meta=None)
    assert proxy._convert_mcp_result_to_python(result) is None


def test_client_empty_content_structured_without_marker_not_unwrapped():
    """A legit {"result": ...} payload lacking the wrap marker is returned
    verbatim (never blindly unwrapped)."""
    proxy = _proxy()
    result = _FakeCallToolResult(
        content=[], structuredContent={"result": [1, 2]}, meta=None
    )
    assert proxy._convert_mcp_result_to_python(result) == {"result": [1, 2]}


def test_client_empty_content_empty_dict_structured_recovers_empty_dict():
    """A falsy-but-present structuredContent ``{}`` must recover as ``{}`` (not
    be treated as absent → None). Byte-identical to Java/TS on degenerate
    payloads."""
    proxy = _proxy()
    result = _FakeCallToolResult(content=[], structuredContent={}, meta=None)
    assert proxy._convert_mcp_result_to_python(result) == {}


# ---------------------------------------------------------------------------
# HTTP path: _normalize_http_result
# ---------------------------------------------------------------------------


def test_http_empty_content_with_wrapped_structured_recovers_empty_list():
    proxy = _proxy()
    envelope = {
        "content": [],
        "structuredContent": {"result": []},
        "_meta": _WRAP_META,
    }
    assert proxy._normalize_http_result(envelope) == []


def test_http_empty_content_no_structured_stays_none():
    proxy = _proxy()
    envelope = {"content": []}
    assert proxy._normalize_http_result(envelope) is None


def test_http_empty_content_structured_without_marker_not_unwrapped():
    proxy = _proxy()
    envelope = {"content": [], "structuredContent": {"result": [1, 2]}}
    assert proxy._normalize_http_result(envelope) == {"result": [1, 2]}


def test_http_empty_content_empty_dict_structured_recovers_empty_dict():
    proxy = _proxy()
    envelope = {"content": [], "structuredContent": {}}
    assert proxy._normalize_http_result(envelope) == {}


# ---------------------------------------------------------------------------
# Regression: non-empty content unchanged across both paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("[]", []), ("{}", {}), ("", ""), ("[1,2,3]", [1, 2, 3])],
)
def test_client_nonempty_text_content_unchanged(text: str, expected: Any):
    proxy = _proxy()

    class _Item:
        def __init__(self, t):
            self.text = t

    result = _FakeCallToolResult(content=[_Item(text)])
    assert proxy._convert_mcp_result_to_python(result) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("[]", []), ("{}", {}), ("", ""), ("[1,2,3]", [1, 2, 3])],
)
def test_http_nonempty_text_content_unchanged(text: str, expected: Any):
    proxy = _proxy()
    envelope = {"content": [{"type": "text", "text": text}]}
    assert proxy._normalize_http_result(envelope) == expected


# ---------------------------------------------------------------------------
# Marker helper
# ---------------------------------------------------------------------------


def test_is_wrap_result_meta():
    proxy = _proxy()
    assert proxy._is_wrap_result_meta(_WRAP_META) is True
    assert proxy._is_wrap_result_meta({"fastmcp": {"wrap_result": False}}) is False
    assert proxy._is_wrap_result_meta({"fastmcp": {}}) is False
    assert proxy._is_wrap_result_meta({}) is False
    assert proxy._is_wrap_result_meta(None) is False
