"""Provider-side unit tests for empty-collection serialization parity (#1250).

FastMCP collapses an empty list/tuple tool return to an EMPTY content array —
indistinguishable on the wire from a ``None`` return. Java/TS providers always
emit a ``"[]"`` text block. ``patch_empty_collection_serialization`` restores
that parity for the Python provider:

  * ``[]`` / ``()``  → one ``"[]"`` text content block (typed tools keep their
    ``structuredContent {"result": []}`` + ``fastmcp.wrap_result`` marker).
  * ``None``         → empty content, unchanged.
  * non-empty        → unchanged (FastMCP handles it verbatim).
  * async handlers   → covered identically.
"""

from __future__ import annotations

import logging

import pytest
from fastmcp import Client, FastMCP

from _mcp_mesh.pipeline.mcp_startup import fastmcpserver_discovery as fsd
from _mcp_mesh.pipeline.mcp_startup.fastmcpserver_discovery import (
    _wrap_convert_result_for_empty_collection,
    patch_empty_collection_serialization,
)


@pytest.fixture(autouse=True)
def _reset_warn_once():
    """Reset the process-wide warn-once guard between tests."""
    fsd._convert_result_warned.clear()
    yield
    fsd._convert_result_warned.clear()


def _build_app() -> FastMCP:
    app = FastMCP("empty-1250")

    @app.tool()
    def typed_empty() -> list[int]:
        return []

    @app.tool()
    def untyped_empty():
        return []

    @app.tool()
    def empty_tuple():
        return ()

    @app.tool()
    async def async_empty() -> list[int]:
        return []

    @app.tool()
    def none_ret():
        return None

    @app.tool()
    def nonempty() -> list[int]:
        return [1, 2, 3]

    return app


def _text_blocks(result) -> list[str]:
    return [getattr(b, "text", None) for b in result.content if b.type == "text"]


@pytest.mark.asyncio
async def test_patch_is_idempotent():
    app = _build_app()
    first = patch_empty_collection_serialization(app)
    assert first == 6  # every tool component patched once
    assert patch_empty_collection_serialization(app) == 0


@pytest.mark.asyncio
async def test_empty_returns_produce_bracket_text_block():
    app = _build_app()
    patch_empty_collection_serialization(app)
    async with Client(app) as c:
        # Every empty list/tuple return — typed or untyped, sync or async —
        # carries a real "[]" text block the consumer can parse to [].
        for name in ("typed_empty", "untyped_empty", "empty_tuple", "async_empty"):
            r = await c.call_tool(name, {})
            assert _text_blocks(r) == ["[]"], name


@pytest.mark.asyncio
async def test_typed_empty_preserves_structured_content_and_marker():
    app = _build_app()
    patch_empty_collection_serialization(app)
    async with Client(app) as c:
        raw = await c.call_tool_mcp("typed_empty", {})
    assert [b.text for b in raw.content if b.type == "text"] == ["[]"]
    assert raw.structuredContent == {"result": []}
    assert raw.meta == {"fastmcp": {"wrap_result": True}}


@pytest.mark.asyncio
async def test_none_return_stays_empty_content():
    app = _build_app()
    patch_empty_collection_serialization(app)
    async with Client(app) as c:
        r = await c.call_tool("none_ret", {})
    assert r.content == []
    assert r.data is None


@pytest.mark.asyncio
async def test_nonempty_return_unchanged():
    app = _build_app()
    patch_empty_collection_serialization(app)
    async with Client(app) as c:
        r = await c.call_tool("nonempty", {})
    assert [b.text for b in r.content if b.type == "text"] == ["[1,2,3]"]
    assert r.data == [1, 2, 3]


@pytest.mark.asyncio
async def test_missing_local_provider_is_noop():
    class _Bare:
        pass

    assert patch_empty_collection_serialization(_Bare()) == 0


