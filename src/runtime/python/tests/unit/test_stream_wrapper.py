"""Unit tests for the streaming-tool wrapper in dependency_injector.

Covers P4 of issue #645:
- Stream-aware wrapper detection (``_is_stream_tool``).
- ``_build_stream_signature`` exposes ``ctx`` so FastMCP auto-fills it.
- Wrapper forwards each chunk via ``ctx.report_progress`` and accumulates
  the joined string as the return value.
- Graceful no-op when ``ctx`` is None (caller didn't pass progressToken).
- ``CancelledError`` propagates ``gen.aclose()`` to user finally blocks.
- Defensive ``report_progress`` signature probe falls back to positional.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator as AbcAsyncIterator
from typing import AsyncIterator
from unittest.mock import patch

import pytest

import mesh
from _mcp_mesh.engine import dependency_injector as di
from _mcp_mesh.engine.dependency_injector import (
    DependencyInjector,
    _build_stream_signature,
    _forward_chunk,
    _is_stream_tool,
    _make_stream_wrapper,
    _resolve_report_progress_convention,
)


# ---------------------------------------------------------------------------
# Mock recorder for ctx.report_progress
# ---------------------------------------------------------------------------


class _RecordingCtx:
    """Records report_progress calls. Mimics fastmcp.Context API surface."""

    def __init__(self, *, fail_on: int | None = None):
        self.events: list[tuple[float, float | None, str | None]] = []
        self._fail_on = fail_on
        self._call = 0

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        self._call += 1
        if self._fail_on is not None and self._call == self._fail_on:
            raise RuntimeError("simulated transport hiccup")
        self.events.append((progress, total, message))


@pytest.fixture(autouse=True)
def _reset_convention_cache():
    """Each test starts with a fresh report_progress convention probe."""
    di._REPORT_PROGRESS_CONVENTION = None
    yield
    di._REPORT_PROGRESS_CONVENTION = None


# ---------------------------------------------------------------------------
# _is_stream_tool detection
# ---------------------------------------------------------------------------


class TestIsStreamTool:
    def test_async_gen_function_detected(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "x"

        assert _is_stream_tool(chat) is True

    def test_metadata_stream_type_detected(self):
        async def chat(prompt: str) -> str:
            return prompt

        chat._mesh_tool_metadata = {"stream_type": "text"}
        assert _is_stream_tool(chat) is True

    def test_no_metadata_no_async_gen_returns_false(self):
        async def chat(prompt: str) -> str:
            return prompt

        assert _is_stream_tool(chat) is False

    def test_metadata_without_stream_type_returns_false(self):
        async def chat(prompt: str) -> str:
            return prompt

        chat._mesh_tool_metadata = {"capability": "chat"}
        assert _is_stream_tool(chat) is False


# ---------------------------------------------------------------------------
# _build_stream_signature appends ctx
# ---------------------------------------------------------------------------


class TestBuildStreamSignature:
    def test_appends_ctx_keyword_only_with_default_none(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield prompt

        sig = _build_stream_signature(chat)
        assert "prompt" in sig.parameters
        assert "ctx" in sig.parameters
        ctx_param = sig.parameters["ctx"]
        assert ctx_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert ctx_param.default is None

    def test_does_not_duplicate_ctx_when_present(self):
        async def chat(prompt: str, ctx: object = None) -> AsyncIterator[str]:
            yield prompt

        sig = _build_stream_signature(chat)
        ctx_params = [p for p in sig.parameters if p == "ctx"]
        assert len(ctx_params) == 1


# ---------------------------------------------------------------------------
# Stream wrapper end-to-end behavior
# ---------------------------------------------------------------------------


class TestStreamWrapperForwardsChunks:
    @pytest.mark.asyncio
    async def test_forwards_each_chunk_and_accumulates_joined_string(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            for word in prompt.split():
                yield word + " "

        chat._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        ctx = _RecordingCtx()
        result = await wrapper("hello world", ctx=ctx)

        assert result == "hello world "
        assert ctx.events == [(0, None, "hello "), (1, None, "world ")]

    @pytest.mark.asyncio
    async def test_works_with_no_ctx(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "a"
            yield "b"

        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        result = await wrapper("ignored")
        assert result == "ab"

    @pytest.mark.asyncio
    async def test_ctx_explicitly_none_no_op(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "a"

        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        result = await wrapper("p", ctx=None)
        assert result == "a"


# ---------------------------------------------------------------------------
# CancelledError propagation
# ---------------------------------------------------------------------------


class TestStreamWrapperCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_calls_gen_aclose(self):
        finally_ran = []

        async def chat(prompt: str) -> AsyncIterator[str]:
            try:
                for i in range(100):
                    yield f"chunk-{i}"
                    await asyncio.sleep(0.05)
            finally:
                finally_ran.append(True)

        chat._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        async def slow_ctx_report(*args, **kwargs):
            await asyncio.sleep(0.05)

        class _SlowCtx:
            async def report_progress(self, *a, **k):
                await slow_ctx_report()

        ctx = _SlowCtx()

        task = asyncio.create_task(wrapper("p", ctx=ctx))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Generator's finally must have run (proving aclose() propagated)
        assert finally_ran == [True]


# ---------------------------------------------------------------------------
# Defensive report_progress signature probe
# ---------------------------------------------------------------------------


class TestForwardChunkConvention:
    def test_kwarg_convention_when_message_param_present(self):
        async def report_progress(
            progress: float, total: float | None = None, message: str | None = None
        ) -> None:
            pass

        assert _resolve_report_progress_convention(report_progress) == "kwarg"

    def test_positional_convention_when_message_kwarg_missing(self):
        async def report_progress(progress, total=None, msg=None):
            pass

        assert _resolve_report_progress_convention(report_progress) == "positional"

    @pytest.mark.asyncio
    async def test_forward_chunk_uses_message_kwarg(self):
        captured: dict = {}

        class Ctx:
            async def report_progress(
                self,
                progress: float,
                total: float | None = None,
                message: str | None = None,
            ):
                captured["progress"] = progress
                captured["total"] = total
                captured["message"] = message

        await _forward_chunk(Ctx(), 3, "hello")
        assert captured == {"progress": 3, "total": None, "message": "hello"}

    @pytest.mark.asyncio
    async def test_forward_chunk_falls_back_to_positional(self):
        captured: list = []

        class Ctx:
            async def report_progress(self, progress, total=None, msg=None):
                captured.append((progress, total, msg))

        await _forward_chunk(Ctx(), 7, "world")
        assert captured == [(7, None, "world")]

    @pytest.mark.asyncio
    async def test_forward_chunk_swallows_report_failure(self):
        ctx = _RecordingCtx(fail_on=1)
        # Must not raise
        await _forward_chunk(ctx, 0, "x")
        # Failure was swallowed; nothing recorded
        assert ctx.events == []

    @pytest.mark.asyncio
    async def test_forward_chunk_none_ctx_no_op(self):
        # Just ensure no exception
        await _forward_chunk(None, 0, "x")


# ---------------------------------------------------------------------------
# Type errors
# ---------------------------------------------------------------------------


class TestStreamWrapperTypeErrors:
    @pytest.mark.asyncio
    async def test_non_str_chunk_raises(self):
        async def bad_stream(prompt: str):
            yield 1  # not a str

        bad_stream._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bad_stream, [])

        with pytest.raises(TypeError, match="non-str chunk"):
            await wrapper("p", ctx=_RecordingCtx())

    @pytest.mark.asyncio
    async def test_function_returning_non_async_iterator_raises(self):
        async def bad(prompt: str):
            return "not an iterator"

        bad._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bad, [])

        with pytest.raises(TypeError, match="did not return an async iterator"):
            await wrapper("p", ctx=_RecordingCtx())
