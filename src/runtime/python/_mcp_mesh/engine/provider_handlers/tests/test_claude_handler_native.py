"""Unit tests for ClaudeHandler native SDK dispatch (issue #834).

Covers:
  * has_native() returns True by default when the SDK is importable
    (opt-out semantics — MCP_MESH_NATIVE_LLM=0 disables)
  * has_native() returns False when MCP_MESH_NATIVE_LLM is explicitly set
    to a falsy value (0/false/no/off)
  * has_native() returns False when the SDK is missing (regardless of
    flag value)
  * has_native() returns True when MCP_MESH_NATIVE_LLM=1 (or other truthy
    value) and the SDK is available — same as the default
  * has_native() emits a one-time DEBUG dispatch-status log on first call
    so ``meshctl ... --debug`` runs can confirm whether native or LiteLLM
    is in play
  * complete()/complete_stream() dispatch into the native module when
    has_native() is True; raise NotImplementedError on the base class
  * apply_structured_output(): on the native path, stamps the synthetic
    format tool sentinels and augments the system prompt; on the LiteLLM
    path, preserves the existing HINT-mode behavior unchanged
"""

from __future__ import annotations

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from _mcp_mesh.engine.provider_handlers import claude_handler as claude_handler_module
from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
    BaseProviderHandler,
)
from _mcp_mesh.engine.provider_handlers.claude_handler import (
    SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION,
    SYNTHETIC_FORMAT_TOOL_NAME,
    ClaudeHandler,
)


# ---------------------------------------------------------------------------
# has_native() gating
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env():
    """Make sure the feature flag does not leak between tests."""
    original = os.environ.pop("MCP_MESH_NATIVE_LLM", None)
    yield
    os.environ.pop("MCP_MESH_NATIVE_LLM", None)
    if original is not None:
        os.environ["MCP_MESH_NATIVE_LLM"] = original


class TestHasNative:
    def test_returns_true_when_flag_unset_and_sdk_available(self):
        """Default ON: with the env var unset and the SDK importable, native
        dispatch is enabled. This is the opt-out semantics flip — previously
        the flag had to be set explicitly to enable native dispatch.
        """
        handler = ClaudeHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "OFF"])
    def test_returns_false_when_flag_explicitly_off(self, value):
        """Explicit opt-out via MCP_MESH_NATIVE_LLM=0/false/no/off forces the
        LiteLLM fallback path even when the SDK is importable."""
        handler = ClaudeHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = value

        # Even with SDK present, explicit opt-out wins.
        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_unset_but_sdk_missing(self):
        """SDK gate: with the SDK missing, native dispatch is unavailable
        even on the new default-ON path. Falls back to LiteLLM with a
        one-time INFO log."""
        handler = ClaudeHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_explicit_on_but_sdk_missing(self):
        """Even with explicit MCP_MESH_NATIVE_LLM=1, a missing SDK falls back."""
        handler = ClaudeHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_true_when_flag_explicit_on_and_sdk_available(self):
        """Explicit-enable matches the default; preserved for backward compat
        with existing deployments that set MCP_MESH_NATIVE_LLM=1."""
        handler = ClaudeHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["", "1", "true", "True", "yes", "ON"])
    def test_default_on_accepts_unset_or_truthy_flag_values(self, value):
        """Empty string (unset → default), and any truthy value all enable
        native dispatch when the SDK is importable."""
        handler = ClaudeHandler()
        if value:
            os.environ["MCP_MESH_NATIVE_LLM"] = value
        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    def test_logs_fallback_once_when_sdk_missing(self):
        """When native is attempted (default ON) but the SDK is missing,
        log_fallback_once() must be invoked so the user sees a single
        nudge per process."""
        handler = ClaudeHandler()
        # Default ON path: do NOT set the flag.
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            patch(
                "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
                return_value=False,
            ),
            patch(
                "_mcp_mesh.engine.native_clients.anthropic_native.log_fallback_once"
            ) as mock_log,
        ):
            handler.has_native()
            handler.has_native()  # second call — log function still invoked,
            # but the function itself dedupes.
            assert mock_log.call_count == 2  # called every time; fn dedupes


