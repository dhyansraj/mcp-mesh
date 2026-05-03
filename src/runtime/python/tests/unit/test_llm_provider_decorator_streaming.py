"""Unit tests for the auto-generated streaming variant in @mesh.llm_provider.

Phase 3 of the mesh-delegate streaming work for issue #849.

The decorator now generates TWO tools per ``@mesh.llm_provider``-decorated
function: the existing buffered ``<name>`` (returns a message dict) and a new
streaming ``<name>_stream`` (yields ``mesh.Stream[str]`` text chunks). Both
share the same capability + tags so consumers can soft-fall-back to the
buffered variant when no streaming tool is registered (handled in Phase 4
by ``MeshLlmAgent._stream_mesh_delegated``).

These tests pin down:
  * Both tools are registered on the FastMCP app.
  * The streaming tool has ``metadata["stream_type"] == "text"`` so the
    runtime forwards chunks via FastMCP progress notifications.
  * Two ``@mesh.llm_provider`` in one module register 4 distinct tools
    (regression for issue #227 — name conflicts between providers).
  * Calling the streaming tool yields chunks from the underlying provider
    loop.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_module_with_app(module_name: str = "test_module"):
    """Create a fake module with a FastMCP ``app`` attribute.

    @mesh.llm_provider looks up the ``app`` via ``sys.modules[func.__module__]``,
    so we have to register a real module entry. We also clear the
    DecoratorRegistry's mesh_tools dict to keep tests isolated — the registry
    is class-level state shared across the whole test run.
    """
    from fastmcp import FastMCP

    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    mod = types.ModuleType(module_name)
    mod.app = FastMCP(module_name)
    sys.modules[module_name] = mod
    # Snapshot existing tools so we can restore after the test.
    DecoratorRegistry._test_snapshot = dict(DecoratorRegistry._mesh_tools)
    DecoratorRegistry._mesh_tools.clear()
    return mod


def _drop_module(module_name: str):
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    sys.modules.pop(module_name, None)
    snapshot = getattr(DecoratorRegistry, "_test_snapshot", None)
    if snapshot is not None:
        DecoratorRegistry._mesh_tools.clear()
        DecoratorRegistry._mesh_tools.update(snapshot)
        del DecoratorRegistry._test_snapshot


def _make_provider_in_module(mod, module_name: str, func_name: str, **kwargs):
    """Build a function whose ``__module__`` matches ``module_name`` BEFORE
    @mesh.llm_provider is applied.

    The decorator looks up the FastMCP ``app`` via
    ``sys.modules[func.__module__]``, so the function's ``__module__`` must
    be set before decoration.
    """
    import mesh

    def placeholder():
        pass

    placeholder.__name__ = func_name
    placeholder.__qualname__ = func_name
    placeholder.__module__ = module_name
    decorated = mesh.llm_provider(**kwargs)(placeholder)
    setattr(mod, func_name, decorated)
    return decorated


# ---------------------------------------------------------------------------
# Both tools are registered
# ---------------------------------------------------------------------------


class TestStreamingVariantRegistered:
    @pytest.mark.asyncio
    async def test_both_tools_present_after_decoration(self):
        module_name = "_test_llm_provider_streaming_both_tools"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude", "test"],
                version="1.0.0",
            )

            registered = await mod.app.list_tools()
            tool_names = {t.name for t in registered}

            assert "claude_provider" in tool_names
            assert "claude_provider_stream" in tool_names
        finally:
            _drop_module(module_name)

    @pytest.mark.asyncio
    async def test_streaming_tool_advertises_stream_type_text(self):
        module_name = "_test_llm_provider_streaming_meta"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude"],
            )

            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            stream_meta = mesh_tools.get("claude_provider_stream")
            assert stream_meta is not None, (
                "@mesh.tool metadata for streaming variant not registered"
            )
            assert stream_meta.metadata.get("stream_type") == "text"

            # The buffered tool must NOT have stream_type stamped.
            buffered_meta = mesh_tools.get("claude_provider")
            assert buffered_meta is not None
            assert "stream_type" not in buffered_meta.metadata
        finally:
            _drop_module(module_name)

    @pytest.mark.asyncio
    async def test_streaming_tool_shares_capability_and_version(self):
        """Soft-fallback works because both tools advertise the same capability+version.

        Tags differ by exactly one entry: the streaming variant carries the
        ``ai.mcpmesh.stream`` discrimination tag (Phase 5C, issue #849), the
        buffered variant does not. All user-supplied tags appear on both.
        """
        module_name = "_test_llm_provider_streaming_caps"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude", "fast"],
                version="2.1.0",
            )

            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            buffered = mesh_tools["claude_provider"].metadata
            stream = mesh_tools["claude_provider_stream"].metadata

            assert buffered["capability"] == stream["capability"] == "llm"
            assert buffered["version"] == stream["version"] == "2.1.0"
            # User-supplied tags are present on both variants.
            for t in ("claude", "fast"):
                assert t in buffered["tags"]
                assert t in stream["tags"]
        finally:
            _drop_module(module_name)

    @pytest.mark.asyncio
    async def test_streaming_variant_has_ai_mcpmesh_stream_tag(self):
        """Producer-side contract for Phase 5C (issue #849): the streaming
        variant carries ``ai.mcpmesh.stream``; the buffered variant does not.

        The consumer half (@mesh.llm) augments its provider tags filter to
        require or exclude this tag so the registry resolver picks the right
        variant deterministically.
        """
        module_name = "_test_llm_provider_streaming_tag"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude"],
            )

            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            buffered = mesh_tools["claude_provider"].metadata
            stream = mesh_tools["claude_provider_stream"].metadata

            assert "ai.mcpmesh.stream" in stream["tags"]
            assert "ai.mcpmesh.stream" not in buffered["tags"]
        finally:
            _drop_module(module_name)

    @pytest.mark.asyncio
    async def test_streaming_variant_tag_added_when_no_user_tags(self):
        """``ai.mcpmesh.stream`` is appended even when the user passes no tags."""
        module_name = "_test_llm_provider_streaming_tag_no_user_tags"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
            )

            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            stream = mesh_tools["claude_provider_stream"].metadata
            assert "ai.mcpmesh.stream" in stream["tags"]
        finally:
            _drop_module(module_name)


# ---------------------------------------------------------------------------
# Issue #227: multiple providers in one module register all variants
# ---------------------------------------------------------------------------


class TestMultipleProvidersInModule:
    @pytest.mark.asyncio
    async def test_two_providers_register_four_distinct_tools(self):
        """Issue #227 regression check, extended for the streaming variant."""
        module_name = "_test_llm_provider_streaming_multi"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude"],
            )
            _make_provider_in_module(
                mod,
                module_name,
                "openai_provider",
                model="openai/gpt-4o-mini",
                capability="llm",
                tags=["openai"],
            )

            registered = await mod.app.list_tools()
            tool_names = {t.name for t in registered}

            assert {
                "claude_provider",
                "claude_provider_stream",
                "openai_provider",
                "openai_provider_stream",
            }.issubset(tool_names)
        finally:
            _drop_module(module_name)


# ---------------------------------------------------------------------------
# Streaming tool yields chunks via the provider stream loop
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self):
        pass


