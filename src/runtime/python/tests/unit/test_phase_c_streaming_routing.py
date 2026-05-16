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

import ast
import inspect
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


def _find_function_defs(
    node: ast.AST, name: str
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Walk ``node`` recursively and return EVERY FunctionDef /
    AsyncFunctionDef whose ``name`` matches.

    Returns a list (not a first-match scalar) because ``mesh.helpers``
    intentionally defines ``process_chat`` twice — once as a sync legacy
    factory and once as an async provider-managed factory. A regression
    that diverges only the second closure (e.g., drops ``streaming=False``
    on its ``_prepare_provider_request`` call) must still fail the audit;
    a first-match-only helper would silently pass.
    """
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name == name
    ]


def _iter_calls(node: ast.AST):
    """Yield every ``ast.Call`` inside ``node`` (descends into nested defs)."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            yield child


def _call_target_name(call: ast.Call) -> str | None:
    """Return the bare callee name for a ``Call`` whose target is either a
    simple ``Name`` (``foo(...)``) or a single-level ``Attribute``
    (``obj.foo(...)``). Returns ``None`` for deeper chains.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _keyword_constant(call: ast.Call, name: str):
    """Return the constant value of keyword ``name`` on ``call`` if present
    and an ``ast.Constant``.

    Returns ``_NOT_PRESENT`` (sentinel) if the keyword is absent.
    Returns ``_NON_CONSTANT`` (sentinel) if the keyword is present but
    its value is not an ``ast.Constant`` (e.g. a Name reference like
    ``streaming=streaming`` rather than a literal ``streaming=True``).
    """
    for kw in call.keywords:
        if kw.arg == name:
            if isinstance(kw.value, ast.Constant):
                return kw.value.value
            return _NON_CONSTANT
    return _NOT_PRESENT


_NON_CONSTANT = object()
_NOT_PRESENT = object()


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

    AST-based (not substring): a refactor that renamed
    ``_pop_mesh_synthetic_format_flags`` would fail SPECIFICALLY because the
    renamed call doesn't appear in ``process_chat_stream``'s call sites, not
    because the literal substring no longer matches. Same goes for any
    whitespace / line-break / argument-spread change to the call.
    """

    @staticmethod
    def _helpers_module_ast() -> ast.Module:
        import mesh.helpers as helpers_module

        return ast.parse(inspect.getsource(helpers_module))

    def test_helpers_module_streaming_branch_does_not_buffer_for_synthetic(self):
        """The removed branch was identified by a local ``buffer_for_synthetic``
        flag. Walk the streaming closure's AST and confirm no ``Name`` or
        ``arg`` carries that identifier. Catches reintroduction regardless
        of whitespace / line-wrap.

        Iterates over EVERY ``process_chat_stream`` definition — today
        there's one, but if a second factory ever defines another, a
        regression in the new closure must still fail this audit.
        """
        tree = self._helpers_module_ast()
        streams = _find_function_defs(tree, "process_chat_stream")
        assert streams, (
            "process_chat_stream closure not found inside mesh.helpers — "
            "this test (and the streaming wiring it guards) is out of date"
        )

        for idx, process_chat_stream in enumerate(streams):
            offending: list[str] = []
            for child in ast.walk(process_chat_stream):
                if isinstance(child, ast.Name) and child.id == "buffer_for_synthetic":
                    offending.append(f"Name@line {child.lineno}")
                elif isinstance(child, ast.arg) and child.arg == "buffer_for_synthetic":
                    offending.append(f"arg@line {child.lineno}")

            assert not offending, (
                f"process_chat_stream #{idx} (defined at line "
                f"{process_chat_stream.lineno}) must not reference "
                "`buffer_for_synthetic` (removed Phase C bug branch). "
                "Found: " + ", ".join(offending)
            )

    def test_streaming_no_tools_path_calls_pop_synthetic_format_flags(self):
        """``process_chat_stream`` must call ``_pop_mesh_synthetic_format_flags``
        at least once — defense-in-depth against misconfiguration where a
        custom handler stamps the sentinels on a streaming request.

        AST check: a refactor that renamed the function (e.g. to
        ``_pop_synthetic_flags``) would break this test because the renamed
        ``Call.func.id`` no longer matches, NOT because a substring stopped
        appearing.

        Iterates over every ``process_chat_stream`` definition so a future
        second factory cannot silently skip the defense-in-depth strip.
        """
        tree = self._helpers_module_ast()
        streams = _find_function_defs(tree, "process_chat_stream")
        assert streams, "process_chat_stream closure not found"

        for idx, process_chat_stream in enumerate(streams):
            target_calls = [
                call
                for call in _iter_calls(process_chat_stream)
                if _call_target_name(call) == "_pop_mesh_synthetic_format_flags"
            ]
            assert target_calls, (
                f"process_chat_stream #{idx} (defined at line "
                f"{process_chat_stream.lineno}) must call "
                "_pop_mesh_synthetic_format_flags (defense-in-depth strip "
                "of the synthetic-format sentinels). If you renamed the "
                "function, update this AST check too."
            )


# ---------------------------------------------------------------------------
# helpers.py wiring: _prepare_provider_request plumbs the streaming flag
# through to handler.apply_structured_output
# ---------------------------------------------------------------------------


class TestPrepareProviderRequestStreamingFlag:
    """``_prepare_provider_request`` is a local closure inside the
    ``llm_provider`` decorator factory, so we can't import and call it
    directly. AST inspection covers the contract: the two outer call sites
    must pass ``streaming=True`` (process_chat_stream) and ``streaming=False``
    (process_chat); the inner handler call must forward ``streaming=streaming``.

    AST (not substring) so a refactor that renamed ``_prepare_provider_request``
    or ``apply_structured_output`` would fail the test SPECIFICALLY because
    the renamed call site isn't found, not because the literal string no
    longer appears.
    """

    @staticmethod
    def _helpers_module_ast() -> ast.Module:
        import mesh.helpers as helpers_module

        return ast.parse(inspect.getsource(helpers_module))

    def _streaming_kw_in_call_to(
        self, parent: ast.AST, callee_name: str
    ) -> list[object]:
        """Walk ``parent`` for every ``Call`` to ``callee_name`` and return
        the ``streaming`` keyword value (constant) of each.
        """
        return [
            _keyword_constant(call, "streaming")
            for call in _iter_calls(parent)
            if _call_target_name(call) == callee_name
        ]

    def test_process_chat_calls_prepare_with_streaming_false(self):
        """``mesh.helpers`` defines ``process_chat`` in BOTH the legacy and
        provider-managed factories. Iterate over every occurrence so a
        regression in either closure (e.g., dropping the explicit
        ``streaming=False``) fails the audit.
        """
        tree = self._helpers_module_ast()
        process_chats = _find_function_defs(tree, "process_chat")
        assert process_chats, "process_chat closure not found"

        for idx, process_chat in enumerate(process_chats):
            streaming_kws = self._streaming_kw_in_call_to(
                process_chat, "_prepare_provider_request"
            )
            # process_chat may call _prepare_provider_request at least once;
            # every such call must pass streaming=False explicitly (no
            # implicit default — explicit is the design contract).
            assert streaming_kws, (
                f"process_chat #{idx} (defined at line {process_chat.lineno}) "
                "must call _prepare_provider_request (none found)"
            )
            assert all(v is False for v in streaming_kws), (
                f"process_chat #{idx} (defined at line {process_chat.lineno}) "
                "must pass streaming=False to _prepare_provider_request "
                f"(observed: {streaming_kws}) to preserve buffered "
                "synthetic-tool behavior"
            )

    def test_process_chat_stream_calls_prepare_with_streaming_true(self):
        """Iterates over every ``process_chat_stream`` definition — today
        there's only one, but the helper returns ALL matches so a future
        second factory cannot silently skip the ``streaming=True`` contract.
        """
        tree = self._helpers_module_ast()
        streams = _find_function_defs(tree, "process_chat_stream")
        assert streams, "process_chat_stream closure not found"

        for idx, process_chat_stream in enumerate(streams):
            streaming_kws = self._streaming_kw_in_call_to(
                process_chat_stream, "_prepare_provider_request"
            )
            assert streaming_kws, (
                f"process_chat_stream #{idx} (defined at line "
                f"{process_chat_stream.lineno}) must call "
                "_prepare_provider_request (none found)"
            )
            assert all(v is True for v in streaming_kws), (
                f"process_chat_stream #{idx} (defined at line "
                f"{process_chat_stream.lineno}) must pass streaming=True "
                f"to _prepare_provider_request (observed: {streaming_kws}) "
                "so ClaudeHandler routes to HINT mode"
            )

    def test_prepare_provider_request_forwards_streaming_to_handler(self):
        """Inside ``_prepare_provider_request``, the call to
        ``handler.apply_structured_output`` must forward ``streaming=streaming``
        (pass-through of the outer parameter, not a literal True/False).

        Iterates over every ``_prepare_provider_request`` definition so any
        future second copy must also forward the parameter.
        """
        tree = self._helpers_module_ast()
        prepares = _find_function_defs(tree, "_prepare_provider_request")
        assert prepares, "_prepare_provider_request closure not found"

        for idx, prepare in enumerate(prepares):
            # First, the function must declare a ``streaming`` parameter —
            # that's the source of the value we forward.
            all_args = (
                prepare.args.args
                + prepare.args.kwonlyargs
                + ([prepare.args.vararg] if prepare.args.vararg else [])
            )
            param_names = [a.arg for a in all_args if a is not None]
            assert "streaming" in param_names, (
                f"_prepare_provider_request #{idx} (defined at line "
                f"{prepare.lineno}) must declare a `streaming` parameter "
                f"(found: {param_names})"
            )

            # Find every call to apply_structured_output inside the closure
            # and verify each forwards streaming=<the parameter>.
            forwarding_calls = []
            for call in _iter_calls(prepare):
                if _call_target_name(call) != "apply_structured_output":
                    continue
                for kw in call.keywords:
                    if kw.arg == "streaming":
                        # The forwarded value should be a Name node
                        # referencing the closure's `streaming` parameter —
                        # NOT a constant.
                        is_forward = (
                            isinstance(kw.value, ast.Name)
                            and kw.value.id == "streaming"
                        )
                        forwarding_calls.append((call.lineno, is_forward))

            assert forwarding_calls, (
                f"_prepare_provider_request #{idx} (defined at line "
                f"{prepare.lineno}) must call handler.apply_structured_output "
                "with a streaming= kwarg"
            )
            assert all(is_forward for _, is_forward in forwarding_calls), (
                f"_prepare_provider_request #{idx} (defined at line "
                f"{prepare.lineno}) must forward its own `streaming` "
                "parameter (Name node) to apply_structured_output, not a "
                f"literal — observed: {forwarding_calls}"
            )