# ---------------------------------------------------------------------------
# complete() dispatch
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_dispatches_to_native_module(self):
        handler = ClaudeHandler()
        sentinel = MagicMock(name="response")
        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.complete",
            new=AsyncMock(return_value=sentinel),
        ) as mock_complete:
            result = await handler.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
                base_url="https://api.example.com",
            )

        assert result is sentinel
        mock_complete.assert_awaited_once()
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["model"] == "anthropic/claude-sonnet-4-5"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["base_url"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_complete_stream_dispatches_to_native_module(self):
        handler = ClaudeHandler()

        async def _fake_iter():
            yield "chunk1"
            yield "chunk2"

        with patch(
            "_mcp_mesh.engine.native_clients.anthropic_native.complete_stream",
            return_value=_fake_iter(),
        ) as mock_stream:
            stream = await handler.complete_stream(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )
            chunks = [c async for c in stream]

        assert chunks == ["chunk1", "chunk2"]
        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args.kwargs
        assert kwargs["model"] == "anthropic/claude-sonnet-4-5"
        assert kwargs["api_key"] == "sk-test"


# ---------------------------------------------------------------------------
# Base class default: NotImplementedError
# ---------------------------------------------------------------------------


class _BareHandler(BaseProviderHandler):
    """Concrete subclass with the bare minimum to instantiate."""

    def __init__(self):
        super().__init__(vendor="bare")

    def prepare_request(self, messages, tools, output_type, **kwargs):
        return {"messages": messages}

    def format_system_prompt(self, base_prompt, tool_schemas, output_type):
        return base_prompt


class TestBaseHandlerDefault:
    def test_has_native_default_false(self):
        assert _BareHandler().has_native() is False

    @pytest.mark.asyncio
    async def test_complete_default_raises(self):
        with pytest.raises(NotImplementedError):
            await _BareHandler().complete(
                {"messages": []}, model="x/y", api_key=None
            )

    @pytest.mark.asyncio
    async def test_complete_stream_default_raises(self):
        with pytest.raises(NotImplementedError):
            await _BareHandler().complete_stream(
                {"messages": []}, model="x/y", api_key=None
            )


# ---------------------------------------------------------------------------
# apply_structured_output(): native path injects synthetic-tool sentinels;
# LiteLLM path preserves existing HINT-mode behavior unchanged.
# ---------------------------------------------------------------------------


class _Trip(BaseModel):
    destination: str
    days: int


def _trip_schema() -> dict:
    return _Trip.model_json_schema()


@pytest.fixture
def _native_on(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → True for the duration of the test.

    Patches the module-level lookup the handler uses, so we don't rely on the
    real anthropic SDK being importable in CI.
    """
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: True)
    yield


@pytest.fixture
def _native_off(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → False — LiteLLM path."""
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: False)
    yield


class TestApplyStructuredOutputNative:
    def test_stamps_synthetic_format_sentinel(self, _native_on):
        handler = ClaudeHandler()
        params: dict = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Plan a trip."},
            ]
        }
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert (
            result["_mesh_synthetic_format_tool_name"]
            == SYNTHETIC_FORMAT_TOOL_NAME
        )
        synth = result["_mesh_synthetic_format_tool"]
        assert synth["type"] == "function"
        assert synth["function"]["name"] == SYNTHETIC_FORMAT_TOOL_NAME
        # Schema is forwarded as the tool's parameters.
        params_schema = synth["function"]["parameters"]
        assert "destination" in params_schema["properties"]
        assert result["_mesh_synthetic_format_output_type_name"] == "Trip"

    def test_does_not_set_response_format_or_hint_flags(self, _native_on):
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}],
            # Pre-existing HINT flag (should be cleared on native path).
            "_mesh_hint_mode": True,
        }
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert "response_format" not in result
        assert "_mesh_hint_mode" not in result
        assert "_mesh_hint_schema" not in result

    def test_appends_must_call_tool_instruction_to_system_message(
        self, _native_on
    ):
        handler = ClaudeHandler()
        original = "You are a travel planner."
        params: dict = {
            "messages": [
                {"role": "system", "content": original},
                {"role": "user", "content": "Plan a trip."},
            ]
        }
        handler.apply_structured_output(_trip_schema(), "Trip", params)

        new_system = params["messages"][0]["content"]
        assert new_system.startswith(original)
        assert "__mesh_format_response" in new_system
        # Spot-check the key directive — "must call this tool".
        assert "MUST call" in new_system

    def test_preserves_cache_control_on_system_content_blocks(self, _native_on):
        """When the system message has already been decorated with prompt-cache
        blocks (list-of-blocks shape), the synthetic instruction is APPENDED as
        a new block so cache_control on the original blocks is preserved.
        """
        handler = ClaudeHandler()
        original_block = {
            "type": "text",
            "text": "Original system text.",
            "cache_control": {"type": "ephemeral"},
        }
        params: dict = {
            "messages": [
                {"role": "system", "content": [original_block]},
                {"role": "user", "content": "Hi"},
            ]
        }
        handler.apply_structured_output(_trip_schema(), "Trip", params)

        blocks = params["messages"][0]["content"]
        assert isinstance(blocks, list)
        assert blocks[0] == original_block  # cache_control intact
        assert any(
            b.get("type") == "text" and "__mesh_format_response" in b.get("text", "")
            for b in blocks[1:]
        )

    def test_synthesizes_system_message_when_absent(self, _native_on):
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "user", "content": "Hi."}]}
        handler.apply_structured_output(_trip_schema(), "Trip", params)

        msgs = params["messages"]
        assert msgs[0]["role"] == "system"
        assert "__mesh_format_response" in msgs[0]["content"]


