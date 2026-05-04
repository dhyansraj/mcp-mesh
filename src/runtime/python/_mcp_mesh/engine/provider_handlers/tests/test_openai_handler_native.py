"""Unit tests for OpenAIHandler native SDK dispatch (issue #834 PR 2).

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
    has_native() is True
"""

from __future__ import annotations

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "openai", reason="OpenAIHandler native dispatch tests require the openai SDK"
)

from _mcp_mesh.engine.provider_handlers import openai_handler as openai_handler_module
from _mcp_mesh.engine.provider_handlers.openai_handler import OpenAIHandler


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
        handler = OpenAIHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "OFF"])
    def test_returns_false_when_flag_explicitly_off(self, value):
        """Explicit opt-out via MCP_MESH_NATIVE_LLM=0/false/no/off forces the
        LiteLLM fallback path even when the SDK is importable."""
        handler = OpenAIHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = value

        # Even with SDK present, explicit opt-out wins.
        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_unset_but_sdk_missing(self):
        """SDK gate: with the SDK missing, native dispatch is unavailable
        even on the default-ON path. Falls back to LiteLLM with a one-time
        INFO log. (In normal installs this branch never fires — openai is
        a base dep.)"""
        handler = OpenAIHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_explicit_on_but_sdk_missing(self):
        """Even with explicit MCP_MESH_NATIVE_LLM=1, a missing SDK falls back."""
        handler = OpenAIHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_true_when_flag_explicit_on_and_sdk_available(self):
        """Explicit-enable matches the default; preserved for backward compat
        with existing deployments that set MCP_MESH_NATIVE_LLM=1."""
        handler = OpenAIHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["", "1", "true", "True", "yes", "ON"])
    def test_default_on_accepts_unset_or_truthy_flag_values(self, value):
        """Empty string (unset → default), and any truthy value all enable
        native dispatch when the SDK is importable."""
        handler = OpenAIHandler()
        if value:
            os.environ["MCP_MESH_NATIVE_LLM"] = value
        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    def test_logs_fallback_once_when_sdk_missing(self):
        """When native is attempted (default ON) but the SDK is missing,
        log_fallback_once() must be invoked so the user sees a single
        nudge per process. The handler also short-circuits the call on
        subsequent misses via ``is_fallback_logged()`` — verify both:
        the first call invokes the log function, the second one does not.
        """
        handler = OpenAIHandler()
        # Default ON path: do NOT set the flag.
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.is_available",
                return_value=False,
            ),
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.log_fallback_once"
            ) as mock_log,
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.is_fallback_logged",
                side_effect=[False, True],
            ),
        ):
            handler.has_native()
            handler.has_native()
            # First call invokes log_fallback_once (is_fallback_logged → False);
            # second call short-circuits at the call site (is_fallback_logged
            # → True) — total log_fallback_once invocations = 1.
            assert mock_log.call_count == 1


# ---------------------------------------------------------------------------
# complete() / complete_stream() dispatch
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_dispatches_to_native_module(self):
        handler = OpenAIHandler()
        sentinel = MagicMock(name="response")
        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.complete",
            new=AsyncMock(return_value=sentinel),
        ) as mock_complete:
            result = await handler.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
                base_url="https://api.example.com",
            )

        assert result is sentinel
        mock_complete.assert_awaited_once()
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o-mini"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["base_url"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_complete_stream_dispatches_to_native_module(self):
        handler = OpenAIHandler()

        async def _fake_iter():
            yield "chunk1"
            yield "chunk2"

        with patch(
            "_mcp_mesh.engine.native_clients.openai_native.complete_stream",
            return_value=_fake_iter(),
        ) as mock_stream:
            stream = await handler.complete_stream(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = [c async for c in stream]

        assert chunks == ["chunk1", "chunk2"]
        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o-mini"
        assert kwargs["api_key"] == "sk-test"


# ---------------------------------------------------------------------------
# One-time DEBUG dispatch-status log
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_dispatch_status_log():
    """Reset the module-level one-time guard so each test starts clean.

    The log is fire-once per process — we have to flip the sentinel back to
    False so subsequent tests can observe the log being emitted.
    """
    original = openai_handler_module._DISPATCH_STATUS_LOGGED
    openai_handler_module._DISPATCH_STATUS_LOGGED = False
    yield
    openai_handler_module._DISPATCH_STATUS_LOGGED = original


class TestDispatchStatusLog:
    """``has_native()`` should fire a DEBUG log exactly once per process so
    operators running ``meshctl ... --debug`` can confirm whether the native
    OpenAI SDK is in play (or whether mesh has fallen back to LiteLLM)."""

    def test_logs_enabled_when_sdk_available_and_flag_unset(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = OpenAIHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.openai_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "OpenAI native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "enabled" in status_records[0].message

    def test_logs_disabled_when_flag_explicitly_off(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = OpenAIHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "0"

        with caplog.at_level(
            logging.DEBUG,
            logger="_mcp_mesh.engine.provider_handlers.openai_handler",
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "OpenAI native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "MCP_MESH_NATIVE_LLM=0" in status_records[0].message

    def test_logs_disabled_when_sdk_missing(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = OpenAIHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.openai_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.is_available",
                return_value=False,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "OpenAI native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "openai SDK not installed" in status_records[0].message
        assert "mcp-mesh[openai]" in status_records[0].message

    def test_log_fires_only_once_across_calls(
        self, caplog, _reset_dispatch_status_log
    ):
        """Second call to has_native() must NOT re-emit the dispatch-status log
        — the one-time guard is the whole point of the helper."""
        handler = OpenAIHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.openai_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.openai_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()
            first_count = sum(
                1 for r in caplog.records if "OpenAI native dispatch:" in r.message
            )
            handler.has_native()
            second_count = sum(
                1 for r in caplog.records if "OpenAI native dispatch:" in r.message
            )

        assert first_count == 1
        assert second_count == 1  # no new log emitted on the second call