# ---------------------------------------------------------------------------
# Post-discovery registration: tools added AFTER the patch runs (e.g. the
# jobs-helper tools, which register in a later pipeline step) must also be
# patched via the _add_component chokepoint hook.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_registered_after_patch_is_covered():
    app = _build_app()
    # Patch first — mirrors FastMCPServerDiscoveryStep running BEFORE
    # JobsHelperToolsStep registers its framework tools.
    patch_empty_collection_serialization(app)

    # Now register a new tool the way jobs_helper_tools does (server.tool
    # decorator → add_tool → _add_component), AFTER the patch.
    @app.tool(name="__mesh_job_status_like")
    def late_tool() -> list[int]:
        return []

    async with Client(app) as c:
        r = await c.call_tool("__mesh_job_status_like", {})
    assert [b.text for b in r.content if b.type == "text"] == ["[]"]
    assert r.structured_content == {"result": []}


@pytest.mark.asyncio
async def test_add_component_hook_is_idempotent():
    app = _build_app()
    patch_empty_collection_serialization(app)
    first_hook = app.local_provider._add_component
    patch_empty_collection_serialization(app)
    # Hook must not be re-wrapped on a second pass.
    assert app.local_provider._add_component is first_hook


# ---------------------------------------------------------------------------
# Zero-patched is loud: N>0 tools but none patchable → warning naming the
# consequence (parity fix inactive).
# ---------------------------------------------------------------------------


def test_zero_patched_with_tools_present_warns(caplog):
    class _Tool:
        key = "tool:x@"
        # No convert_result attribute → cannot be patched.

    class _Provider:
        def __init__(self):
            self._components = {"tool:x@": _Tool()}

        def _add_component(self, component):  # pragma: no cover - unused here
            self._components[component.key] = component
            return component

    class _Server:
        def __init__(self):
            self.local_provider = _Provider()

    with caplog.at_level(logging.WARNING):
        newly = patch_empty_collection_serialization(_Server())
    assert newly == 0
    assert any("INACTIVE" in rec.message for rec in caplog.records)


def test_components_not_a_dict_warns(caplog):
    class _Provider:
        _components = None  # FastMCP renamed / restructured storage.

    class _Server:
        local_provider = _Provider()

    with caplog.at_level(logging.WARNING):
        newly = patch_empty_collection_serialization(_Server())
    assert newly == 0
    assert any("INACTIVE" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Hot-path hardening: the wrapper must survive a convert_result call-convention
# drift (extra args/kwargs pass through; empty-block errors fall back + warn
# once) rather than breaking every tool call.
# ---------------------------------------------------------------------------


def test_wrapper_passes_through_extra_args_and_kwargs():
    calls = []

    class _Result:
        content = [object()]  # non-empty → no re-wrap

    def orig(raw_value, extra=None, *, kw=None):
        calls.append((raw_value, extra, kw))
        return _Result()

    wrapped = _wrap_convert_result_for_empty_collection(orig)
    out = wrapped([1, 2], "positional", kw="keyword")
    assert isinstance(out, _Result)
    assert calls == [([1, 2], "positional", "keyword")]


def test_wrapper_falls_back_and_warns_once_on_empty_block_error():
    class _BadResult:
        # Accessing .content raises → the empty-detection block errors and
        # must fall back to this very object.
        @property
        def content(self):
            raise RuntimeError("shape drift")

    sentinel = _BadResult()

    def orig(raw_value):
        return sentinel

    wrapped = _wrap_convert_result_for_empty_collection(orig)

    # Empty list would normally trigger re-wrap, but .content blows up.
    assert wrapped([]) is sentinel
    assert wrapped([]) is sentinel  # still fine on subsequent calls
    # Warn-once: exactly one warning recorded across both calls.
    assert len(fsd._convert_result_warned) == 1


def test_wrapper_missing_raw_value_kwarg_is_safe():
    class _Result:
        content = []

    def orig(**kwargs):
        return _Result()

    wrapped = _wrap_convert_result_for_empty_collection(orig)
    # No positional arg and no raw_value → raw_value is None → passthrough.
    out = wrapped(something_else=1)
    assert isinstance(out, _Result)