class TestApplyStructuredOutputLiteLLMUnchanged:
    """The LiteLLM path MUST keep the existing HINT-mode behavior."""

    def test_sets_hint_mode_flags_not_synthetic(self, _native_off):
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "You are helpful."}]
        }
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert result["_mesh_hint_mode"] is True
        assert result["_mesh_hint_schema"] is not None
        assert result["_mesh_hint_output_type_name"] == "Trip"
        # Native sentinels MUST NOT be present on the LiteLLM path.
        assert "_mesh_synthetic_format_tool" not in result
        assert "_mesh_synthetic_format_tool_name" not in result

    def test_force_response_format_env_flag_still_works_on_litellm(
        self, _native_off, monkeypatch
    ):
        """The MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT env flag is unchanged for
        the LiteLLM path — it routes to the base impl that sets response_format.
        """
        handler = ClaudeHandler()
        monkeypatch.setenv("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", "true")
        params: dict = {
            "messages": [{"role": "system", "content": "You are helpful."}]
        }
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert "response_format" in result
        assert result["response_format"]["type"] == "json_schema"
        # No HINT or synthetic flags on the base path.
        assert "_mesh_hint_mode" not in result
        assert "_mesh_synthetic_format_tool" not in result

    def test_force_response_format_env_flag_no_op_on_native(
        self, _native_on, monkeypatch
    ):
        """On the native path the env flag is intentionally a no-op —
        synthetic-tool injection is the canonical native behavior.
        """
        handler = ClaudeHandler()
        monkeypatch.setenv("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", "true")
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert "response_format" not in result
        assert (
            result["_mesh_synthetic_format_tool_name"]
            == SYNTHETIC_FORMAT_TOOL_NAME
        )


# ---------------------------------------------------------------------------
# One-time DEBUG dispatch-status log (issue #834 follow-up)
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_dispatch_status_log():
    """Reset the module-level one-time guard so each test starts clean.

    The log is fire-once per process — we have to flip the sentinel back to
    False so subsequent tests can observe the log being emitted.
    """
    original = claude_handler_module._DISPATCH_STATUS_LOGGED
    claude_handler_module._DISPATCH_STATUS_LOGGED = False
    yield
    claude_handler_module._DISPATCH_STATUS_LOGGED = original


class TestDispatchStatusLog:
    """``has_native()`` should fire a DEBUG log exactly once per process so
    operators running ``meshctl ... --debug`` can confirm whether the native
    Anthropic SDK is in play (or whether mesh has fallen back to LiteLLM)."""

    def test_logs_enabled_when_sdk_available_and_flag_unset(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = ClaudeHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.claude_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Claude native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "enabled" in status_records[0].message

    def test_logs_disabled_when_flag_explicitly_off(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = ClaudeHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "0"

        with caplog.at_level(
            logging.DEBUG,
            logger="_mcp_mesh.engine.provider_handlers.claude_handler",
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Claude native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "MCP_MESH_NATIVE_LLM=0" in status_records[0].message

    def test_logs_disabled_when_sdk_missing(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = ClaudeHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.claude_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
                return_value=False,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Claude native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "anthropic SDK not installed" in status_records[0].message
        assert "mcp-mesh[anthropic]" in status_records[0].message

    def test_log_fires_only_once_across_calls(
        self, caplog, _reset_dispatch_status_log
    ):
        """Second call to has_native() must NOT re-emit the dispatch-status log
        — the one-time guard is the whole point of the helper."""
        handler = ClaudeHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.claude_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.anthropic_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()
            first_count = sum(
                1 for r in caplog.records if "Claude native dispatch:" in r.message
            )
            handler.has_native()
            second_count = sum(
                1 for r in caplog.records if "Claude native dispatch:" in r.message
            )

        assert first_count == 1
        assert second_count == 1  # no new log emitted on the second call
