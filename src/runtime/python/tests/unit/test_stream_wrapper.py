"""Unit tests for the streaming-tool wrapper in dependency_injector.

Covers P4 of issue #645:
- Stream-aware wrapper detection (``_is_stream_tool``).
- ``_build_stream_signature`` exposes the synthesized progress-context
  parameter so FastMCP auto-fills its ``Context`` at call time.
- Wrapper forwards each chunk via ``ctx.report_progress`` and accumulates
  the joined string as the return value.
- Graceful no-op when no ``Context`` is injected (caller didn't pass
  ``progressToken``).
- ``CancelledError`` propagates ``gen.aclose()`` to user finally blocks.
- Defensive ``report_progress`` signature probe falls back to positional.

Also covers the ctx-collision fix: users who declare their own ``ctx``
parameter (typically a ``MeshContextModel`` paired with
``@mesh.llm(context_param="ctx", ...)``) must not have streaming silently
disabled. The wrapper synthesizes its progress channel under an internal
name (``_mesh_progress_ctx``) to avoid clobbering the user's annotation.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator as AbcAsyncIterator
from typing import AsyncIterator, Optional
from unittest.mock import patch

import pytest

import mesh
from _mcp_mesh.engine import dependency_injector as di
from _mcp_mesh.engine.dependency_injector import (
    _MESH_PROGRESS_CTX_PARAM,
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
    def test_appends_progress_ctx_keyword_only_with_default_none(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield prompt

        sig = _build_stream_signature(chat)
        assert "prompt" in sig.parameters
        assert _MESH_PROGRESS_CTX_PARAM in sig.parameters
        ctx_param = sig.parameters[_MESH_PROGRESS_CTX_PARAM]
        assert ctx_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert ctx_param.default is None

    def test_progress_ctx_is_context_typed_so_fastmcp_can_inject(self):
        """FastMCP injects ``Context`` by TYPE annotation, not by name. The
        synthesized parameter must carry ``Optional[Context]`` (or ``Context``
        nested under a ``Union``/``Optional``) for
        ``transform_context_annotations`` to recognize it.
        """
        from fastmcp import Context

        async def chat(prompt: str) -> AsyncIterator[str]:
            yield prompt

        sig = _build_stream_signature(chat)
        ctx_param = sig.parameters[_MESH_PROGRESS_CTX_PARAM]
        # Annotation is ``Optional[Context]``.
        assert ctx_param.annotation == Optional[Context]

    def test_user_ctx_param_passes_through_unchanged(self):
        """A user function that declares its own ``ctx`` parameter (a common
        pattern with ``@mesh.llm(context_param="ctx", ...)``) must keep that
        parameter untouched in the wrapper signature — same name, same
        annotation, same default — and the synthesized progress-context
        parameter must be added alongside it.
        """

        class UserContext:
            pass

        async def chat(prompt: str, ctx: UserContext = None) -> AsyncIterator[str]:
            yield prompt

        sig = _build_stream_signature(chat)
        # User's ctx is preserved.
        assert "ctx" in sig.parameters
        user_ctx = sig.parameters["ctx"]
        # Note: ``from __future__ import annotations`` (PEP 563) at the top
        # of this module converts annotations to strings, so we compare the
        # string form rather than the class object.
        assert user_ctx.annotation in (UserContext, "UserContext")
        assert user_ctx.default is None
        # Synthesized parameter is added (this is the regression that the
        # name-collision fix addresses).
        assert _MESH_PROGRESS_CTX_PARAM in sig.parameters

    def test_idempotent_when_progress_ctx_already_present(self):
        """Running the builder twice on the same signature must not duplicate
        the synthesized parameter."""

        async def chat(prompt: str) -> AsyncIterator[str]:
            yield prompt

        sig_once = _build_stream_signature(chat)
        # Simulate re-entry by attaching the augmented signature back to
        # the function and calling again.
        chat.__signature__ = sig_once
        sig_twice = _build_stream_signature(chat)
        progress_params = [
            p for p in sig_twice.parameters if p == _MESH_PROGRESS_CTX_PARAM
        ]
        assert len(progress_params) == 1


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
        # FastMCP injects under the synthesized internal name.
        result = await wrapper("hello world", **{_MESH_PROGRESS_CTX_PARAM: ctx})

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
    async def test_progress_ctx_explicitly_none_no_op(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "a"

        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        result = await wrapper("p", **{_MESH_PROGRESS_CTX_PARAM: None})
        assert result == "a"

    @pytest.mark.asyncio
    async def test_stream_wrapper_works_when_user_has_ctx_parameter(self):
        """Regression test for the ctx-name-collision bug.

        When the user declares their own ``ctx: SomeOtherType`` parameter on
        the streaming function (which is the natural shape produced by
        ``@mesh.llm(context_param="ctx", ...)``), the wrapper must still
        forward chunks via FastMCP's injected ``Context``. Before the fix
        the synthesized parameter was also named ``ctx`` and was suppressed
        when the user already had one — leaving ``ctx`` ``None`` at runtime
        and silently degrading streaming to a buffered single chunk.

        Verifies:
          * ``report_progress`` is called per chunk on the FastMCP-injected
            mock context.
          * The user's ``ctx`` keyword (their own context object) is passed
            through to the user function untouched.
          * The joined text is returned at the end.
        """

        class UserContext:
            def __init__(self, label: str):
                self.label = label

        seen_user_ctx: list[UserContext | None] = []

        async def chat(prompt: str, ctx: UserContext = None) -> AsyncIterator[str]:
            seen_user_ctx.append(ctx)
            yield "alpha "
            yield "beta"

        chat._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        progress_ctx = _RecordingCtx()
        user_ctx = UserContext(label="user-supplied")

        result = await wrapper(
            "p",
            ctx=user_ctx,  # user's own context — must reach the user function
            **{_MESH_PROGRESS_CTX_PARAM: progress_ctx},
        )

        # Joined string returned.
        assert result == "alpha beta"
        # Each chunk forwarded via FastMCP's Context.
        assert progress_ctx.events == [(0, None, "alpha "), (1, None, "beta")]
        # User's ctx survived the wrapper untouched.
        assert seen_user_ctx == [user_ctx]

    @pytest.mark.asyncio
    async def test_user_ctx_kwarg_does_not_leak_progress_ctx(self):
        """The synthesized progress-context kwarg must be popped before the
        user function is invoked — otherwise the user function would receive
        an unexpected ``_mesh_progress_ctx`` kwarg and raise ``TypeError``.
        """

        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "x"

        chat._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(chat, [])

        # Should not raise — the wrapper must strip the internal kwarg.
        result = await wrapper("p", **{_MESH_PROGRESS_CTX_PARAM: _RecordingCtx()})
        assert result == "x"


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

        task = asyncio.create_task(
            wrapper("p", **{_MESH_PROGRESS_CTX_PARAM: ctx})
        )
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
            await wrapper("p", **{_MESH_PROGRESS_CTX_PARAM: _RecordingCtx()})

    @pytest.mark.asyncio
    async def test_function_returning_non_async_iterator_raises(self):
        async def bad(prompt: str):
            return "not an iterator"

        bad._mesh_tool_metadata = {"stream_type": "text"}
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bad, [])

        with pytest.raises(TypeError, match="did not return an async iterator"):
            await wrapper("p", **{_MESH_PROGRESS_CTX_PARAM: _RecordingCtx()})
