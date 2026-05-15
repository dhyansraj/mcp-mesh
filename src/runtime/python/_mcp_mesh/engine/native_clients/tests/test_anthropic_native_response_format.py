"""Adapter-level integration tests for ``response_format`` translation
(Phase A.3).

The adapter translates ``response_format`` (LiteLLM-shape) into a
synthetic-tool injection inside ``_build_create_kwargs``. These tests
capture the outbound ``anthropic.messages.create`` kwargs and assert the
contract documented in the Phase A.3 design.

Two injection paths exist:
  * Handler-injected — when ``ClaudeHandler._apply_native_synthetic_format``
    has already added the synthetic tool. Adapter is a no-op (just pops
    ``response_format``).
  * Adapter-injected — when a caller (notably
    ``helpers._run_response_format_retry``) bypasses the handler and emits
    ``response_format`` directly.

Real network calls are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "anthropic", reason="native Anthropic adapter requires the anthropic SDK"
)

from _mcp_mesh.engine._structured_output_helpers import (
    SYNTHETIC_FORMAT_TOOL_NAME,
    schema_to_synthetic_tool,
)
from _mcp_mesh.engine.native_clients import anthropic_native


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_anthropic_message(text: str = "ok"):
    """Minimal anthropic.types.Message-like response."""
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    return SimpleNamespace(content=[block], usage=usage, model="claude-test")


def _patched_async_anthropic(api_response):
    """Patch anthropic.AsyncAnthropic so .messages.create returns api_response.

    Returns ``(cls_mock, create_mock)`` so tests can both substitute the
    SDK class and inspect the kwargs the adapter forwards.
    """
    instance = MagicMock()
    create_mock = AsyncMock(return_value=api_response)
    instance.messages = MagicMock()
    instance.messages.create = create_mock
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, create_mock


_SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "TestResponse",
        "schema": _SIMPLE_SCHEMA,
        "strict": True,
    },
}


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Reset the per-key WARN dedupe set so tests in this module don't
    observe state leaked from earlier tests in the same process."""
    anthropic_native._reset_unsupported_kwargs_dedupe()
    yield
    anthropic_native._reset_unsupported_kwargs_dedupe()


# ---------------------------------------------------------------------------
# response_format translation
# ---------------------------------------------------------------------------


