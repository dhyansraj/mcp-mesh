"""Unit tests for GeminiHandler native SDK dispatch (issue #834 PR 3).

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
  * HINT-mode preservation: the existing prepare_request behavior (omit
    response_format when tools present + Pydantic output) is unchanged on
    the native dispatch path — the dispatch decision is independent of the
    prepare_request output.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

pytest.importorskip(
    "google.genai",
    reason="GeminiHandler native dispatch tests require the google-genai SDK",
)

from _mcp_mesh.engine.provider_handlers import gemini_handler as gemini_handler_module
from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler


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
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "OFF"])
    def test_returns_false_when_flag_explicitly_off(self, value):
        """Explicit opt-out via MCP_MESH_NATIVE_LLM=0/false/no/off forces the
        LiteLLM fallback path even when the SDK is importable."""
        handler = GeminiHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = value

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_unset_but_sdk_missing(self):
        """SDK gate: with the SDK missing, native dispatch is unavailable
        even on the default-ON path. Falls back to LiteLLM with a one-time
        INFO log. (In normal installs this branch never fires — google-genai
        is a base dep.)"""
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_false_when_flag_explicit_on_but_sdk_missing(self):
        """Even with explicit MCP_MESH_NATIVE_LLM=1, a missing SDK falls back."""
        handler = GeminiHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=False,
        ):
            assert handler.has_native() is False

    def test_returns_true_when_flag_explicit_on_and_sdk_available(self):
        """Explicit-enable matches the default; preserved for backward compat
        with existing deployments that set MCP_MESH_NATIVE_LLM=1."""
        handler = GeminiHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "1"

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=True,
        ):
            assert handler.has_native() is True

    @pytest.mark.parametrize("value", ["", "1", "true", "True", "yes", "ON"])
    def test_default_on_accepts_unset_or_truthy_flag_values(self, value):
        """Empty string (unset → default), and any truthy value all enable
        native dispatch when the SDK is importable."""
        handler = GeminiHandler()
        if value:
            os.environ["MCP_MESH_NATIVE_LLM"] = value
        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
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
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.is_available",
                return_value=False,
            ),
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.log_fallback_once"
            ) as mock_log,
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.is_fallback_logged",
                side_effect=[False, True],
            ),
        ):
            handler.has_native()
            handler.has_native()
            assert mock_log.call_count == 1


# ---------------------------------------------------------------------------
# complete() / complete_stream() dispatch
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_dispatches_to_native_module(self):
        handler = GeminiHandler()
        sentinel = MagicMock(name="response")
        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.complete",
            new=AsyncMock(return_value=sentinel),
        ) as mock_complete:
            result = await handler.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="gemini/gemini-2.0-flash",
                api_key="GAK-test",
                base_url=None,
            )

        assert result is sentinel
        mock_complete.assert_awaited_once()
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["model"] == "gemini/gemini-2.0-flash"
        assert kwargs["api_key"] == "GAK-test"

    @pytest.mark.asyncio
    async def test_complete_stream_dispatches_to_native_module(self):
        handler = GeminiHandler()

        async def _fake_iter():
            yield "chunk1"
            yield "chunk2"

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.complete_stream",
            return_value=_fake_iter(),
        ) as mock_stream:
            stream = await handler.complete_stream(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="gemini/gemini-2.0-flash",
                api_key="GAK-test",
            )
            chunks = [c async for c in stream]

        assert chunks == ["chunk1", "chunk2"]
        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args.kwargs
        assert kwargs["model"] == "gemini/gemini-2.0-flash"
        assert kwargs["api_key"] == "GAK-test"

    @pytest.mark.asyncio
    async def test_vertex_model_dispatches_through_native(self):
        """vertex_ai/* models route through the same native adapter as
        gemini/* — the handler doesn't care about the prefix; backend
        selection happens inside ``gemini_native._build_client``."""
        handler = GeminiHandler()
        sentinel = MagicMock(name="vertex_response")
        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.complete",
            new=AsyncMock(return_value=sentinel),
        ) as mock_complete:
            result = await handler.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="vertex_ai/gemini-2.0-flash",
            )
        assert result is sentinel
        assert mock_complete.await_args.kwargs["model"] == (
            "vertex_ai/gemini-2.0-flash"
        )


# ---------------------------------------------------------------------------
# One-time DEBUG dispatch-status log
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_dispatch_status_log():
    """Reset the module-level one-time guard so each test starts clean."""
    original = gemini_handler_module._DISPATCH_STATUS_LOGGED
    gemini_handler_module._DISPATCH_STATUS_LOGGED = False
    yield
    gemini_handler_module._DISPATCH_STATUS_LOGGED = original


class TestDispatchStatusLog:
    """``has_native()`` should fire a DEBUG log exactly once per process so
    operators running ``meshctl ... --debug`` can confirm whether the native
    Gemini SDK is in play (or whether mesh has fallen back to LiteLLM)."""

    def test_logs_enabled_when_sdk_available_and_flag_unset(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.gemini_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Gemini native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "enabled" in status_records[0].message

    def test_logs_disabled_when_flag_explicitly_off(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = GeminiHandler()
        os.environ["MCP_MESH_NATIVE_LLM"] = "0"

        with caplog.at_level(
            logging.DEBUG,
            logger="_mcp_mesh.engine.provider_handlers.gemini_handler",
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Gemini native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "MCP_MESH_NATIVE_LLM=0" in status_records[0].message

    def test_logs_disabled_when_sdk_missing(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.gemini_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.is_available",
                return_value=False,
            ),
        ):
            handler.has_native()

        status_records = [
            r for r in caplog.records if "Gemini native dispatch:" in r.message
        ]
        assert len(status_records) == 1
        assert status_records[0].levelno == logging.DEBUG
        assert "disabled" in status_records[0].message
        assert "google-genai SDK not installed" in status_records[0].message
        assert "mcp-mesh[gemini]" in status_records[0].message

    def test_log_fires_only_once_across_calls(
        self, caplog, _reset_dispatch_status_log
    ):
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ

        with (
            caplog.at_level(
                logging.DEBUG,
                logger="_mcp_mesh.engine.provider_handlers.gemini_handler",
            ),
            patch(
                "_mcp_mesh.engine.native_clients.gemini_native.is_available",
                return_value=True,
            ),
        ):
            handler.has_native()
            first_count = sum(
                1 for r in caplog.records if "Gemini native dispatch:" in r.message
            )
            handler.has_native()
            second_count = sum(
                1 for r in caplog.records if "Gemini native dispatch:" in r.message
            )

        assert first_count == 1
        assert second_count == 1

    def test_is_dispatch_status_logged_short_circuits_after_first_call(
        self, _reset_dispatch_status_log
    ):
        """``has_native()`` consults ``is_dispatch_status_logged()`` so it can
        skip the log-once call frame on the hot path. Verify the getter
        flips False → True after the first ``has_native()`` invocation."""
        handler = GeminiHandler()
        assert "MCP_MESH_NATIVE_LLM" not in os.environ
        assert gemini_handler_module.is_dispatch_status_logged() is False

        with patch(
            "_mcp_mesh.engine.native_clients.gemini_native.is_available",
            return_value=True,
        ):
            handler.has_native()

        assert gemini_handler_module.is_dispatch_status_logged() is True


# ---------------------------------------------------------------------------
# HINT-mode preservation
# ---------------------------------------------------------------------------


class _SamplePydantic(BaseModel):
    answer: str
    confidence: int


class TestHintModePreservation:
    """The existing GeminiHandler.prepare_request behavior must be unchanged
    on the native dispatch path:

    * No tools + Pydantic output → response_format IS attached (STRICT mode).
    * Tools + Pydantic output → response_format is OMITTED (HINT mode; the
      schema lives in the system prompt instead — workaround for the Gemini
      API infinite-tool-loop bug for that combination).

    The native adapter just executes whatever request_params it receives;
    the dispatch decision (has_native()) is independent of prepare_request's
    output. This test pins the behavior end-to-end so a future refactor of
    either piece doesn't accidentally regress the workaround.
    """

    def test_no_tools_pydantic_output_attaches_response_format(self):
        handler = GeminiHandler()
        params = handler.prepare_request(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
            output_type=_SamplePydantic,
        )
        # STRICT mode: response_format IS attached when no tools present.
        assert "response_format" in params
        assert params["response_format"]["type"] == "json_schema"

    def test_tools_with_pydantic_output_omits_response_format(self):
        """The HINT-mode workaround: when tools + Pydantic output, the
        handler MUST NOT attach response_format (Gemini API has a non-
        deterministic infinite-tool-loop bug for that combo). The schema
        gets surfaced through the system prompt by ``format_system_prompt``
        instead."""
        handler = GeminiHandler()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        params = handler.prepare_request(
            messages=[{"role": "user", "content": "Hi"}],
            tools=tools,
            output_type=_SamplePydantic,
        )
        # response_format MUST be absent when tools + Pydantic output.
        assert "response_format" not in params
        # Tools still flow through.
        assert params["tools"] == tools

    def test_str_output_skips_response_format(self):
        handler = GeminiHandler()
        params = handler.prepare_request(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
            output_type=str,
        )
        assert "response_format" not in params