def _delta(content=None, tool_calls=None):
    d = MagicMock()
    d.content = content
    d.tool_calls = tool_calls
    return d


def _choice(delta):
    c = MagicMock()
    c.delta = delta
    return c


def _chunk(content=None, usage=None, model=None):
    ch = MagicMock()
    ch.choices = [_choice(_delta(content=content))]
    ch.usage = (
        MagicMock(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        if usage
        else None
    )
    ch.model = model
    return ch


class TestStreamingToolYieldsChunks:
    @pytest.mark.asyncio
    async def test_no_tools_path_streams_chunks_through_acompletion(self):
        """Direct text-streaming when ``request.tools`` is empty.

        We exercise the underlying async generator function (resolved via
        ``_mesh_original_func`` on the DI wrapper) rather than the FastMCP
        stream wrapper — the wrapper accumulates chunks and returns a string,
        so testing it requires a FastMCP Context. The streaming behavior we
        care about is in the generator itself; the wrapper's chunk-forwarding
        is covered by ``test_stream_wrapper.py``.
        """
        import inspect

        from mesh.types import MeshLlmRequest

        module_name = "_test_llm_provider_streaming_yield"
        mod = _make_module_with_app(module_name)
        try:
            _make_provider_in_module(
                mod,
                module_name,
                "claude_provider",
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                tags=["claude"],
            )

            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            stream_meta = mesh_tools["claude_provider_stream"]
            wrapper = stream_meta.function
            # Walk back to the original async-generator function.
            original = getattr(wrapper, "_mesh_original_func", wrapper)
            assert inspect.isasyncgenfunction(original), (
                f"expected async-generator function, got {type(original).__name__}"
            )

            request = MeshLlmRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                model_params=None,
            )

            chunks = [
                _chunk(content="Hi", model="claude-3-5-haiku"),
                _chunk(content=" there"),
                _chunk(usage={"prompt_tokens": 5, "completion_tokens": 2}),
            ]

            with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
                mock_ac.return_value = _FakeStream(chunks)

                collected: list[str] = []
                async for piece in original(request):
                    collected.append(piece)

            assert collected == ["Hi", " there"]
        finally:
            _drop_module(module_name)