class TestResponseFormatTranslation:
    @pytest.mark.asyncio
    async def test_pops_response_format_before_sdk_call(self):
        """The synthetic tool MUST appear in ``tools``; ``response_format``
        MUST be absent from the kwargs forwarded to ``messages.create`` —
        the Anthropic SDK would reject it."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        # Synthetic tool injected by the adapter (no handler in play).
        tools = kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == SYNTHETIC_FORMAT_TOOL_NAME
        # Schema flows through verbatim into Anthropic's input_schema.
        assert tools[0]["input_schema"] == _SIMPLE_SCHEMA

    @pytest.mark.asyncio
    async def test_handler_already_injected_is_noop(self):
        """When handler injected the synthetic tool upstream, the adapter
        MUST NOT re-inject. Only one synthetic in the final tools list."""
        handler_injected_tool = schema_to_synthetic_tool(_SIMPLE_SCHEMA)

        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [handler_injected_tool],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        tools = kwargs["tools"]
        synthetic_count = sum(
            1 for t in tools if t.get("name") == SYNTHETIC_FORMAT_TOOL_NAME
        )
        assert synthetic_count == 1, (
            f"Expected exactly one synthetic tool, got {synthetic_count}: {tools}"
        )

    @pytest.mark.asyncio
    async def test_no_tools_forces_synthetic_tool_choice(self):
        """``response_format`` set, no real tools → tool_choice forces the
        synthetic (single deterministic round-trip)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["tool_choice"] == {
            "type": "tool",
            "name": SYNTHETIC_FORMAT_TOOL_NAME,
        }

    @pytest.mark.asyncio
    async def test_real_tools_present_uses_auto(self):
        """``response_format`` + a real tool → tool_choice="auto" so the model
        can still call real tools mid-agentic-flow."""
        real_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up weather.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [real_tool],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        # Anthropic-shape "auto" — translation happens later in the same
        # _build_create_kwargs run; the adapter sets tool_choice="auto"
        # (litellm string), the downstream translator converts to dict.
        assert kwargs["tool_choice"] == {"type": "auto"}
        # Both tools present.
        tool_names = {t.get("name") for t in kwargs["tools"]}
        assert tool_names == {"get_weather", SYNTHETIC_FORMAT_TOOL_NAME}

    @pytest.mark.asyncio
    async def test_caller_tool_choice_none_warns_and_drops_tools(self, caplog):
        """Caller's tool_choice='none' wins; structured output NOT enforced.
        WARN MUST surface the inconsistency."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "response_format": _RESPONSE_FORMAT,
                        "tool_choice": "none",
                    },
                    model="anthropic/claude-sonnet-4-5",
                    api_key="sk-test",
                )

        kwargs = create_mock.call_args.kwargs
        # tool_choice='none' drops tools entirely (existing behavior).
        assert "tools" not in kwargs or not kwargs.get("tools")
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "tool_choice='none'" in m and "Structured output not enforced" in m
            for m in warn_msgs
        ), f"Expected WARN about tool_choice='none'; got: {warn_msgs}"

    @pytest.mark.asyncio
    async def test_caller_tool_choice_forced_real_tool_kept(self):
        """Caller's forced tool_choice (real tool) wins; synthetic still
        appended so it's available on subsequent iterations."""
        real_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "parameters": {"type": "object"},
            },
        }
        forced_choice = {
            "type": "function",
            "function": {"name": "get_weather"},
        }
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [real_tool],
                    "response_format": _RESPONSE_FORMAT,
                    "tool_choice": forced_choice,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        # Caller's forced tool_choice survives translation (Anthropic shape).
        assert kwargs["tool_choice"] == {"type": "tool", "name": "get_weather"}
        # Synthetic still in the tools list for next iteration.
        tool_names = {t.get("name") for t in kwargs["tools"]}
        assert tool_names == {"get_weather", SYNTHETIC_FORMAT_TOOL_NAME}

    @pytest.mark.asyncio
    async def test_system_instruction_appended_when_translating(self):
        """When adapter translates response_format, the system message MUST
        be augmented with the advisory addendum."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [
                        {"role": "system", "content": "You are helpful."},
                        {"role": "user", "content": "Hi."},
                    ],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        system = kwargs["system"]
        assert isinstance(system, str)
        assert system.startswith("You are helpful.")
        assert SYNTHETIC_FORMAT_TOOL_NAME in system

    @pytest.mark.asyncio
    async def test_system_instruction_synthesized_when_no_system(self):
        """No system message + adapter-translated response_format → system
        is synthesized from the advisory addendum alone."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        # system kwarg present and contains the synthetic tool reference.
        assert "system" in kwargs
        assert SYNTHETIC_FORMAT_TOOL_NAME in kwargs["system"]

    @pytest.mark.asyncio
    async def test_malformed_response_format_pops_without_translation(self):
        """Malformed response_format (missing json_schema.schema) is popped
        but NO synthetic injection happens. No crash."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": {"type": "json_object"},  # not json_schema
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        # No synthetic injected (extract returned None).
        assert "tools" not in kwargs or not kwargs.get("tools")


# ---------------------------------------------------------------------------
# request_timeout → timeout rename
# ---------------------------------------------------------------------------


class TestRequestTimeoutRename:
    @pytest.mark.asyncio
    async def test_request_timeout_translates_to_timeout(self):
        """LiteLLM-shape ``request_timeout`` MUST translate to the Anthropic
        SDK kwarg name ``timeout``."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "request_timeout": 42,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "request_timeout" not in kwargs
        assert kwargs.get("timeout") == 42

    @pytest.mark.asyncio
    async def test_caller_supplied_timeout_wins_when_both_set(self):
        """If caller sets BOTH ``timeout=`` and ``request_timeout=``, the
        explicit ``timeout`` wins. ``request_timeout`` is still popped."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "timeout": 10,
                    "request_timeout": 99,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "request_timeout" not in kwargs
        assert kwargs["timeout"] == 10

    @pytest.mark.asyncio
    async def test_request_timeout_does_not_warn(self, caplog):
        """Post-fix, ``request_timeout`` MUST NOT trigger the unsupported-
        kwarg WARN (it is translated, not dropped)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "request_timeout": 90,
                    },
                    model="anthropic/claude-sonnet-4-5",
                    api_key="sk-test",
                )

        warns_about_rt = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "request_timeout" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warns_about_rt == [], (
            f"request_timeout should not WARN post-fix; got: {warns_about_rt}"
        )


# ---------------------------------------------------------------------------
# response_format no longer warns
# ---------------------------------------------------------------------------


class TestResponseFormatNoLongerWarns:
    @pytest.mark.asyncio
    async def test_response_format_does_not_warn(self, caplog):
        """Post-fix, ``response_format`` MUST NOT trigger the unsupported-
        kwarg WARN (it is translated, not dropped)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "response_format": _RESPONSE_FORMAT,
                    },
                    model="anthropic/claude-sonnet-4-5",
                    api_key="sk-test",
                )

        warns_about_rf = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "response_format" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warns_about_rf == [], (
            f"response_format should not WARN post-fix; got: {warns_about_rf}"
        )


# ---------------------------------------------------------------------------
# Dedupe reset hook (logger fix verification)
# ---------------------------------------------------------------------------


class TestDedupeResetHook:
    def test_reset_unsupported_kwargs_dedupe_clears_set(self):
        """After reset, the WARN fires again for a previously-seen kwarg."""
        anthropic_native._warn_unsupported_kwarg_once("madeup_kwarg")
        assert "madeup_kwarg" in anthropic_native._logged_unsupported_kwargs

        anthropic_native._reset_unsupported_kwargs_dedupe()

        assert "madeup_kwarg" not in anthropic_native._logged_unsupported_kwargs

    def test_warn_propagates_to_root_after_reset(self, caplog):
        """After reset, the WARN for a deliberate unsupported kwarg MUST
        reach the captured logger. This is the discovery surface for the
        next silently-dropped kwarg regression."""
        anthropic_native._reset_unsupported_kwargs_dedupe()

        with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
            anthropic_native._warn_unsupported_kwarg_once("totally_made_up_kwarg")

        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "totally_made_up_kwarg" in m and "dropping unsupported kwarg" in m
            for m in warn_msgs
        ), f"Expected WARN about totally_made_up_kwarg; got: {warn_msgs}"
