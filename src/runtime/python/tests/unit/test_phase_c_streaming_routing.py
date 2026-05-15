"""Unit tests for Phase C of the native LLM dispatch contract work.

Phase C ties together three changes:

1. ``BaseProviderHandler.apply_structured_output`` gains a ``streaming``
   kwarg. ``ClaudeHandler`` consumes it: ``streaming=True`` forces HINT mode
   even when the native Anthropic SDK is available, because synthetic-tool
   injection (the buffered native path) is a single discrete forced tool
   call that doesn't actually stream as text chunks. HINT mode (schema in
   prompt, JSON-as-text) is the natural fit for streaming and reuses the
   existing HINT-fallback machinery for parse failures.

2. The legacy buffered ``process_chat`` final-response branch in
   ``mesh.helpers`` gains a ``_maybe_run_synthetic_fallback`` call, mirroring
   the agentic-loop site. Without it, a direct call into ``process_chat``
   (no provider-managed loop) would surface the model's plain-text response
   as the structured answer when Claude declined to call the synthetic tool.

3. The legacy ``process_chat_stream`` no-tools path no longer attempts to
   buffer the stream for synthetic-tool emission. With Phase C, streaming
   routes to HINT mode in ClaudeHandler, so the synthetic-format sentinels
   should never reach this path. The previous code yielded buffered text as
   a "best-effort fallback" when the synthetic tool was missing — that
   branch is removed; the strip of the synthetic flags is preserved as
   defense-in-depth.

The handler-side routing tests live in
``_mcp_mesh/engine/provider_handlers/tests/test_claude_handler_native.py``
(``TestApplyStructuredOutputStreamingRouting``). This module covers the
helpers.py wiring + fallback semantics.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mesh.helpers import (
    _maybe_run_synthetic_fallback,
)


SYNTHETIC_TOOL_NAME = "__mesh_format_response"


# ---------------------------------------------------------------------------
# Vendor handler signature compatibility: every apply_structured_output
# override must accept the ``streaming`` kwarg.
# ---------------------------------------------------------------------------


class TestApplyStructuredOutputAcceptsStreamingKwarg:
    """Every vendor handler's ``apply_structured_output`` must accept the
    ``streaming`` kwarg even when the handler doesn't change its behavior
    based on it — otherwise the shared call site in ``_prepare_provider_request``
    would raise TypeError for non-Claude vendors when ``streaming=True``.
    """

    @staticmethod
    def _schema() -> dict:
        return {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }

    def test_base_handler_accepts_streaming_kwarg(self):
        from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
            BaseProviderHandler,
        )

        class _Concrete(BaseProviderHandler):
            def __init__(self):
                super().__init__(vendor="test")

            def determine_output_mode(self, output_type, override_mode=None):
                return "strict"

            def prepare_request(self, messages, tools, output_type, **kwargs):
                return {}

            def format_system_prompt(
                self, base_prompt, tool_schemas, output_type, output_mode=None
            ):
                return base_prompt

        handler = _Concrete()
        result = handler.apply_structured_output(
            self._schema(), "T", {"messages": []}, streaming=True
        )
        # Base impl sets response_format regardless of streaming.
        assert "response_format" in result

    def test_openai_handler_accepts_streaming_kwarg(self):
        from _mcp_mesh.engine.provider_handlers.openai_handler import OpenAIHandler

        handler = OpenAIHandler()
        # OpenAI inherits from base — streaming kwarg should pass through.
        result = handler.apply_structured_output(
            self._schema(), "T", {"messages": []}, streaming=True
        )
        assert "response_format" in result

    def test_gemini_handler_accepts_streaming_kwarg_as_noop(self):
        from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler

        handler = GeminiHandler()
        params: dict = {"messages": [{"role": "system", "content": "x"}]}
        # Gemini is HINT-only for tools-present anyway; streaming is a no-op.
        result_streaming = handler.apply_structured_output(
            self._schema(), "T", params, streaming=True
        )
        assert result_streaming["_mesh_hint_mode"] is True

        params2: dict = {"messages": [{"role": "system", "content": "x"}]}
        result_buffered = handler.apply_structured_output(
            self._schema(), "T", params2, streaming=False
        )
        assert result_buffered["_mesh_hint_mode"] is True

    def test_generic_handler_accepts_streaming_kwarg(self):
        from _mcp_mesh.engine.provider_handlers.generic_handler import GenericHandler

        handler = GenericHandler(vendor="custom")
        # Generic handler is a no-op for structured output — just verify the
        # call doesn't TypeError when streaming is passed.
        result = handler.apply_structured_output(
            self._schema(), "T", {"messages": []}, streaming=True
        )
        assert "response_format" not in result


def _synthetic_tool(schema: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": SYNTHETIC_TOOL_NAME,
            "description": "synthetic format tool",
            "parameters": schema
            or {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }


# ---------------------------------------------------------------------------
# _maybe_run_synthetic_fallback: contract for the legacy buffered path
# ---------------------------------------------------------------------------


class TestMaybeRunSyntheticFallbackEarlyReturns:
    """The legacy ``process_chat`` buffered branch calls
    ``_maybe_run_synthetic_fallback`` unconditionally after the HINT
    fallback. It MUST early-return cleanly when the synthetic flags are
    not set so we can call it on every request without harm.
    """

    @pytest.mark.asyncio
    async def test_returns_original_content_when_synthetic_tool_name_is_none(self):
        message = MagicMock()
        response = MagicMock()

        out_content, out_msg, out_resp = await _maybe_run_synthetic_fallback(
            final_content="hello",
            message=message,
            response=response,
            base_completion_args={},
            synthetic_tool_name=None,
            synthetic_tool=_synthetic_tool(),
            fallback_timeout=30,
            fallback_logger=None,
            vendor="anthropic",
        )

        assert out_content == "hello"
        assert out_msg is message
        assert out_resp is response

    @pytest.mark.asyncio
    async def test_returns_original_content_when_synthetic_tool_is_none(self):
        message = MagicMock()
        response = MagicMock()

        out_content, out_msg, out_resp = await _maybe_run_synthetic_fallback(
            final_content="hello",
            message=message,
            response=response,
            base_completion_args={},
            synthetic_tool_name=SYNTHETIC_TOOL_NAME,
            synthetic_tool=None,
            fallback_timeout=30,
            fallback_logger=None,
            vendor="anthropic",
        )

        assert out_content == "hello"
        assert out_msg is message
        assert out_resp is response

    @pytest.mark.asyncio
    async def test_returns_original_content_when_final_content_empty(self):
        """Empty content -> nothing to validate, no retry."""
        message = MagicMock()
        response = MagicMock()

        out_content, out_msg, out_resp = await _maybe_run_synthetic_fallback(
            final_content="",
            message=message,
            response=response,
            base_completion_args={},
            synthetic_tool_name=SYNTHETIC_TOOL_NAME,
            synthetic_tool=_synthetic_tool(),
            fallback_timeout=30,
            fallback_logger=None,
            vendor="anthropic",
        )

        assert out_content == ""
        assert out_msg is message
        assert out_resp is response

    @pytest.mark.asyncio
    async def test_skips_retry_when_content_parses_against_synthetic_schema(self):
        """Content that already validates against the synthetic schema is the
        success case — no retry needed."""
        message = MagicMock()
        response = MagicMock()
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }

        with patch(
            "mesh.helpers._run_response_format_retry",
            new=AsyncMock(),
        ) as mock_retry:
            out_content, out_msg, out_resp = await _maybe_run_synthetic_fallback(
                final_content='{"answer": "hello"}',
                message=message,
                response=response,
                base_completion_args={},
                synthetic_tool_name=SYNTHETIC_TOOL_NAME,
                synthetic_tool=_synthetic_tool(schema),
                fallback_timeout=30,
                fallback_logger=None,
                vendor="anthropic",
            )

        mock_retry.assert_not_awaited()
        assert out_content == '{"answer": "hello"}'
        assert out_msg is message
        assert out_resp is response


class TestMaybeRunSyntheticFallbackRetry:
    """When the content fails to parse against the synthetic schema, the
    helper retries via ``_run_response_format_retry`` with the schema.
    """

    @pytest.mark.asyncio
    async def test_retries_when_plain_text_fails_schema_validation(self):
        """The synthetic-tool decline case: model returns plain text instead of
        calling the synthetic tool. The fallback retries with response_format
        to recover a structured answer."""
        original_msg = MagicMock()
        original_response = MagicMock()
        retry_msg = MagicMock()
        retry_response = MagicMock()

        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }

        with patch(
            "mesh.helpers._run_response_format_retry",
            new=AsyncMock(
                return_value=('{"answer": "structured"}', retry_msg, retry_response)
            ),
        ) as mock_retry:
            out_content, out_msg, out_resp = await _maybe_run_synthetic_fallback(
                final_content="I cannot help with that.",
                message=original_msg,
                response=original_response,
                base_completion_args={
                    "model": "anthropic/claude-haiku",
                    "messages": [{"role": "user", "content": "x"}],
                },
                synthetic_tool_name=SYNTHETIC_TOOL_NAME,
                synthetic_tool=_synthetic_tool(schema),
                fallback_timeout=30,
                fallback_logger=None,
                vendor="anthropic",
            )

        mock_retry.assert_awaited_once()
        # The retry's content replaces the model's hedge/refusal.
        assert out_content == '{"answer": "structured"}'
        assert out_msg is retry_msg
        assert out_resp is retry_response

        # Retry was called with the schema from the synthetic tool's
        # ``parameters`` field.
        call_kwargs = mock_retry.await_args.kwargs
        assert call_kwargs["schema"] == schema
        assert call_kwargs["fallback_timeout"] == 30
        assert call_kwargs["vendor"] == "anthropic"


# ---------------------------------------------------------------------------
# Legacy process_chat_stream no-tools path: the buffer-for-synthetic bug
# branch is removed; the synthetic-format flags are still stripped.
# ---------------------------------------------------------------------------


class TestStreamingNoToolsPathSyntheticBugRemoved:
    """The legacy ``process_chat_stream`` no-tools path used to set up
    ``buffer_for_synthetic`` when synthetic flags were present, drain the
    whole stream, then either yield the merged synthetic args OR yield the
    buffered text as a "best-effort fallback". That fallback branch was the
    bug per the gap map: it surfaced the model's hedge text as if it were
    the structured answer.

    With Phase C, streaming routes to HINT in ClaudeHandler, so the synthetic
    sentinels should never reach this path. The strip is kept defensively;
    the buffer-for-synthetic logic is removed. These tests confirm the
    streaming-side code no longer references the removed names.
    """

    def test_helpers_module_streaming_branch_does_not_buffer_for_synthetic(self):
        """Source-level check: the legacy streaming path must no longer
        contain the ``buffer_for_synthetic`` bug branch. This is a
        belt-and-suspenders assertion against accidental reintroduction.
        """
        import inspect

        import mesh.helpers as helpers_module

        source = inspect.getsource(helpers_module)
        # The flag name was specific to the removed branch — its presence
        # would mean someone reintroduced the buffer-then-fallback path.
        assert "buffer_for_synthetic" not in source, (
            "process_chat_stream no-tools path must not buffer for "
            "synthetic-tool emission — Phase C routes streaming to HINT "
            "mode in ClaudeHandler instead"
        )

    def test_helpers_module_still_strips_synthetic_flags_defensively(self):
        """Even though the synthetic-format flags should never reach the
        streaming path, the strip via ``_pop_mesh_synthetic_format_flags``
        must remain — defense-in-depth against misconfiguration where a
        custom handler stamps the sentinels on a streaming request.
        """
        import inspect

        import mesh.helpers as helpers_module

        source = inspect.getsource(helpers_module)
        # The strip helper is called in the streaming no-tools path. The
        # specific call site is non-trivial to extract by AST in a unit
        # test; we instead assert it's still referenced (the legacy path
        # was the only place that called it directly outside the agentic
        # loops, and we kept it).
        assert "_pop_mesh_synthetic_format_flags" in source


# ---------------------------------------------------------------------------
# helpers.py wiring: _prepare_provider_request plumbs the streaming flag
# through to handler.apply_structured_output
# ---------------------------------------------------------------------------


class TestPrepareProviderRequestStreamingFlag:
    """``_prepare_provider_request`` is a local closure inside the
    ``llm_provider`` decorator factory, so we can't import and call it
    directly. Source-level inspection is the pragmatic guard: the two call
    sites must pass ``streaming=True`` (process_chat_stream) and
    ``streaming=False`` (process_chat), and the handler call must forward
    the flag.
    """

    def test_streaming_flag_is_plumbed_through_to_handler(self):
        import inspect

        import mesh.helpers as helpers_module

        source = inspect.getsource(helpers_module)
        # The buffered path passes streaming=False explicitly (or omits to
        # default). The streaming path MUST pass streaming=True.
        assert "_prepare_provider_request(request, streaming=True)" in source, (
            "process_chat_stream must call _prepare_provider_request with "
            "streaming=True so ClaudeHandler routes to HINT mode"
        )
        assert "_prepare_provider_request(request, streaming=False)" in source, (
            "process_chat must call _prepare_provider_request with "
            "streaming=False to preserve buffered synthetic-tool behavior"
        )
        # And the apply_structured_output call must forward streaming.
        assert "streaming=streaming" in source, (
            "_prepare_provider_request must forward its streaming kwarg to "
            "handler.apply_structured_output"
        )
